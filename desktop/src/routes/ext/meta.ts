import type { LucideIcon } from "lucide-react";

export interface ExtensionMeta {
  path: string;
  label: string;
  title: string;
  group: "Studio+";
  icon: LucideIcon;
}

const modules = import.meta.glob<ExtensionMeta>("./*.meta.ts", {
  eager: true,
  import: "default",
});

export const EXTENSION_META_MODULES: Record<string, ExtensionMeta> = modules;

// Glob keys only (no route module is imported here): used to find which metas have a route.
const routeKeys = Object.keys(import.meta.glob("./*.route.tsx", { eager: false }));

/** Keep only metadata whose stem has a matching `<stem>.route.tsx` key. */
export function pairExtensionMetadata(
  metas: Record<string, ExtensionMeta>,
  routeFilenames: readonly string[],
): ExtensionMeta[] {
  const routeStems = new Set(routeFilenames.map((name) => name.replace(/^\.\//, "").replace(/\.route\.tsx$/, "")));
  return Object.entries(metas)
    .filter(([name]) => routeStems.has(name.replace(/^\.\//, "").replace(/\.meta\.ts$/, "")))
    .map(([, meta]) => meta);
}

/** Metadata with a matching route file; the only collection nav, route checks and titles may use. */
export const PAIRED_EXTENSION_METADATA: readonly ExtensionMeta[] = pairExtensionMetadata(modules, routeKeys);

/** Resolve an extension title for its route and nested route segments. */
export function extensionTitleFor(
  path: string,
  metadata: readonly ExtensionMeta[] = PAIRED_EXTENSION_METADATA,
): string | undefined {
  return metadata.find(({ path: base }) => path === base || path.startsWith(`${base.replace(/\/$/, "")}/`))?.title;
}
