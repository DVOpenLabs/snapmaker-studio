// The ONLY door to the vendored SlicerX viewport. The vendored source ships editing code (move, rotate, scale, paint, cut,
// sketch). That code is still in the bundle, but nothing here can reach it: the viewport handle is never returned, the
// tool is fixed to "probe" (a click only reports what is under the cursor), and the methods below are the whole surface.
import type { Viewport } from "@/vendor/slicerx/entry";
import type { ViewScene } from "./sceneModel";

/** The exact members of the vendored viewport this file may call. Editing methods are deliberately absent. */
export type ViewportSubset = Pick<
  Viewport,
  "canvas" | "setTool" | "setPlate" | "setSelection" | "view" | "zoomBy" | "setRenderMode" | "setDisplayStyle" | "setOverhangAngle"
  | "setTheme" | "setGuides" | "setBedAlert" | "on" | "dispose"
>;
export type ViewportFactory = (canvas: HTMLCanvasElement, options: { label: string; quality: "balanced" }) => ViewportSubset;

export type CameraPreset = "iso" | "top" | "front" | "back" | "left" | "right" | "fit" | "bed";
export const CAMERA_PRESETS: { id: CameraPreset; label: string }[] = [
  { id: "iso", label: "Corner view" },
  { id: "top", label: "Top" },
  { id: "front", label: "Front" },
  { id: "back", label: "Back" },
  { id: "left", label: "Left" },
  { id: "right", label: "Right" },
  { id: "bed", label: "Whole bed" },
  { id: "fit", label: "Zoom to objects" },
];

/** Shown next to the slope toggle. The wording is fixed. */
export const SLOPE_LABEL = "Geometric slope visualization - review supports in Orca.";
/** Degrees from vertical where the slope view starts to color a face. A display setting, not a print rule. */
const SLOPE_ANGLE_DEG = 45;

export type ThemeMode = "light" | "dark";
const THEMES: Record<ThemeMode, { bgTop: string; bgBottom: string; bgGlow: string; selection: string; floorGrid: string }> = {
  dark: { bgTop: "#253b47", bgBottom: "#101c25", bgGlow: "#2d4754", selection: "#bd93f9", floorGrid: "#8babb7" },
  light: { bgTop: "#eff4f6", bgBottom: "#d3e0e6", bgGlow: "#ffffff", selection: "#6d3fd0", floorGrid: "#6d8793" },
};

export type Trouble = { message: string; fatal: boolean };

export interface ReadOnlyViewport {
  show(scene: ViewScene): void;
  setSelected(ids: string[]): void;
  setCamera(preset: CameraPreset): void;
  setSlopeView(on: boolean): void;
  setTheme(mode: ThemeMode): void;
  /** A click on an object reports its id, a click on empty space reports null. Returns an unsubscribe function. */
  onPick(handler: (id: string | null) => void): () => void;
  /** Graphics trouble. `fatal` means the drawing surface is gone and the view must be rebuilt on a new canvas. */
  onTrouble(handler: (t: Trouble) => void): () => void;
  dispose(): void;
}

export class ViewerUnavailableError extends Error {
  constructor() {
    super("3D graphics are not available");
    this.name = "ViewerUnavailableError";
  }
}

export function createReadOnlyViewport(
  canvas: HTMLCanvasElement, factory: ViewportFactory, theme: ThemeMode,
): ReadOnlyViewport {
  let vp: ViewportSubset;
  try {
    vp = factory(canvas, { label: "3D view of the project. Drag to orbit, scroll to zoom.", quality: "balanced" });
  } catch {
    throw new ViewerUnavailableError();
  }
  // "probe": a click reports what is under the cursor and moves, rotates, scales and paints nothing.
  vp.setTool("probe");
  vp.setTheme({ scene: THEMES[theme] });
  const picks = new Set<(id: string | null) => void>();
  const troubles = new Set<(t: Trouble) => void>();
  const offs = [
    vp.on("pick", (e) => { for (const h of [...picks]) h(e.objectId); }),
    vp.on("error", (e) => { for (const h of [...troubles]) h({ message: e.message, fatal: true }); }),
    vp.on("degrade", (e) => { for (const h of [...troubles]) h({ message: e.message, fatal: false }); }),
  ];
  let disposed = false;
  return {
    show(scene) {
      if (disposed) return;
      vp.setPlate({
        bed: scene.bed,
        objects: scene.objects.map((o) => ({
          id: o.id, name: o.name, transform: o.transform,
          parts: o.parts.map((p) => ({ name: p.name, positions: p.positions, indices: p.indices, color: p.color })),
        })),
      });
      vp.setGuides(scene.marginLoop ? { loops: [{ points: scene.marginLoop, soft: true }] } : {});
      vp.setBedAlert(scene.bedAlert);
      vp.view("bed", { animate: false });
      // An object placed past the bed edge has to stay in frame, so back the camera away a little.
      if (scene.bedAlert) vp.zoomBy(0.7, { animate: false });
    },
    setSelected(ids) { if (!disposed) vp.setSelection([...ids]); },
    setCamera(preset) { if (!disposed) vp.view(preset); },
    setSlopeView(on) {
      if (disposed) return;
      vp.setRenderMode(on ? "overhang" : "studio");
      if (on) vp.setOverhangAngle(SLOPE_ANGLE_DEG);
    },
    setTheme(mode) { if (!disposed) vp.setTheme({ scene: THEMES[mode] }); },
    onPick(handler) { picks.add(handler); return () => { picks.delete(handler); }; },
    onTrouble(handler) { troubles.add(handler); return () => { troubles.delete(handler); }; },
    dispose() {
      if (disposed) return;
      disposed = true;
      for (const off of offs) off();
      picks.clear();
      troubles.clear();
      vp.dispose();
    },
  };
}
