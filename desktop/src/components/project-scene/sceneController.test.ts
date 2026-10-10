// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { SceneController, type ControllerDeps } from "./sceneController";
import { makeFakeFactory } from "./fakeViewport";
import { offBedScene, scene } from "./sceneFixtures";
import { SceneError, loadScene, resetSceneSession, type LoadSceneOptions, type SceneTransport, type SceneV1 } from "@/lib/scene";

// The scene client keeps one session per app run; every test starts as at app start.
beforeEach(() => resetSceneSession());

function abortError() { const e = new Error("aborted"); e.name = "AbortError"; return e; }

/** A loader the test settles by hand. Aborting rejects with an AbortError, like the real one. */
function manualLoader() {
  const pending: { path: string; opts: LoadSceneOptions; resolve: (s: SceneV1) => void; reject: (e: unknown) => void }[] = [];
  const load: ControllerDeps["load"] = (path, opts) => new Promise<SceneV1>((resolve, reject) => {
    pending.push({ path, opts, resolve, reject });
    opts.signal.addEventListener("abort", () => reject(abortError()), { once: true });
  });
  return { load, pending };
}
/** A loader that IGNORES abort, like a transport that cannot recall a request: every answer is delivered when the test says, however late. */
function manualLoaderIgnoringAbort() {
  const pending: { path: string; opts: LoadSceneOptions; resolve: (s: SceneV1) => void; reject: (e: unknown) => void }[] = [];
  const load: ControllerDeps["load"] = (path, opts) => new Promise<SceneV1>((resolve, reject) => { pending.push({ path, opts, resolve, reject }); });
  return { load, pending };
}
const flush = () => new Promise((r) => setTimeout(r, 0));
const host = () => { const el = document.createElement("div"); document.body.appendChild(el); return el; };

