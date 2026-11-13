import type { ComponentType } from "react";
import type { ExtensionMeta } from "./meta";
import { EXTENSION_META_MODULES, PAIRED_EXTENSION_METADATA } from "./meta";

export interface ExtensionRoute {
  path: string;
  Component: ComponentType;
}

const routeModules = import.meta.glob<ExtensionRoute>("./*.route.tsx", {
  eager: true,
  import: "default",
});

function stem(filename: string): string {
  return filename.replace(/^\.\//, "").replace(/\.route\.tsx$/, "");
}

function metaStem(filename: string): string {
  return filename.replace(/^\.\//, "").replace(/\.meta\.ts$/, "");
}

/** Only complete track pairs become routes; missing halves are never rendered. */
export function joinExtensionRoutes(
  routes: Record<string, ExtensionRoute>,
  metas: Record<string, ExtensionMeta>,
): ExtensionRoute[] {
  return Object.entries(routes).flatMap(([filename, route]) => {
    const meta = Object.entries(metas).find(([metaFilename]) => metaStem(metaFilename) === stem(filename))?.[1];
    return meta ? [{ ...route, path: meta.path }] : [];
  });
}

export const EXTENSION_ROUTES = joinExtensionRoutes(routeModules, EXTENSION_META_MODULES);
export const EXTENSION_METADATA = PAIRED_EXTENSION_METADATA;
