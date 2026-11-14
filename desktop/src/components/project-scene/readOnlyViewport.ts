// The read-only facade. Studio code never holds the vendored SlicerX viewport. The vendored source ships editing code
// (move, rotate, scale, paint, cut, sketch) and that code is still in the bundle, so the boundary is structural:
//   * defaultViewport.ts is the only file that imports the viewport's factory. It sets the tool to "probe" (a click only
//     reports what is under the cursor), keeps the viewport inside a closure, and hands out an `InspectionPort`;
//   * this file turns that port into `ReadOnlyViewport`. The port has no setTool and no generic `on`: only the named
//     inspection calls below and four named subscriptions;
//   * readOnly.guard.test.ts scans all of src/ so no other file can import the vendor tree or name an editing call.
import type { Viewport } from "@/vendor/slicerx/entry";
import type { ViewScene } from "./sceneModel";

/** The members of the vendored viewport the port may forward. Editing members, setTool and the generic `on` are absent. */
export type InspectionCalls = Pick<
  Viewport,
  "setPlate" | "setSelection" | "view" | "zoomBy" | "setRenderMode" | "setOverhangAngle" | "setTheme" | "setGuides"
  | "setBedAlert" | "dispose"
>;
export type InspectionPort = InspectionCalls & {
  onPick(handler: (objectId: string | null) => void): () => void;
  onSelect(handler: (ids: string[]) => void): () => void;
  onError(handler: (message: string) => void): () => void;
  onDegrade(handler: (message: string) => void): () => void;
};
/** Builds a read-only viewer on a fresh canvas. Throws if graphics cannot start; never leaves a half-built viewer behind. */
export type SceneViewerFactory = (canvas: HTMLCanvasElement, options: { theme: ThemeMode }) => ReadOnlyViewport;

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
  /** The viewer cleared or changed its own selection (for example Escape). */
  onSelect(handler: (ids: string[]) => void): () => void;
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

export function createReadOnlyViewport(port: InspectionPort, theme: ThemeMode): ReadOnlyViewport {
  port.setTheme({ scene: THEMES[theme] });
  const picks = new Set<(id: string | null) => void>();
  const selects = new Set<(ids: string[]) => void>();
  const troubles = new Set<(t: Trouble) => void>();
  const offs = [
    port.onPick((id) => { for (const h of [...picks]) h(id); }),
    port.onSelect((ids) => { for (const h of [...selects]) h(ids); }),
    port.onError((message) => { for (const h of [...troubles]) h({ message, fatal: true }); }),
    port.onDegrade((message) => { for (const h of [...troubles]) h({ message, fatal: false }); }),
  ];
  let disposed = false;
  return {
    show(scene) {
      if (disposed) return;
      port.setPlate({
        bed: scene.bed,
        objects: scene.objects.map((o) => ({
          id: o.id, name: o.name, transform: o.transform,
          parts: o.parts.map((p) => ({ name: p.name, positions: p.positions, indices: p.indices, color: p.color })),
        })),
      });
      port.setGuides(scene.marginLoop ? { loops: [{ points: scene.marginLoop, soft: true }] } : {});
      port.setBedAlert(scene.bedAlert);
      port.view("bed", { animate: false });
      // An object placed past the bed edge has to stay in frame, so back the camera away a little.
      if (scene.bedAlert) port.zoomBy(0.7, { animate: false });
    },
    setSelected(ids) { if (!disposed) port.setSelection([...ids]); },
    setCamera(preset) { if (!disposed) port.view(preset); },
    setSlopeView(on) {
      if (disposed) return;
      port.setRenderMode(on ? "overhang" : "studio");
      if (on) port.setOverhangAngle(SLOPE_ANGLE_DEG);
    },
    setTheme(mode) { if (!disposed) port.setTheme({ scene: THEMES[mode] }); },
    onPick(handler) { picks.add(handler); return () => { picks.delete(handler); }; },
    onSelect(handler) { selects.add(handler); return () => { selects.delete(handler); }; },
    onTrouble(handler) { troubles.add(handler); return () => { troubles.delete(handler); }; },
    dispose() {
      if (disposed) return;
      disposed = true;
      for (const off of offs) off();
      picks.clear();
      selects.clear();
      troubles.clear();
      port.dispose();
    },
  };
}
