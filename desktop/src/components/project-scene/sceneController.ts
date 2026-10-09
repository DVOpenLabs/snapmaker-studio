// Lifecycle of one project view: load the scene from the engine, build a FRESH canvas for it, and tear everything down
// again. Framework-free so it can be tested without React or WebGL. One controller per React effect.
//
// Rules this file keeps:
//   * every load gets its own AbortController and a new generation number; a result from an older generation, path or
//     controller is dropped (so A -> B -> A cannot show A's first answer for the second A);
//   * disposing aborts the load, which also tells the engine to cancel (see loadScene);
//   * a canvas is never reused: each graphics start creates a canvas, and dispose removes it;
//   * late callbacks after dispose do nothing.
import { SceneError, isAbort, type LoadSceneOptions, type SceneErrorCode, type SceneProgress, type SceneV1 } from "@/lib/scene";
import type { CameraPreset, ReadOnlyViewport, SceneViewerFactory, ThemeMode } from "./readOnlyViewport";
import { buildModel, buildViewScene, type SceneModel, type ViewScene } from "./sceneModel";

export type GraphicsState = "none" | "working" | "unavailable" | "lost";
export type ViewerState = {
  phase: "idle" | "loading" | "shown" | "failed";
  progress: SceneProgress | null;
  error: SceneErrorCode | null;
  model: SceneModel | null;
  revision: string | null;
  graphics: GraphicsState;
  /** A non-fatal note from the graphics layer, for example that it slowed itself down. */
  graphicsNote: string | null;
  selectedId: string | null;
  preset: CameraPreset;
  slope: boolean;
};

export type ControllerDeps = {
  load: (path: string, opts: LoadSceneOptions) => Promise<SceneV1>;
  viewportFactory: SceneViewerFactory;
  theme: ThemeMode;
};

const INITIAL: ViewerState = {
  phase: "idle", progress: null, error: null, model: null, revision: null, graphics: "none", graphicsNote: null,
  selectedId: null, preset: "bed", slope: false,
};

export class SceneController {
  private state: ViewerState = INITIAL;
  private readonly listeners = new Set<() => void>();
  private disposed = false;
  private generation = 0;
  private path: string | null = null;
  private abort: AbortController | null = null;
  private scene: SceneV1 | null = null;
  private viewScene: ViewScene | null = null;
  private host: HTMLElement | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private viewer: ReadOnlyViewport | null = null;
  private offs: (() => void)[] = [];
  private theme: ThemeMode;

  constructor(private readonly deps: ControllerDeps) {
    this.theme = deps.theme;
  }

  getState = (): ViewerState => this.state;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private set(patch: Partial<ViewerState>): void {
    if (this.disposed) return;
    this.state = { ...this.state, ...patch };
    for (const l of [...this.listeners]) l();
  }

  /** Starts (or restarts) loading for a path. Any earlier load is cancelled first. */
  setPath(path: string | null): void {
    if (this.disposed) return;
    this.cancelLoad();
    this.teardownGraphics();
    this.scene = null;
    this.viewScene = null;
    this.path = path;
    this.set({ ...INITIAL });
    if (!path) return;
    const generation = ++this.generation;
    const abort = new AbortController();
    this.abort = abort;
    this.set({ phase: "loading" });
    this.deps.load(path, {
      signal: abort.signal,
      onProgress: (p) => { if (this.current(generation, path)) this.set({ progress: p }); },
    }).then(
      (scene) => {
        if (!this.current(generation, path)) return;
        this.abort = null;
        this.scene = scene;
        let model: SceneModel;
        try {
          model = buildModel(scene);
        } catch {
          this.set({ phase: "failed", error: "BAD_RESPONSE" });
          return;
        }
        this.set({ phase: "shown", model, revision: scene.revision, progress: null });
        this.startGraphics();
      },
      (error: unknown) => {
        if (!this.current(generation, path)) return;
        this.abort = null;
        if (isAbort(error)) return;
        this.set({ phase: "failed", error: error instanceof SceneError ? error.code : "INTERNAL", progress: null });
      },
    );
  }

  private current(generation: number, path: string): boolean {
    return !this.disposed && generation === this.generation && path === this.path;
  }

  retryLoad(): void {
    if (this.path) this.setPath(this.path);
  }

  /** The element the canvas goes into. Passing null (or a new element) removes the current canvas. */
  setHost(host: HTMLElement | null): void {
    if (this.disposed || host === this.host) return;
    this.teardownGraphics();
    this.host = host;
    if (host && this.state.phase === "shown") this.startGraphics();
  }

