import { describe, expect, it, vi } from "vitest";
import {
  SceneError, clientId, decodeMesh, isAbort, loadScene, newRequestId, sceneErrorText,
  type SceneMesh, type SceneTransport,
} from "./scene";

vi.mock("@/api", () => ({ engineConnection: vi.fn() }));

const REVISION = "a".repeat(64);
const status = (state: string, extra: Record<string, unknown> = {}) => ({
  job_id: "job-1", request_id: "req", state, stage: null, completed: null, total: null, error: null, revision: null, ...extra,
});
// What /scene/start really answers (backend scene_jobs.py): identity and state only, no stage, progress or error.
const started = (state: string, extra: Record<string, unknown> = {}) => ({
  job_id: "job-1", request_id: "req", state, revision: null, replaced_job_id: null, ...extra,
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
      start: [{ status: 200, body: started("queued") }],
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
        start: [{ status: 200, body: started("succeeded", { revision: REVISION }) }],
        result: [{ status: 200, body: scene }],
      });
      await loadScene("p.3mf", { signal: new AbortController().signal, transport, sleep: noSleep });
      ids.add((calls[0].body as { request_id: string }).request_id);
    }
    expect(ids.size).toBe(20);
    expect(newRequestId()).not.toBe(newRequestId());
  });

  it("tells the engine to cancel by client id and request id when the caller aborts, and stops with an AbortError", async () => {
    const controller = new AbortController();
    const { transport, calls } = transportFor({
      start: [{ status: 200, body: started("running") }],
      status: [{ status: 200, body: status("running") }],
    });
    const sleep = vi.fn(async () => { controller.abort(); });
    const failure = await loadScene("p.3mf", { signal: controller.signal, transport, sleep }).catch((e) => e);
    expect(isAbort(failure)).toBe(true);
    const startBody = calls.find((c) => c.route === "start")!.body as { request_id: string; client_id: string };
    const cancels = calls.filter((c) => c.route === "cancel");
    expect(cancels).toEqual([{ route: "cancel", body: { client_id: clientId, request_id: startBody.request_id } }]);
    expect(Object.keys(cancels[0].body as object).sort()).toEqual(["client_id", "request_id"]); // no job_id
  });

  it("cancels a request whose start was answered just before the caller aborted", async () => {
    const controller = new AbortController();
    const { transport, calls } = transportFor({ start: [{ status: 200, body: started("queued") }] });
    const wrapped: SceneTransport = async (route, body, signal) => {
      const r = await transport(route, body, signal);
      if (route === "start") controller.abort();
      return r;
    };
    const failure = await loadScene("p.3mf", { signal: controller.signal, transport: wrapped, sleep: noSleep }).catch((e) => e);
    expect(isAbort(failure)).toBe(true);
    expect(calls.map((c) => c.route)).toEqual(["start", "cancel"]);
    expect((calls[1].body as { request_id: string }).request_id).toBe((calls[0].body as { request_id: string }).request_id);
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
      // A request id the engine still holds comes back already failed, with no reason in the start answer; the reason is in the status.
      start: [{ status: 200, body: started("failed") }],
      status: [{ status: 200, body: status("failed", { error: { code, message: "C:\\private\\path.3mf" } }) }],
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
      start: [{ status: 200, body: started("succeeded", { revision: REVISION }) }],
      result: [{ status: 200, body: { schema: "scene/2", nodes: [] } }],
    });
    const failure = (await loadScene("p.3mf", { signal: new AbortController().signal, transport, sleep: noSleep }).catch((e) => e)) as SceneError;
    expect(failure.code).toBe("BAD_RESPONSE");
  });

  it("reports a cancelled job as CANCELLED", async () => {
    const { transport } = transportFor({ start: [{ status: 200, body: started("cancelled") }] });
    const failure = (await loadScene("p.3mf", { signal: new AbortController().signal, transport }).catch((e) => e)) as SceneError;
    expect(failure.code).toBe("CANCELLED");
  });
});

