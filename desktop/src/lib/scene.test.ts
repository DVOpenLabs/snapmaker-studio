import { describe, expect, it, vi } from "vitest";
import {
  SceneError, decodeMesh, isAbort, loadScene, newRequestId, sceneErrorText,
  type SceneMesh, type SceneTransport,
} from "./scene";

vi.mock("@/api", () => ({ engineConnection: vi.fn() }));

const REVISION = "a".repeat(64);
const status = (state: string, extra: Record<string, unknown> = {}) => ({
  job_id: "job-1", request_id: "req", state, stage: null, completed: null, total: null, error: null, revision: null, ...extra,
});
const scene = { schema: "scene/1", revision: REVISION, nodes: [], findings: [], limitations: [] };
const noSleep = () => Promise.resolve();

type Call = { route: string; body: unknown };
function transportFor(
  script: Partial<Record<"start" | "status" | "result" | "cancel", ({ status: number; body: unknown } | (() => { status: number; body: unknown }))[]>>,
): { transport: SceneTransport; calls: Call[] } {
  const calls: Call[] = [];
  const queues = Object.fromEntries(Object.entries(script).map(([k, v]) => [k, [...(v as unknown[])]]));
  const transport: SceneTransport = async (route, body) => {
    calls.push({ route, body });
    const q = queues[route] as ({ status: number; body: unknown } | (() => { status: number; body: unknown }))[] | undefined;
    if (!q?.length) return { status: 200, body: status("cancelled") };
    const next = q.length > 1 ? q.shift()! : q[0];
    return typeof next === "function" ? next() : next;
  };
  return { transport, calls };
}

describe("loadScene", () => {
  it("follows a job from queued to the finished scene and asks for the revision it saw", async () => {
    const { transport, calls } = transportFor({
      start: [{ status: 200, body: status("queued") }],
      status: [{ status: 200, body: status("running", { stage: "parsing", completed: 1, total: 4 }) },
        { status: 200, body: status("succeeded", { revision: REVISION }) }],
      result: [{ status: 200, body: scene }],
    });
    const seen: string[] = [];
    const out = await loadScene("p.3mf", {
      signal: new AbortController().signal, transport, sleep: noSleep, onProgress: (p) => seen.push(p.state),
    });
    expect(out.schema).toBe("scene/1");
    expect(seen).toEqual(["queued", "running", "succeeded"]);
    expect(calls.find((c) => c.route === "result")?.body).toEqual({ job_id: "job-1", expected_revision: REVISION });
    expect(calls.some((c) => c.route === "cancel")).toBe(false);
  });

  it("uses a fresh request id for every generation", async () => {
    const ids = new Set<string>();
    for (let i = 0; i < 20; i++) {
      const { transport, calls } = transportFor({
        start: [{ status: 200, body: status("succeeded", { revision: REVISION }) }],
        result: [{ status: 200, body: scene }],
      });
      await loadScene("p.3mf", { signal: new AbortController().signal, transport, sleep: noSleep });
      ids.add((calls[0].body as { request_id: string }).request_id);
    }
    expect(ids.size).toBe(20);
    expect(newRequestId()).not.toBe(newRequestId());
  });

  it("tells the engine to cancel when the caller aborts, and stops with an AbortError", async () => {
    const controller = new AbortController();
    const { transport, calls } = transportFor({
      start: [{ status: 200, body: status("running") }],
      status: [{ status: 200, body: status("running") }],
    });
    const sleep = vi.fn(async () => { controller.abort(); });
    const failure = await loadScene("p.3mf", { signal: controller.signal, transport, sleep }).catch((e) => e);
    expect(isAbort(failure)).toBe(true);
    expect(calls.filter((c) => c.route === "cancel")).toEqual([{ route: "cancel", body: { job_id: "job-1" } }]);
  });

  it("cancels a job that was started just before the caller aborted", async () => {
    const controller = new AbortController();
    const { transport, calls } = transportFor({ start: [{ status: 200, body: status("queued") }] });
    const wrapped: SceneTransport = async (route, body, signal) => {
      const r = await transport(route, body, signal);
      if (route === "start") controller.abort();
      return r;
    };
    const failure = await loadScene("p.3mf", { signal: controller.signal, transport: wrapped, sleep: noSleep }).catch((e) => e);
    expect(isAbort(failure)).toBe(true);
    expect(calls.map((c) => c.route)).toEqual(["start", "cancel"]);
  });

  it("does not start anything when it is already aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const { transport, calls } = transportFor({});
    const failure = await loadScene("p.3mf", { signal: controller.signal, transport }).catch((e) => e);
    expect(isAbort(failure)).toBe(true);
    expect(calls).toEqual([]);
  });

  it.each([
    ["LIMIT_EXCEEDED", "larger than the 3D view can show"],
    ["SOURCE_CHANGED", "changed while it was being read"],
    ["TIMEOUT", "took too long"],
  ])("reports a failed job as %s in plain words", async (code, words) => {
    const { transport } = transportFor({
      start: [{ status: 200, body: status("failed", { error: { code, message: "C:\\private\\path.3mf" } }) }],
    });
    const failure = (await loadScene("p.3mf", { signal: new AbortController().signal, transport, sleep: noSleep }).catch((e) => e)) as SceneError;
    expect(failure).toBeInstanceOf(SceneError);
    expect(failure.code).toBe(code);
    expect(sceneErrorText(failure.code)).toContain(words);
    expect(sceneErrorText(failure.code)).not.toContain("private");
  });

  it("maps an HTTP refusal to its error code and an unknown code to INTERNAL", async () => {
    const refused = transportFor({ start: [{ status: 422, body: { error: "UNSUPPORTED_FORMAT" } }] });
    const a = (await loadScene("p.obj", { signal: new AbortController().signal, transport: refused.transport }).catch((e) => e)) as SceneError;
    expect(a.code).toBe("UNSUPPORTED_FORMAT");
    const odd = transportFor({ start: [{ status: 409, body: { error: "SOMETHING_NEW" } }] });
    const b = (await loadScene("p.3mf", { signal: new AbortController().signal, transport: odd.transport }).catch((e) => e)) as SceneError;
    expect(b.code).toBe("INTERNAL");
  });

  it("rejects a result that is not scene/1", async () => {
    const { transport } = transportFor({
      start: [{ status: 200, body: status("succeeded", { revision: REVISION }) }],
      result: [{ status: 200, body: { schema: "scene/2", nodes: [] } }],
    });
    const failure = (await loadScene("p.3mf", { signal: new AbortController().signal, transport, sleep: noSleep }).catch((e) => e)) as SceneError;
    expect(failure.code).toBe("BAD_RESPONSE");
  });

  it("reports a cancelled job as CANCELLED", async () => {
    const { transport } = transportFor({ start: [{ status: 200, body: status("cancelled") }] });
    const failure = (await loadScene("p.3mf", { signal: new AbortController().signal, transport }).catch((e) => e)) as SceneError;
    expect(failure.code).toBe("CANCELLED");
  });
});

