// A stand-in for the vendored viewport, used by tests. `makeFakePort` is the inspection port the real adapter builds;
// `makeFakeFactory` wraps it in the real facade. Every call is recorded, so tests can prove what was (not) reached, and
// "contexts" and listeners are counted the way the real viewport acquires them.
import { createReadOnlyViewport, type InspectionPort, type SceneViewerFactory } from "./readOnlyViewport";

export type FakeStats = {
  created: number; disposed: number; liveContexts: number; peakContexts: number; liveListeners: number; disposedDetached: number;
  calls: string[];
};

type Handler = (payload: never) => void;

export function makeFakePort(canvas: HTMLCanvasElement, stats: FakeStats, handlers: Map<string, Set<Handler>>): InspectionPort {
  stats.created++;
  stats.liveContexts++;
  stats.peakContexts = Math.max(stats.peakContexts, stats.liveContexts);
  // The real viewport adds pointer listeners to its canvas; mimic that so leaks are visible.
  const onDown = () => undefined;
  canvas.addEventListener("pointerdown", onDown);
  stats.liveListeners++;
  let disposed = false;
  const rec = (name: string) => { stats.calls.push(name); };
  const sub = (event: string, map: (p: never) => unknown, cb: (v: never) => void) => {
    const handler: Handler = (p) => cb(map(p) as never);
    let set = handlers.get(event);
    if (!set) handlers.set(event, (set = new Set()));
    set.add(handler);
    stats.liveListeners++;
    return () => { if (set!.delete(handler)) stats.liveListeners--; };
  };
  const port = {
    setPlate: () => rec("setPlate"),
    setSelection: (ids: string[]) => rec(`setSelection:${ids.join(",")}`),
    view: (p: string) => rec(`view:${p}`),
    zoomBy: () => rec("zoomBy"),
    setRenderMode: (m: string) => rec(`setRenderMode:${m}`),
    setOverhangAngle: () => rec("setOverhangAngle"),
    setTheme: () => rec("setTheme"),
    setGuides: () => rec("setGuides"),
    setBedAlert: () => rec("setBedAlert"),
    onPick: (cb: (id: string | null) => void) => sub("pick", (p: { objectId: string | null }) => p.objectId, cb),
    onSelect: (cb: (ids: string[]) => void) => sub("select", (p: { ids: string[] }) => p.ids, cb),
    onError: (cb: (m: string) => void) => sub("error", (p: { message: string }) => p.message, cb),
    onDegrade: (cb: (m: string) => void) => sub("degrade", (p: { message: string }) => p.message, cb),
    dispose: () => {
      if (disposed) return;
      disposed = true;
      stats.disposed++;
      if (!canvas.isConnected) stats.disposedDetached++;
      stats.liveContexts--;
      canvas.removeEventListener("pointerdown", onDown);
      stats.liveListeners--;
      for (const set of handlers.values()) stats.liveListeners -= set.size;
      handlers.clear();
    },
  };
  return port as unknown as InspectionPort;
}

export function makeFakeFactory(opts: { failCreate?: () => boolean } = {}) {
  const stats: FakeStats = {
    created: 0, disposed: 0, liveContexts: 0, peakContexts: 0, liveListeners: 0, disposedDetached: 0, calls: [],
  };
  const handlers = new Map<string, Set<Handler>>();
  const emit = (event: string, payload: unknown) => { for (const h of [...(handlers.get(event) ?? [])]) (h as (p: unknown) => void)(payload); };
  const factory: SceneViewerFactory = (canvas, { theme }) => {
    if (opts.failCreate?.()) throw new Error("no webgl");
    return createReadOnlyViewport(makeFakePort(canvas, stats, handlers), theme);
  };
  return { factory, stats, emit };
}