describe("a start that never answers", () => {
  it("times out with TIMEOUT, cancels the request by id, and does not block later loads", async () => {
    const calls: { route: string; body: unknown }[] = [];
    let starts = 0;
    // The first start ignores its signal on purpose: the caller must still get away.
    const transport: SceneTransport = (route, body) => {
      calls.push({ route, body });
      if (route === "start" && ++starts === 1) return new Promise(() => undefined);
      if (route === "start") return Promise.resolve({ status: 200, body: started("succeeded", { job_id: "j2", revision: REVISION }) });
      if (route === "result") return Promise.resolve({ status: 200, body: scene });
      return Promise.resolve({ status: 200, body: status("cancelled") });
    };
    const failure = (await loadScene("a.3mf", { signal: new AbortController().signal, transport, sleep: noSleep, startTimeoutMs: 20 }).catch((e) => e)) as SceneError;
    expect(failure).toBeInstanceOf(SceneError);
    expect(failure.code).toBe("TIMEOUT");
    expect(sceneErrorText(failure.code)).toContain("took too long");
    const firstStart = calls[0].body as { request_id: string };
    expect(calls.find((c) => c.route === "cancel")!.body).toEqual({ client_id: clientId, request_id: firstStart.request_id });
    const next = await loadScene("a.3mf", { signal: new AbortController().signal, transport, sleep: noSleep, startTimeoutMs: 20 });
    expect(next.schema).toBe("scene/1");
    expect(calls.filter((c) => c.route === "start")).toHaveLength(2); // the hung start and the new one: no re-send protocol
  });

  it("is released at once when the caller aborts, even if the transport never answers", async () => {
    const controller = new AbortController();
    const transport: SceneTransport = (route) => (route === "start" ? new Promise(() => undefined) : Promise.resolve({ status: 200, body: scene }));
    const pending = loadScene("a.3mf", { signal: controller.signal, transport, sleep: noSleep, startTimeoutMs: 60000 }).catch((e) => e);
    await Promise.resolve();
    controller.abort();
    expect(isAbort(await pending)).toBe(true);
  });

  it("gives up on a status answer that never comes and cancels the request", async () => {
    const calls: string[] = [];
    const transport: SceneTransport = (route) => {
      calls.push(route);
      if (route === "start") return Promise.resolve({ status: 200, body: started("running") });
      if (route === "status") return new Promise(() => undefined);
      return Promise.resolve({ status: 200, body: status("cancelled") });
    };
    const failure = (await loadScene("a.3mf", { signal: new AbortController().signal, transport, sleep: noSleep, requestTimeoutMs: 20 }).catch((e) => e)) as SceneError;
    expect(failure.code).toBe("TIMEOUT");
    expect(calls).toContain("cancel");
  });
});

// ---- The ordering contract with the engine -----------------------------------------------------------------------
// A stand-in engine that follows the contract agreed for PR #97: starts carry client_id and a strictly increasing seq; a
// start with a lower seq than the highest seen for that client is refused (STALE_START); a start for a (client, request)
// that was cancelled is refused (CANCELLED_BEFORE_START); a newer start replaces the running job; cancel takes {job_id} or
// {client_id, request_id} and the second form also tombstones the request. Delivery of any call can be held and released
// by hand, so every ordering below is deterministic: no timers, no sleeping.
type Job = { id: string; request: string; state: "running" | "succeeded" | "cancelled" };
type Reply = { status: number; body: unknown };
function makeEngine() {
  const highest = new Map<string, number>();
  const tombstones = new Set<string>();
  const jobs: Job[] = [];
  const byRequest = new Map<string, Job>();
  let running: Job | null = null;
  const log: { route: string; body: Record<string, unknown> }[] = [];
  const held: { match: (route: string, body: Record<string, unknown>) => boolean; release: () => void; gate: Promise<void> }[] = [];
  const hold = (match: (route: string, body: Record<string, unknown>) => boolean) => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => { release = r; });
    const h = { match, release, gate };
    held.push(h);
    return h;
  };
  const handle = (route: string, body: Record<string, unknown>): Reply => {
    if (route === "start") {
      const client = String(body.client_id), seq = Number(body.seq), request = String(body.request_id);
      if (tombstones.has(`${client}|${request}`)) return { status: 409, body: { error: "CANCELLED_BEFORE_START" } };
      const top = highest.get(client) ?? 0;
      if (seq < top) return { status: 409, body: { error: "STALE_START" } };
      const existing = byRequest.get(request);
      if (existing && seq === top) return { status: 200, body: started(existing.state, { job_id: existing.id, request_id: request }) };
      highest.set(client, seq);
      let replaced: string | null = null;
      if (running) { running.state = "cancelled"; replaced = running.id; }
      const job: Job = { id: `job-${jobs.length + 1}`, request, state: "running" };
      jobs.push(job);
      byRequest.set(request, job);
      running = job;
      return { status: 200, body: started("running", { job_id: job.id, request_id: request, replaced_job_id: replaced }) };
    }
    const jobOf = () => jobs.find((j) => j.id === body.job_id);
    if (route === "status") {
      const j = jobOf();
      if (!j) return { status: 404, body: { error: "EXPIRED" } };
      if (j.state === "running") j.state = "succeeded"; // the engine finishes on the first status call
      return { status: 200, body: status(j.state, { job_id: j.id, request_id: j.request, revision: j.state === "succeeded" ? REVISION : null }) };
    }
    if (route === "result") {
      const j = jobOf();
      if (!j) return { status: 404, body: { error: "EXPIRED" } };
      return j.state === "succeeded" ? { status: 200, body: { ...scene, revision: REVISION } } : { status: 409, body: { error: "CANCELLED" } };
    }
    // cancel
    if (typeof body.job_id === "string") {
      const j = jobOf();
      if (j && j.state === "running") j.state = "cancelled";
    } else {
      tombstones.add(`${body.client_id}|${body.request_id}`);
      const j = byRequest.get(String(body.request_id));
      if (j && j.state === "running") j.state = "cancelled";
    }
    return { status: 200, body: status("cancelled") };
  };
  const transport: SceneTransport = async (route, body) => {
    const b = body as Record<string, unknown>;
    log.push({ route, body: b });
    const h = held.find((x) => x.match(route, b));
    if (h) {
      held.splice(held.indexOf(h), 1);
      await h.gate;
    }
    return handle(route, b);
  };
  return { transport, log, hold, jobs, starts: () => log.filter((l) => l.route === "start").map((l) => l.body) };
}
const flushMicrotasks = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const opts = (signal: AbortSignal, transport: SceneTransport) => ({ signal, transport, sleep: noSleep });

