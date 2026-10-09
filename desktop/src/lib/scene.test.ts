import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  SceneError, currentSceneClientId, decodeMesh, isAbort, loadScene, newRequestId, sceneErrorText,
  resetSceneSession, type SceneMesh, type SceneTransport,
} from "./scene";

vi.mock("@/api", () => ({ engineConnection: vi.fn() }));

// Every test starts with no session, as at app start.
beforeEach(() => resetSceneSession());

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
    if (!q?.length) return route === "session" ? { status: 200, body: { client_id: "session-scripted", ttl_s: 900 } } : { status: 200, body: status("cancelled") };
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
    const startBody = calls.find((c) => c.route === "start")!.body as { request_id: string; client_id: string; seq: number };
    const cancels = calls.filter((c) => c.route === "cancel");
    expect(cancels).toEqual([{ route: "cancel", body: { client_id: currentSceneClientId(), request_id: startBody.request_id, seq: startBody.seq } }]);
    expect(Object.keys(cancels[0].body as object).sort()).toEqual(["client_id", "request_id", "seq"]); // no job_id
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
    expect(calls.map((c) => c.route)).toEqual(["session", "start", "cancel"]);
    expect((calls[2].body as { request_id: string }).request_id).toBe((calls[1].body as { request_id: string }).request_id);
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
      if (route === "session") return Promise.resolve({ status: 200, body: { client_id: "session-t", ttl_s: 900 } });
      if (route === "start" && ++starts === 1) return new Promise(() => undefined);
      if (route === "start") return Promise.resolve({ status: 200, body: started("succeeded", { job_id: "j2", revision: REVISION }) });
      if (route === "result") return Promise.resolve({ status: 200, body: scene });
      return Promise.resolve({ status: 200, body: status("cancelled") });
    };
    const failure = (await loadScene("a.3mf", { signal: new AbortController().signal, transport, sleep: noSleep, startTimeoutMs: 20 }).catch((e) => e)) as SceneError;
    expect(failure).toBeInstanceOf(SceneError);
    expect(failure.code).toBe("TIMEOUT");
    expect(sceneErrorText(failure.code)).toContain("took too long");
    const firstStart = calls.find((c) => c.route === "start")!.body as { request_id: string; seq: number };
    expect(calls.find((c) => c.route === "cancel")!.body).toEqual({ client_id: "session-t", request_id: firstStart.request_id, seq: firstStart.seq });
    const next = await loadScene("a.3mf", { signal: new AbortController().signal, transport, sleep: noSleep, startTimeoutMs: 20 });
    expect(next.schema).toBe("scene/1");
    expect(calls.filter((c) => c.route === "start")).toHaveLength(2); // the hung start and the new one: no re-send protocol
  });

  it("is released at once when the caller aborts, even if the transport never answers", async () => {
    const controller = new AbortController();
    const transport: SceneTransport = (route) => (route === "start" ? new Promise(() => undefined) : route === "session" ? Promise.resolve({ status: 200, body: { client_id: "session-t", ttl_s: 900 } }) : Promise.resolve({ status: 200, body: scene }));
    const pending = loadScene("a.3mf", { signal: controller.signal, transport, sleep: noSleep, startTimeoutMs: 60000 }).catch((e) => e);
    await Promise.resolve();
    controller.abort();
    expect(isAbort(await pending)).toBe(true);
  });

  it("gives up on a status answer that never comes and cancels the request", async () => {
    const calls: string[] = [];
    const transport: SceneTransport = (route) => {
      calls.push(route);
      if (route === "session") return Promise.resolve({ status: 200, body: { client_id: "session-t", ttl_s: 900 } });
      if (route === "start") return Promise.resolve({ status: 200, body: started("running") });
      if (route === "status") return new Promise(() => undefined);
      return Promise.resolve({ status: 200, body: status("cancelled") });
    };
    const failure = (await loadScene("a.3mf", { signal: new AbortController().signal, transport, sleep: noSleep, requestTimeoutMs: 20 }).catch((e) => e)) as SceneError;
    expect(failure.code).toBe("TIMEOUT");
    expect(calls).toContain("cancel");
  });
});

