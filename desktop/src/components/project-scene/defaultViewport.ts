// The one place that imports the vendored viewport at run time, and the only place that touches its tool. Only the lazily
// loaded panel imports this file, so three.js and the viewport stay out of the main bundle. The viewport lives in a closure
// here: callers get a `ReadOnlyViewport` (no setTool, no generic `on`, no handle).
import { createViewport, type Viewport } from "@/vendor/slicerx/entry";
import { ViewerUnavailableError, createReadOnlyViewport, type InspectionPort, type SceneViewerFactory } from "./readOnlyViewport";

const LABEL = "3D view of the project. Drag to turn the view, scroll to zoom.";

function portOf(raw: Viewport): InspectionPort {
  return {
    setPlate: (plate, opts) => raw.setPlate(plate, opts),
    setSelection: (ids) => raw.setSelection(ids),
    view: (preset, opts) => raw.view(preset, opts),
    zoomBy: (factor, opts) => raw.zoomBy(factor, opts),
    setRenderMode: (mode) => raw.setRenderMode(mode),
    setOverhangAngle: (deg) => raw.setOverhangAngle(deg),
    setTheme: (theme) => raw.setTheme(theme),
    setGuides: (guides) => raw.setGuides(guides),
    setBedAlert: (on) => raw.setBedAlert(on),
    dispose: () => raw.dispose(),
    onPick: (handler) => raw.on("pick", (e) => handler(e.objectId)),
    onSelect: (handler) => raw.on("select", (e) => handler(e.ids)),
    onError: (handler) => raw.on("error", (e) => handler(e.message)),
    onDegrade: (handler) => raw.on("degrade", (e) => handler(e.message)),
  };
}

export const createSceneViewer: SceneViewerFactory = (canvas, { theme }) => {
  let raw: Viewport;
  try {
    raw = createViewport(canvas, { label: LABEL, quality: "balanced" });
  } catch {
    throw new ViewerUnavailableError();
  }
  try {
    // "probe": a click reports what is under the cursor and moves, rotates, scales and paints nothing.
    raw.setTool("probe");
    return createReadOnlyViewport(portOf(raw), theme);
  } catch (error) {
    // The renderer, its listeners and its GL context exist by now: release them rather than leave them behind.
    try { raw.dispose(); } catch { /* nothing more to do */ }
    throw error;
  }
};