  /** Builds a brand new canvas and viewer. Used on first show and by the Retry button. */
  startGraphics(): void {
    if (this.disposed || !this.host || !this.scene || !this.state.model) return;
    this.teardownGraphics();
    // Decode the geometry first: a scene the engine sent badly is a load problem with its own message, not a graphics one.
    let viewScene: ViewScene;
    try {
      viewScene = this.viewScene ?? (this.viewScene = buildViewScene(this.scene, this.state.model));
    } catch (error) {
      this.set({ phase: "failed", error: error instanceof SceneError ? error.code : "BAD_RESPONSE", graphics: "none" });
      return;
    }
    const canvas = this.host.ownerDocument.createElement("canvas");
    canvas.style.cssText = "display:block;width:100%;height:100%";
    this.host.appendChild(canvas);
    this.canvas = canvas;
    let viewer: ReadOnlyViewport;
    try {
      viewer = this.deps.viewportFactory(canvas, { theme: this.theme });
    } catch {
      this.removeCanvas();
      this.set({ graphics: "unavailable", graphicsNote: null });
      return;
    }
    this.viewer = viewer;
    this.offs.push(
      viewer.onPick((id) => this.select(id)),
      // The viewer cleared its own selection (Escape): keep the list in step. Selections we make ourselves are not echoed.
      viewer.onSelect((ids) => { if (ids.length === 0 && this.state.selectedId !== null) this.set({ selectedId: null }); }),
      viewer.onTrouble((t) => {
        if (this.viewer !== viewer) return;
        if (t.fatal) {
          this.teardownGraphics();
          this.set({ graphics: "lost", graphicsNote: null });
        } else {
          this.set({ graphicsNote: t.message });
        }
      }),
    );
    try {
      viewer.show(viewScene);
      viewer.setSlopeView(this.state.slope);
      viewer.setSelected(this.state.selectedId ? this.meshIdsUnder(this.state.selectedId) : []);
      if (this.state.preset !== "bed") viewer.setCamera(this.state.preset);
    } catch {
      this.teardownGraphics();
      this.set({ graphics: "unavailable" });
      return;
    }
    this.set({ graphics: "working", graphicsNote: null });
  }

  /** A click in the 3D view: select the whole top-level object it belongs to, in the view and in the list. */
  select(id: string | null): void {
    if (this.disposed) return;
    this.selectFromList(id ? this.topLevelId(id) : null);
  }

  private topLevelId(id: string): string {
    const byId = new Map((this.scene?.nodes ?? []).map((n) => [n.id, n]));
    let cur = byId.get(id);
    for (let guard = 0; cur && cur.parent_id !== null && guard < 80; guard++) {
      const parent = byId.get(cur.parent_id);
      if (!parent) break;
      cur = parent;
    }
    return cur?.id ?? id;
  }

  /** Every drawn piece (node with a mesh) at or under a top-level object. */
  private meshIdsUnder(topId: string): string[] {
    const nodes = this.scene?.nodes ?? [];
    const kids = new Map<string, string[]>();
    for (const n of nodes) if (n.parent_id !== null) kids.set(n.parent_id, [...(kids.get(n.parent_id) ?? []), n.id]);
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const out: string[] = [];
    const stack = [topId];
    const seen = new Set<string>();
    while (stack.length) {
      const id = stack.pop()!;
      if (seen.has(id)) continue;
      seen.add(id);
      if (byId.get(id)?.mesh_key) out.push(id);
      for (const k of kids.get(id) ?? []) stack.push(k);
    }
    return out;
  }

  selectFromList(id: string | null): void {
    if (this.disposed) return;
    this.set({ selectedId: id });
    this.viewer?.setSelected(id ? this.meshIdsUnder(id) : []);
  }

  setCamera(preset: CameraPreset): void {
    if (this.disposed) return;
    this.set({ preset });
    this.viewer?.setCamera(preset);
  }

  setSlope(on: boolean): void {
    if (this.disposed) return;
    this.set({ slope: on });
    this.viewer?.setSlopeView(on);
  }

  setTheme(theme: ThemeMode): void {
    if (this.disposed || theme === this.theme) return;
    this.theme = theme;
    this.viewer?.setTheme(theme);
  }

  private cancelLoad(): void {
    this.abort?.abort();
    this.abort = null;
  }

  private removeCanvas(): void {
    this.canvas?.remove();
    this.canvas = null;
  }

  private teardownGraphics(): void {
    for (const off of this.offs.splice(0)) off();
    const viewer = this.viewer;
    this.viewer = null;
    // three's OrbitControls removes one of its document-level listeners through canvas.getRootNode(). React removes a
    // route's DOM before passive cleanups run, so a canvas that is already detached would leave that listener behind.
    // Dispose with the canvas attached: put a detached one back (in the page body) just for the call.
    const canvas = this.canvas;
    if (viewer && canvas && !canvas.isConnected) canvas.ownerDocument.body.appendChild(canvas);
    try { viewer?.dispose(); } catch { /* disposal must never throw out of cleanup */ }
    this.removeCanvas();
  }

  dispose(): void {
    if (this.disposed) return;
    this.cancelLoad();
    this.teardownGraphics();
    this.disposed = true;
    this.generation++;
    this.listeners.clear();
    this.scene = null;
    this.host = null;
  }
}
