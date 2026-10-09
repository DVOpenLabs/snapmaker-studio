// The one place that imports the vendored viewport at run time. Only the lazily loaded panel imports this file, so
// three.js and the viewport stay out of the main bundle.
import { createViewport } from "@/vendor/slicerx/entry";
import type { ViewportFactory } from "./readOnlyViewport";

export const defaultViewportFactory: ViewportFactory = (canvas, options) =>
  createViewport(canvas, { label: options.label, quality: options.quality });
