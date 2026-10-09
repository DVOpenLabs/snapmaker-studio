// A stand-in for the vendored viewport, used by tests. It records every call so tests can prove what was (not) reached,
// and it counts live "contexts" and listeners the way the real one acquires them.
import type { ViewportFactory, ViewportSubset } from "./readOnlyViewport";

export type FakeStats = {
  created: number; disposed: number; liveContexts: number; peakContexts: number; liveListeners: number; disposedDetached: number; calls: string[];
};

export function makeFakeFactory(opts: { failCreate?: () => boolean } = {}) {
  const stats: FakeStats = { created: 0, disposed: 0, liveContexts: 0, peakContexts: 0, liveListeners: 0, disposedDetached: 0, calls: [] };
  const handlers = new Map<string, Set<(p: never) => void>>();
  const emit = (event: string, payload: unknown) => { for (const h of [...(handlers.get(event) ?? [])]) (h as (p: unknown) => void)(payload); };
  const factory: ViewportFactory = (canvas) => {
    if (opts.failCreate?.()) throw new Error("no webgl");
    stats.created++;
    stats.liveContexts++;
    stats.peakContexts = Math.max(stats.peakContexts, stats.liveContexts);
    // The real viewport adds pointer listeners to its canvas; mimic that so leaks are visible.
    const onDown = () => undefined;
    canvas.addEventListener("pointerdown", onDown);
    stats.liveListeners++;
    let disposed = false;
    const rec = (name: string) => { stats.calls.push(name); };
    const vp = {
      canvas,
      setTool: (t: string) => rec(`setTool:${t}`),
      setPlate: () => rec("setPlate"),
      setSelection: (ids: string[]) => rec(`setSelection:${ids.join(",")}`),
      view: (p: string) => rec(`view:${p}`),
      zoomBy: () => rec("zoomBy"),
      setRenderMode: (m: string) => rec(`setRenderMode:${m}`),
      setDisplayStyle: () => rec("setDisplayStyle"),
      setOverhangAngle: () => rec("setOverhangAngle"),
      setTheme: () => rec("setTheme"),
      setGuides: () => rec("setGuides"),
      setBedAlert: () => rec("setBedAlert"),
      on: (event: string, cb: (p: never) => void) => {
        let set = handlers.get(event);
        if (!set) handlers.set(event, (set = new Set()));
        set.add(cb);
        stats.liveListeners++;
        return () => { if (set!.delete(cb)) stats.liveListeners--; };
      },
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
    return vp as unknown as ViewportSubset;
  };
  return { factory, stats, emit };
}