describe("ordering of overlapping starts", () => {
  it("an abandoned start A delivered AFTER the wanted start B cannot cancel or replace B, and B loads", async () => {
    const engine = makeEngine();
    const aSignal = new AbortController();
    const holdA = engine.hold((route, body) => route === "start" && body.path === "a.3mf");
    const a = loadScene("a.3mf", opts(aSignal.signal, engine.transport)).catch((e) => e);
    await flushMicrotasks(); // A's start is issued and held on the way to the engine
    aSignal.abort(); // the user (or an unmount) abandons A
    expect(isAbort(await a)).toBe(true);
    const loaded = await loadScene("b.3mf", opts(new AbortController().signal, engine.transport)); // B reaches the engine first
    expect(loaded.schema).toBe("scene/1");
    holdA.release(); // A's late start finally arrives
    await flushMicrotasks();
    const starts = engine.starts();
    expect(starts.map((s) => s.path)).toEqual(["a.3mf", "b.3mf"]);
    expect(Number(starts[1].seq)).toBeGreaterThan(Number(starts[0].seq));
    expect(engine.jobs.map((j) => j.state)).toEqual(["succeeded"]); // only B's job exists; A registered nothing
    // A's cancel went out by client id and request id, and tombstoned it.
    const cancels = engine.log.filter((l) => l.route === "cancel");
    expect(cancels).toHaveLength(1);
    expect(Object.keys(cancels[0].body).sort()).toEqual(["client_id", "request_id"]);
    expect(cancels[0].body.request_id).toBe(starts[0].request_id);
  });

  it("the same delivery order under a StrictMode style start, cancel, start for the same path", async () => {
    const engine = makeEngine();
    const first = new AbortController();
    const holdFirst = engine.hold((route) => route === "start");
    const a = loadScene("same.3mf", opts(first.signal, engine.transport)).catch((e) => e);
    await flushMicrotasks();
    first.abort();
    await a;
    const loaded = await loadScene("same.3mf", opts(new AbortController().signal, engine.transport));
    holdFirst.release();
    await flushMicrotasks();
    expect(loaded.schema).toBe("scene/1");
    const starts = engine.starts();
    expect(starts).toHaveLength(2);
    expect(starts[0].request_id).not.toBe(starts[1].request_id);
    expect(engine.jobs.filter((j) => j.state === "cancelled")).toHaveLength(0);
  });

  it("an abandoned A delivered before B is replaced by B, and B still loads", async () => {
    const engine = makeEngine();
    const aSignal = new AbortController();
    const a = loadScene("a.3mf", opts(aSignal.signal, engine.transport)).catch((e) => e);
    await flushMicrotasks(); // A's start reached the engine and A's job runs
    aSignal.abort();
    await a;
    const loaded = await loadScene("b.3mf", opts(new AbortController().signal, engine.transport));
    expect(loaded.schema).toBe("scene/1");
    expect(engine.jobs.map((j) => j.state)).toEqual(["cancelled", "succeeded"]);
  });

  it("gives every start attempt a higher seq, retries included, and one client id", async () => {
    const engine = makeEngine();
    for (let i = 0; i < 3; i++) await loadScene(`p${i}.3mf`, opts(new AbortController().signal, engine.transport));
    const refusing: SceneTransport = async (route) => (route === "start" ? { status: 422, body: { error: "UNSUPPORTED_FORMAT" } } : { status: 200, body: status("cancelled") });
    const failure = await loadScene("x.obj", opts(new AbortController().signal, refusing)).catch((e) => e);
    expect((failure as SceneError).code).toBe("UNSUPPORTED_FORMAT");
    const more = makeEngine();
    await loadScene("again.3mf", opts(new AbortController().signal, more.transport)); // the user presses Try again
    const all = [...engine.starts(), ...more.starts()];
    const seqs = all.map((s) => Number(s.seq));
    expect(seqs.every((n, i) => i === 0 || n > seqs[i - 1])).toBe(true);
    expect(seqs[seqs.length - 1] - seqs[0]).toBeGreaterThanOrEqual(seqs.length); // the refused start used a seq in between
    expect(new Set(all.map((s) => s.client_id))).toEqual(new Set([clientId]));
    expect(clientId).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
  });
});