// ---- The session contract with the engine ------------------------------------------------------------------------------
// A stand-in engine that follows the session contract agreed for the engine update (PR #97): POST /scene/session opens a
// session; starts carry client_id and a strictly increasing seq; a start whose seq is not higher than the highest seen is
// refused (STALE_START), which includes an exact retry; a start for a cancelled request or seq is refused
// (CANCELLED_BEFORE_START); an unknown or expired session gives 409 SESSION_EXPIRED; more sessions than allowed gives 503
// SESSION_LIMIT; a newer start replaces the running job; cancel takes {client_id, request_id, seq} and keeps that seq dead.
// Delivery of any call can be held and released by hand, so every ordering below is deterministic: no timers, no sleeping.
type Job = { id: string; request: string; session: string; state: "running" | "succeeded" | "cancelled" };
type Reply = { status: number; body: unknown };
function makeEngine(options: { maxSessions?: number } = {}) {
  const sessions = new Map<string, { highest: number; deadSeqs: Set<number>; deadRequests: Set<string> }>();
  const jobs: Job[] = [];
  const byRequest = new Map<string, Job>();
  let running: Job | null = null;
  let opened = 0;
  const log: { route: string; body: Record<string, unknown> }[] = [];
  const held: { match: (route: string, body: Record<string, unknown>) => boolean; release: () => void; gate: Promise<void> }[] = [];
  const hold = (match: (route: string, body: Record<string, unknown>) => boolean) => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => { release = r; });
    const h = { match, release, gate };
    held.push(h);
    return h;
  };
  const expire = (clientId: string) => { sessions.delete(clientId); };
  const handle = (route: string, body: Record<string, unknown>): Reply => {
    if (route === "session") {
      if (options.maxSessions !== undefined && sessions.size >= options.maxSessions) return { status: 503, body: { error: "SESSION_LIMIT" } };
      const id = `session-${++opened}`;
      sessions.set(id, { highest: 0, deadSeqs: new Set(), deadRequests: new Set() });
      return { status: 200, body: { client_id: id, ttl_s: 900 } };
    }
    if (route === "start") {
      const s = sessions.get(String(body.client_id));
      if (!s) return { status: 409, body: { error: "SESSION_EXPIRED" } };
      const seq = Number(body.seq), request = String(body.request_id);
      if (s.deadSeqs.has(seq) || s.deadRequests.has(request)) return { status: 409, body: { error: "CANCELLED_BEFORE_START" } };
      if (seq <= s.highest) return { status: 409, body: { error: "STALE_START" } };
      s.highest = seq;
      let replaced: string | null = null;
      if (running) { running.state = "cancelled"; replaced = running.id; }
      const job: Job = { id: `job-${jobs.length + 1}`, request, session: String(body.client_id), state: "running" };
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
    const s = sessions.get(String(body.client_id));
    if (!s) return { status: 409, body: { error: "SESSION_EXPIRED" } };
    s.deadSeqs.add(Number(body.seq));
    s.deadRequests.add(String(body.request_id));
    const j = byRequest.get(String(body.request_id));
    if (j && j.state === "running") j.state = "cancelled";
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
  return {
    transport, log, hold, jobs, expire,
    starts: () => log.filter((l) => l.route === "start").map((l) => l.body),
    sessionOpens: () => log.filter((l) => l.route === "session").length,
  };
}
const flushMicrotasks = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const opts = (signal: AbortSignal, transport: SceneTransport) => ({ signal, transport, sleep: noSleep });

describe("sessions", () => {
  it("opens ONE session lazily, shared by concurrent loads, and every start carries it with a seq that starts at 1", async () => {
    const engine = makeEngine();
    expect(currentSceneClientId()).toBeNull();
    const holdOpen = engine.hold((route) => route === "session");
    const aSignal = new AbortController();
    const a = loadScene("a.3mf", opts(aSignal.signal, engine.transport)).catch((e) => e);
    const b = loadScene("b.3mf", opts(new AbortController().signal, engine.transport));
    await flushMicrotasks();
    expect(engine.sessionOpens()).toBe(1); // both loads wait on the same open
    holdOpen.release();
    aSignal.abort(); // A is abandoned before it learns the session, so it never sends a start
    expect(isAbort(await a)).toBe(true);
    await b;
    await loadScene("c.3mf", opts(new AbortController().signal, engine.transport));
    expect(engine.sessionOpens()).toBe(1);
    const starts = engine.starts();
    expect(new Set(starts.map((s) => s.client_id))).toEqual(new Set(["session-1"]));
    expect(currentSceneClientId()).toBe("session-1");
    expect(starts.map((s) => s.path)).toEqual(["b.3mf", "c.3mf"]);
    expect(starts.map((s) => Number(s.seq))).toEqual([1, 2]);
    expect(new Set(starts.map((s) => s.request_id)).size).toBe(2);
  });

  it("a load aborted before the session is known sends nothing, and the next load uses the same session", async () => {
    const engine = makeEngine();
    const holdOpen = engine.hold((route) => route === "session");
    const first = new AbortController();
    const a = loadScene("same.3mf", opts(first.signal, engine.transport)).catch((e) => e); // StrictMode's first mount
    await flushMicrotasks();
    first.abort();
    expect(isAbort(await a)).toBe(true);
    const b = loadScene("same.3mf", opts(new AbortController().signal, engine.transport)); // the second mount
    await flushMicrotasks();
    holdOpen.release();
    expect((await b).schema).toBe("scene/1");
    expect(engine.sessionOpens()).toBe(1);
    expect(engine.starts()).toHaveLength(1); // the abandoned mount never reached the engine
    expect(engine.log.filter((l) => l.route === "cancel")).toHaveLength(0);
  });

  it("an abandoned start A delivered AFTER the wanted start B cannot cancel or replace B, and B loads", async () => {
    const engine = makeEngine();
    const aSignal = new AbortController();
    await loadScene("warm.3mf", opts(new AbortController().signal, engine.transport)); // opens the session
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
    expect(starts.map((s) => s.path)).toEqual(["warm.3mf", "a.3mf", "b.3mf"]);
    expect(starts.map((s) => Number(s.seq))).toEqual([1, 2, 3]);
    expect(engine.jobs.map((j) => j.state)).toEqual(["cancelled", "succeeded"]); // warm (replaced by B) and B; A registered nothing
    const cancels = engine.log.filter((l) => l.route === "cancel");
    expect(cancels).toHaveLength(1);
    expect(Object.keys(cancels[0].body).sort()).toEqual(["client_id", "request_id", "seq"]);
    expect(cancels[0].body).toEqual({ client_id: "session-1", request_id: starts[1].request_id, seq: starts[1].seq });
  });

  it("cancel before start: the cancel reaches the engine first, and the late start is refused and registers nothing", async () => {
    const engine = makeEngine();
    await loadScene("warm.3mf", opts(new AbortController().signal, engine.transport));
    const jobsBefore = engine.jobs.length;
    const holdStart = engine.hold((route, body) => route === "start" && body.path === "a.3mf");
    const aSignal = new AbortController();
    const a = loadScene("a.3mf", opts(aSignal.signal, engine.transport)).catch((e) => e);
    await flushMicrotasks();
    aSignal.abort();
    await a;
    await flushMicrotasks(); // the cancel was delivered while the start is still on its way
    expect(engine.log.filter((l) => l.route === "cancel")).toHaveLength(1);
    holdStart.release();
    await flushMicrotasks();
    expect(engine.jobs).toHaveLength(jobsBefore); // the late start created no job
    expect(engine.jobs.every((j) => j.state !== "running" || j.request !== engine.starts()[1].request_id)).toBe(true);
  });

  it("gives every start attempt a higher seq, retries included", async () => {
    const engine = makeEngine();
    for (let i = 0; i < 3; i++) await loadScene(`p${i}.3mf`, opts(new AbortController().signal, engine.transport));
    const refusing: SceneTransport = async (route, body) => (route === "start" ? { status: 422, body: { error: "UNSUPPORTED_FORMAT" } } : engine.transport(route, body));
    const failure = await loadScene("x.obj", opts(new AbortController().signal, refusing)).catch((e) => e);
    expect((failure as SceneError).code).toBe("UNSUPPORTED_FORMAT");
    await loadScene("again.3mf", opts(new AbortController().signal, engine.transport)); // the user presses Try again
    const seqs = engine.starts().map((s) => Number(s.seq));
    expect(seqs).toEqual([1, 2, 3, 5]); // the refused start used seq 4
    expect(new Set(engine.starts().map((s) => s.request_id)).size).toBe(4);
  });

  it("an expired session opens a NEW session, restarts ONCE with seq back at 1 and a fresh request id, and loads", async () => {
    const engine = makeEngine();
    await loadScene("a.3mf", opts(new AbortController().signal, engine.transport));
    engine.expire("session-1"); // the engine restarted, or the session sat idle too long
    const loaded = await loadScene("b.3mf", opts(new AbortController().signal, engine.transport));
    expect(loaded.schema).toBe("scene/1");
    expect(engine.sessionOpens()).toBe(2);
    const starts = engine.starts();
    expect(starts.map((s) => [s.client_id, Number(s.seq)])).toEqual([["session-1", 1], ["session-1", 2], ["session-2", 1]]);
    expect(starts[2].request_id).not.toBe(starts[1].request_id);
    expect(currentSceneClientId()).toBe("session-2");
  });

  it("repeated expiry stops after one restart and is reported: no loop", async () => {
    const engine = makeEngine();
    const alwaysExpired: SceneTransport = async (route, body) => {
      const reply = await engine.transport(route, body);
      if (route === "session") engine.expire(String((reply.body as { client_id: string }).client_id));
      return reply;
    };
    const failure = (await loadScene("a.3mf", opts(new AbortController().signal, alwaysExpired)).catch((e) => e)) as SceneError;
    expect(failure.code).toBe("SESSION_EXPIRED");
    expect(sceneErrorText(failure.code)).toContain("Try again");
    expect(engine.sessionOpens()).toBe(2);
    expect(engine.starts()).toHaveLength(2);
  });

  it("an abandoned start delivered after its session expired never revives: it opens nothing and its answer is dropped", async () => {
    const engine = makeEngine();
    await loadScene("warm.3mf", opts(new AbortController().signal, engine.transport));
    const holdA = engine.hold((route, body) => route === "start" && body.path === "a.3mf");
    const aSignal = new AbortController();
    const a = loadScene("a.3mf", opts(aSignal.signal, engine.transport)).catch((e) => e);
    await flushMicrotasks();
    aSignal.abort();
    expect(isAbort(await a)).toBe(true);
    engine.expire("session-1");
    const loaded = await loadScene("b.3mf", opts(new AbortController().signal, engine.transport)); // opens session-2 and loads
    expect(loaded.schema).toBe("scene/1");
    const opensBefore = engine.sessionOpens();
    holdA.release(); // A's late start meets an unknown session
    await flushMicrotasks();
    expect(engine.sessionOpens()).toBe(opensBefore); // A did not trigger a new session or a restart
    expect(engine.starts().filter((s) => s.path === "a.3mf")).toHaveLength(1);
    expect(engine.jobs.filter((j) => j.session === "session-2").map((j) => j.state)).toEqual(["succeeded"]);
  });

  it("an engine at its session limit gives SESSION_LIMIT in plain words, and a later load works once there is room", async () => {
    const engine = makeEngine({ maxSessions: 0 });
    const failure = (await loadScene("a.3mf", opts(new AbortController().signal, engine.transport)).catch((e) => e)) as SceneError;
    expect(failure.code).toBe("SESSION_LIMIT");
    expect(sceneErrorText("SESSION_LIMIT")).toContain("as many 3D views as it allows");
    expect(engine.starts()).toHaveLength(0);
    expect(engine.sessionOpens()).toBe(1); // no loop
    const roomy = makeEngine();
    expect((await loadScene("a.3mf", opts(new AbortController().signal, roomy.transport))).schema).toBe("scene/1");
  });

  it("cancel on an expired session is ignored: the load still ends with an AbortError", async () => {
    const engine = makeEngine();
    const controller = new AbortController();
    const slowSleep = async () => { engine.expire("session-1"); controller.abort(); };
    const failure = await loadScene("a.3mf", { signal: controller.signal, transport: engine.transport, sleep: slowSleep }).catch((e) => e);
    expect(isAbort(failure)).toBe(true);
    await flushMicrotasks();
    expect(engine.log.filter((l) => l.route === "cancel")).toHaveLength(1); // sent, answered SESSION_EXPIRED, nothing thrown
  });
});

describe("a wanted request that is replaced or refused", () => {
  it("restarts ONCE with a fresh request id and the next seq, then loads", async () => {
    const bodies: Record<string, unknown>[] = [];
    let starts = 0;
    const transport: SceneTransport = async (route, body) => {
      if (route === "session") return { status: 200, body: { client_id: "session-x", ttl_s: 900 } };
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
      if (route === "session") return { status: 200, body: { client_id: "session-x", ttl_s: 900 } };
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
      if (route === "session") return { status: 200, body: { client_id: "session-x", ttl_s: 900 } };
      if (route === "start") { ++starts; return { status: 200, body: started("cancelled") }; }
      return { status: 200, body: status("cancelled") };
    };
    const failure = (await loadScene("b.3mf", opts(new AbortController().signal, transport)).catch((e) => e)) as SceneError;
    expect(failure.code).toBe("CANCELLED");
    expect(starts).toBe(2);
    let refused = 0;
    const stale: SceneTransport = async (route) => {
      if (route === "session") return { status: 200, body: { client_id: "session-x", ttl_s: 900 } };
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
      if (route === "session") return { status: 200, body: { client_id: "session-x", ttl_s: 900 } };
      if (route === "start") { ++starts; controller.abort(); return { status: 200, body: started("cancelled") }; }
      return { status: 200, body: status("cancelled") };
    };
    expect(isAbort(await loadScene("b.3mf", opts(controller.signal, transport)).catch((e) => e))).toBe(true);
    expect(starts).toBe(1);
  });

  it("gives the new refusals plain wording", () => {
    expect(sceneErrorText("STALE_START")).toBe("A newer request for the 3D view replaced this one.");
    expect(sceneErrorText("CANCELLED_BEFORE_START")).toBe("This 3D view request was cancelled before it started.");
    expect(sceneErrorText("SESSION_EXPIRED")).toContain("Try again");
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