describe("start ordering", () => {
  it("sends a second start only after the first start has been answered, and skips a start whose caller gave up", async () => {
    const order: string[] = [];
    let releaseFirst: () => void = () => undefined;
    const first = new Promise<void>((r) => { releaseFirst = r; });
    const transport: SceneTransport = async (route, body) => {
      if (route === "start") {
        const tag = (body as { path: string }).path;
        order.push(`start:${tag}`);
        if (tag === "a.3mf") await first;
        return { status: 200, body: status("succeeded", { job_id: `job-${tag}`, revision: REVISION }) };
      }
      if (route === "result") return { status: 200, body: scene };
      return { status: 200, body: status("cancelled") };
    };
    const a = loadScene("a.3mf", { signal: new AbortController().signal, transport, sleep: noSleep });
    const giveUp = new AbortController();
    const skipped = loadScene("skipped.3mf", { signal: giveUp.signal, transport, sleep: noSleep }).catch((e) => e);
    const b = loadScene("b.3mf", { signal: new AbortController().signal, transport, sleep: noSleep });
    await new Promise((r) => setTimeout(r, 20));
    expect(order).toEqual(["start:a.3mf"]);
    giveUp.abort();
    releaseFirst();
    await Promise.all([a, b]);
    expect(isAbort(await skipped)).toBe(true);
    expect(order).toEqual(["start:a.3mf", "start:b.3mf"]);
  });
});

describe("decodeMesh", () => {
  const b64 = (bytes: Uint8Array) => btoa(Array.from(bytes, (b) => String.fromCharCode(b)).join(""));
  const mesh = (positions: number[], indices: number[]): SceneMesh => ({
    key: { part: "3D/3dmodel.model", object_id: "1" }, vertex_count: positions.length / 3, triangle_count: indices.length / 3,
    positions_f32le_base64: b64(new Uint8Array(new Float32Array(positions).buffer)),
    indices_u32le_base64: b64(new Uint8Array(new Uint32Array(indices).buffer)), volumes: [],
  });

  it("round-trips little-endian floats and indices", () => {
    const out = decodeMesh(mesh([0, 0, 0, 10, 0, 0, 0, 10.5, 0], [0, 1, 2]));
    expect(Array.from(out.positions)).toEqual([0, 0, 0, 10, 0, 0, 0, 10.5, 0]);
    expect(Array.from(out.indices)).toEqual([0, 1, 2]);
  });

  it("refuses an index past the vertex list and a size that disagrees with the counts", () => {
    expect(() => decodeMesh(mesh([0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 3]))).toThrow(SceneError);
    const short = mesh([0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 2]);
    short.vertex_count = 4;
    expect(() => decodeMesh(short)).toThrow(SceneError);
  });
});