describe("a wanted request that is replaced or refused", () => {
  it("restarts ONCE with a fresh request id and the next seq, then loads", async () => {
    const bodies: Record<string, unknown>[] = [];
    let starts = 0;
    const transport: SceneTransport = async (route, body) => {
      if (route === "start") {
        bodies.push(body as Record<string, unknown>);
        return { status: 200, body: ++starts === 1 ? started("cancelled") : started("succeeded", { revision: REVISION }) };
      }
      if (route === "result") return { status: 200, body: scene };
      return { status: 200, body: status("cancelled") };
    };
    const out = await loadScene("b.3mf", opts(new AbortController().signal, transport));
    expect(out.schema).toBe("scene/1");
    expect(bodies).toHaveLength(2);
    expect(bodies[1].request_id).not.toBe(bodies[0].request_id);
    expect(Number(bodies[1].seq)).toBe(Number(bodies[0].seq) + 1);
  });

  it.each([["CANCELLED_BEFORE_START"], ["STALE_START"]])("also restarts once when a start is refused as %s", async (code) => {
    let starts = 0;
    const transport: SceneTransport = async (route) => {
      if (route === "start") return ++starts === 1 ? { status: 409, body: { error: code } } : { status: 200, body: started("succeeded", { revision: REVISION }) };
      if (route === "result") return { status: 200, body: scene };
      return { status: 200, body: status("cancelled") };
    };
    expect((await loadScene("b.3mf", opts(new AbortController().signal, transport))).schema).toBe("scene/1");
    expect(starts).toBe(2);
  });

  it("repeated replacement stops after the second attempt and reports it: no loop", async () => {
    let starts = 0;
    const transport: SceneTransport = async (route) => {
      if (route === "start") { ++starts; return { status: 200, body: started("cancelled") }; }
      return { status: 200, body: status("cancelled") };
    };
    const failure = (await loadScene("b.3mf", opts(new AbortController().signal, transport)).catch((e) => e)) as SceneError;
    expect(failure.code).toBe("CANCELLED");
    expect(starts).toBe(2);
    let refused = 0;
    const stale: SceneTransport = async (route) => {
      if (route === "start") { ++refused; return { status: 409, body: { error: "STALE_START" } }; }
      return { status: 200, body: status("cancelled") };
    };
    expect(((await loadScene("b.3mf", opts(new AbortController().signal, stale)).catch((e) => e)) as SceneError).code).toBe("STALE_START");
    expect(refused).toBe(2);
  });

  it("does not restart when the caller left", async () => {
    const controller = new AbortController();
    let starts = 0;
    const transport: SceneTransport = async (route) => {
      if (route === "start") { ++starts; controller.abort(); return { status: 200, body: started("cancelled") }; }
      return { status: 200, body: status("cancelled") };
    };
    expect(isAbort(await loadScene("b.3mf", opts(controller.signal, transport)).catch((e) => e))).toBe(true);
    expect(starts).toBe(1);
  });

  it("gives the two new refusals plain wording", () => {
    expect(sceneErrorText("STALE_START")).toBe("A newer request for the 3D view replaced this one.");
    expect(sceneErrorText("CANCELLED_BEFORE_START")).toBe("This 3D view request was cancelled before it started.");
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