describe("SceneController", () => {
  it("loads, shows the objects and builds one fresh canvas", async () => {
    const { load, pending } = manualLoader();
    const { factory, stats } = makeFakeFactory();
    const c = new SceneController({ load, viewportFactory: factory, theme: "dark" });
    const el = host();
    c.setHost(el);
    c.setPath("a.3mf");
    expect(c.getState().phase).toBe("loading");
    pending[0].resolve(offBedScene());
    await flush();
    expect(c.getState().phase).toBe("shown");
    expect(c.getState().graphics).toBe("working");
    expect(c.getState().model?.objects).toHaveLength(2);
    expect(el.querySelectorAll("canvas")).toHaveLength(1);
    expect(stats.created).toBe(1);
    c.dispose();
    expect(el.querySelectorAll("canvas")).toHaveLength(0);
  });

  it("drops late successful answers from a loader that ignores abort: A, then B, then A again shows only the last A", async () => {
    const { load, pending } = manualLoaderIgnoringAbort();
    const { factory, stats } = makeFakeFactory();
    const c = new SceneController({ load, viewportFactory: factory, theme: "dark" });
    c.setHost(host());
    c.setPath("a.3mf");
    c.setPath("b.3mf");
    c.setPath("a.3mf");
    expect(pending.map((p) => p.path)).toEqual(["a.3mf", "b.3mf", "a.3mf"]);
    expect(pending[0].opts.signal.aborted).toBe(true);
    expect(pending[1].opts.signal.aborted).toBe(true);
    // The first two were aborted, but their (successful) answers still arrive, late and out of order.
    pending[1].resolve(scene({ revision: "2".repeat(64) }));
    pending[0].resolve(scene({ revision: "1".repeat(64) }));
    await flush();
    expect(c.getState().phase).toBe("loading");
    expect(c.getState().revision).toBeNull();
    expect(stats.created).toBe(0); // neither stale answer built a viewer
    pending[2].resolve(scene({ revision: "3".repeat(64) }));
    await flush();
    expect(c.getState().revision).toBe("3".repeat(64));
    expect(stats.created).toBe(1);
    // A stale failure arriving after the view is shown changes nothing either.
    pending[0].reject(new SceneError("LIMIT_EXCEEDED"));
    await flush();
    expect(c.getState()).toMatchObject({ phase: "shown", error: null });
    c.dispose();
  });

  it("ignores a result that arrives after dispose and creates no canvas", async () => {
    const { load, pending } = manualLoader();
    const { factory, stats } = makeFakeFactory();
    const c = new SceneController({ load, viewportFactory: factory, theme: "dark" });
    const el = host();
    c.setHost(el);
    c.setPath("a.3mf");
    c.dispose();
    expect(pending[0].opts.signal.aborted).toBe(true);
    pending[0].resolve(scene());
    await flush();
    expect(stats.created).toBe(0);
    expect(el.querySelectorAll("canvas")).toHaveLength(0);
  });

  it("reports engine failures as codes the panel turns into plain words, and retry starts a new load", async () => {
    const { load, pending } = manualLoader();
    const c = new SceneController({ load, viewportFactory: makeFakeFactory().factory, theme: "dark" });
    c.setHost(host());
    c.setPath("a.3mf");
    pending[0].reject(new SceneError("LIMIT_EXCEEDED"));
    await flush();
    expect(c.getState()).toMatchObject({ phase: "failed", error: "LIMIT_EXCEEDED" });
    c.retryLoad();
    expect(c.getState().phase).toBe("loading");
    expect(pending).toHaveLength(2);
    c.dispose();
  });

  it("shows no graphics but keeps the lists when WebGL cannot start, and Retry builds a new canvas", async () => {
    const { load, pending } = manualLoader();
    let fail = true;
    const { factory, stats } = makeFakeFactory({ failCreate: () => fail });
    const c = new SceneController({ load, viewportFactory: factory, theme: "dark" });
    const el = host();
    c.setHost(el);
    c.setPath("a.3mf");
    pending[0].resolve(offBedScene());
    await flush();
    expect(c.getState().graphics).toBe("unavailable");
    expect(c.getState().model?.objects).toHaveLength(2);
    expect(el.querySelectorAll("canvas")).toHaveLength(0);
    fail = false;
    c.startGraphics();
    expect(c.getState().graphics).toBe("working");
    expect(stats.created).toBe(1);
    c.dispose();
  });

  it("moves to a lost state on a fatal graphics error, removes the canvas, and Retry uses a different canvas", async () => {
    const { load, pending } = manualLoader();
    const { factory, stats, emit } = makeFakeFactory();
    const c = new SceneController({ load, viewportFactory: factory, theme: "dark" });
    const el = host();
    c.setHost(el);
    c.setPath("a.3mf");
    pending[0].resolve(scene());
    await flush();
    const first = el.querySelector("canvas");
    emit("error", { message: "lost" });
    expect(c.getState().graphics).toBe("lost");
    expect(el.querySelectorAll("canvas")).toHaveLength(0);
    expect(stats.liveContexts).toBe(0);
    c.startGraphics();
    const second = el.querySelector("canvas");
    expect(second).not.toBe(first);
    expect(stats.liveContexts).toBe(1);
    c.dispose();
  });

  it("selects the whole object from a pick and from the list", async () => {
    const { load, pending } = manualLoader();
    const { factory, stats, emit } = makeFakeFactory();
    const c = new SceneController({ load, viewportFactory: factory, theme: "dark" });
    c.setHost(host());
    c.setPath("a.3mf");
    pending[0].resolve(scene());
    await flush();
    emit("pick", { objectId: "b1" });
    expect(c.getState().selectedId).toBe("b1");
    expect(stats.calls).toContain("setSelection:b1");
    c.selectFromList(null);
    expect(c.getState().selectedId).toBeNull();
    c.setCamera("front");
    c.setSlope(true);
    expect(stats.calls).toEqual(expect.arrayContaining(["view:front", "setRenderMode:overhang"]));
    c.dispose();
  });

  it("50 mount/dispose cycles leave no canvas, no listener and at most one live context", async () => {
    const { factory, stats } = makeFakeFactory();
    const el = host();
    for (let i = 0; i < 50; i++) {
      const c = new SceneController({
        load: async () => scene(), viewportFactory: factory, theme: i % 2 ? "light" : "dark",
      });
      c.setHost(el);
      c.setPath(`p${i}.3mf`);
      await flush();
      expect(stats.liveContexts).toBeLessThanOrEqual(1);
      c.dispose();
    }
    expect(stats.created).toBe(50);
    expect(stats.disposed).toBe(50);
    expect(stats.liveContexts).toBe(0);
    expect(stats.liveListeners).toBe(0);
    expect(stats.peakContexts).toBe(1);
    expect(el.querySelectorAll("canvas")).toHaveLength(0);
    expect(document.querySelectorAll("canvas")).toHaveLength(0);
  });

  it("survives a StrictMode style start, dispose, start on the same host", async () => {
    const { factory, stats } = makeFakeFactory();
    const el = host();
    const aborted: boolean[] = [];
    const load: ControllerDeps["load"] = (_p, opts) => new Promise((resolve, reject) => {
      opts.signal.addEventListener("abort", () => { aborted.push(true); reject(abortError()); }, { once: true });
      setTimeout(() => resolve(scene()), 5);
    });
    const first = new SceneController({ load, viewportFactory: factory, theme: "dark" });
    first.setHost(el);
    first.setPath("a.3mf");
    first.dispose();
    const second = new SceneController({ load, viewportFactory: factory, theme: "dark" });
    second.setHost(el);
    second.setPath("a.3mf");
    await new Promise((r) => setTimeout(r, 20));
    expect(aborted).toEqual([true]);
    expect(second.getState().phase).toBe("shown");
    expect(el.querySelectorAll("canvas")).toHaveLength(1);
    expect(stats.liveContexts).toBe(1);
    second.dispose();
    expect(stats.liveContexts).toBe(0);
  });

  it("disposes the viewer while its canvas is attached even when the host was removed first", async () => {
    const { load, pending } = manualLoader();
    const { factory, stats } = makeFakeFactory();
    const c = new SceneController({ load, viewportFactory: factory, theme: "dark" });
    const el = host();
    c.setHost(el);
    c.setPath("a.3mf");
    pending[0].resolve(scene());
    await flush();
    el.remove(); // what React does to a route's DOM before its passive cleanups run
    c.dispose();
    expect(stats.disposed).toBe(1);
    expect(stats.disposedDetached).toBe(0);
    expect(document.querySelectorAll("canvas")).toHaveLength(0);
  });

  it("shows a failure with Retry when the engine never answers the start, and Retry works afterwards", async () => {
    let answer = false;
    const job = (state: string, revision: string | null) => ({ job_id: "j", request_id: "r", state, stage: null, completed: null, total: null, error: null, revision });
    const transport: SceneTransport = (route) => {
      if (route === "session") return Promise.resolve({ status: 200, body: { client_id: "session-ctl", ttl_s: 900 } });
      if (route === "start") {
        // Until `answer` is set it never answers, and ignores its signal.
        return answer ? Promise.resolve({ status: 200, body: job("succeeded", "a".repeat(64)) }) : new Promise(() => undefined);
      }
      if (route === "result") return Promise.resolve({ status: 200, body: scene() });
      return Promise.resolve({ status: 200, body: job("cancelled", null) });
    };
    const { factory } = makeFakeFactory();
    const c = new SceneController({
      load: (path, opts) => loadScene(path, { ...opts, transport, startTimeoutMs: 30, sleep: () => Promise.resolve() }),
      viewportFactory: factory, theme: "dark",
    });
    c.setHost(host());
    c.setPath("a.3mf");
    expect(c.getState().phase).toBe("loading");
    await new Promise((r) => setTimeout(r, 120));
    expect(c.getState()).toMatchObject({ phase: "failed", error: "TIMEOUT" });
    answer = true;
    c.retryLoad();
    await new Promise((r) => setTimeout(r, 60));
    expect(c.getState().phase).toBe("shown");
    c.dispose();
  }, 10000);

  it("reports a scene whose geometry cannot be decoded as a load problem, not as missing graphics", async () => {
    const { load, pending } = manualLoader();
    const { factory, stats } = makeFakeFactory();
    const c = new SceneController({ load, viewportFactory: factory, theme: "dark" });
    c.setHost(host());
    c.setPath("a.3mf");
    const bad = scene();
    bad.meshes[0].positions_f32le_base64 = "AAAA"; // wrong size for the counts
    pending[0].resolve(bad);
    await flush();
    expect(c.getState()).toMatchObject({ phase: "failed", error: "BAD_RESPONSE" });
    expect(stats.created).toBe(0);
    expect(document.querySelectorAll("canvas")).toHaveLength(0);
    c.dispose();
  });

  it("clears the list selection when the viewer clears its own (Escape), and ignores echoes of its own selections", async () => {
    const { load, pending } = manualLoader();
    const { factory, emit } = makeFakeFactory();
    const c = new SceneController({ load, viewportFactory: factory, theme: "dark" });
    c.setHost(host());
    c.setPath("a.3mf");
    pending[0].resolve(scene());
    await flush();
    c.selectFromList("b1");
    emit("select", { ids: ["b1"] });
    expect(c.getState().selectedId).toBe("b1");
    emit("select", { ids: [] });
    expect(c.getState().selectedId).toBeNull();
    c.dispose();
  });

  it("never throws out of dispose even if the viewport's dispose throws", async () => {
    const { load, pending } = manualLoader();
    const { factory } = makeFakeFactory();
    const wrapped: ControllerDeps["viewportFactory"] = (canvas, o) => {
      const vp = factory(canvas, o);
      const original = vp.dispose;
      vp.dispose = () => { original(); throw new Error("boom"); };
      return vp;
    };
    const c = new SceneController({ load, viewportFactory: wrapped, theme: "dark" });
    const el = host();
    c.setHost(el);
    c.setPath("a.3mf");
    pending[0].resolve(scene());
    await flush();
    expect(() => c.dispose()).not.toThrow();
    expect(el.querySelectorAll("canvas")).toHaveLength(0);
  });
});
