import { describe, expect, it } from "vitest";
// @ts-expect-error Node builtin is used at runtime; this checkout omits @types/node.
import * as fs from "node:fs";
import { EXTENSION_ROUTES, EXTENSION_METADATA, joinExtensionRoutes, type ExtensionRoute } from "./index";
import { EXTENSION_META_MODULES, extensionTitleFor, pairExtensionMetadata, type ExtensionMeta } from "./meta";
import { Home } from "lucide-react";
import { STATIC_ROUTES, isKnownRoute, primaryNavItems } from "@/lib/nav";

const routeFiles = Object.keys(import.meta.glob("./*.route.tsx"));
const metaFiles = Object.keys(import.meta.glob("./*.meta.ts"));
const routeStem = (filename: string) => filename.replace(/^\.\//, "").replace(/\.route\.tsx$/, "");
const metadataStem = (filename: string) => filename.replace(/^\.\//, "").replace(/\.meta\.ts$/, "");
const forbiddenRouteImport = (source: string) =>
  /(?:\bfrom\s*|\bimport\s*(?:\(\s*)?)['"][^'"]*(?:\/lib\/nav|components\/shell)(?:\.[jt]sx?)?(?:['"]|\/)/.test(source);
const forbiddenMetaImport = (source: string) =>
  forbiddenRouteImport(source) ||
  /(?:\bfrom\s*|\bimport\s*(?:\(\s*)?)['"][^'"]*routes\/ext(?:\.[jt]sx?)?(?:['"]|\/)/.test(source) ||
  // Relative specifiers reaching the route index or meta module from a sibling meta file.
  /(?:\bfrom\s*|\bimport\s*(?:\(\s*)?)['"](?:\.{1,2}|\.\.\/ext)(?:\/(?:index|meta)?(?:\.[jt]sx?)?)?['"]/.test(source);

describe("extension route seam", () => {
  it("requires a meta entry for every route file and a route for every meta file", () => {
    expect(routeFiles.map(routeStem).sort()).toEqual(metaFiles.map(metadataStem).sort());
  });

  it("does not expose either half of an unmatched synthetic track", () => {
    const component = () => null;
    const route: ExtensionRoute = { path: "/ignored", Component: component };
    const meta: ExtensionMeta = { path: "/synthetic", label: "Synthetic", title: "Synthetic", group: "Studio+", icon: Home };
    expect(joinExtensionRoutes({ "./only-route.route.tsx": route }, {})).toEqual([]);
    expect(joinExtensionRoutes({}, { "./only-meta.meta.ts": meta })).toEqual([]);
    expect(joinExtensionRoutes({ "./synthetic.route.tsx": route }, { "./synthetic.meta.ts": meta })).toEqual([
      { ...route, path: "/synthetic" },
    ]);
  });

  it("has no half-paired entries in the imported route and metadata lists", () => {
    expect(EXTENSION_ROUTES).toHaveLength(EXTENSION_METADATA.length);
  });

  it("validates metadata paths and confirms meta.path is the route source of truth", async () => {
    const paths = EXTENSION_METADATA.map(({ path }) => path);
    expect(new Set(paths).size).toBe(paths.length);
    for (const [metaFilename, metadata] of Object.entries(EXTENSION_META_MODULES).filter(([filename]) =>
      routeFiles.some((routeFilename) => routeStem(routeFilename) === metadataStem(filename)))) {
      expect(metadata.group).toBe("Studio+");
      expect(metadata.path.startsWith("/")).toBe(true);
      expect(STATIC_ROUTES.has(metadata.path)).toBe(false);
      expect(metadata.path.startsWith("/doctor/")).toBe(false);
      const routeSource = await readSource(`${metadataStem(metaFilename)}.route.tsx`);
      const declaredPath = /\bpath\s*:\s*["']([^"']+)["']/.exec(routeSource)?.[1];
      if (declaredPath !== undefined) expect(metadata.path).toBe(declaredPath);
    }
  });

  it("converts a metadata filename to its route filename", () => {
    expect(`${metadataStem("./setups.meta.ts")}.route.tsx`).toBe("setups.route.tsx");
    expect(routeStem("./setups.route.tsx")).toBe(metadataStem("./setups.meta.ts"));
  });

  it("excludes an unpaired synthetic meta from paired metadata and titles", () => {
    const paired: ExtensionMeta = { path: "/paired", label: "Paired", title: "Paired title", group: "Studio+", icon: Home };
    const orphan: ExtensionMeta = { path: "/orphan", label: "Orphan", title: "Orphan title", group: "Studio+", icon: Home };
    const result = pairExtensionMetadata(
      { "./paired.meta.ts": paired, "./orphan.meta.ts": orphan },
      ["./paired.route.tsx", "./route-only.route.tsx"],
    );
    expect(result).toEqual([paired]);
    expect(extensionTitleFor("/paired", result)).toBe("Paired title");
    expect(extensionTitleFor("/orphan", result)).toBeUndefined();
    expect(primaryNavItems(result).some((item) => item.to === "/orphan")).toBe(false);
    expect(primaryNavItems(result).some((item) => item.to === "/paired")).toBe(true);
    expect(isKnownRoute("/orphan", result)).toBe(false);
    expect(isKnownRoute("/paired", result)).toBe(true);
  });

  it("resolves an extension title only on its path or a segment below it", () => {
    const metadata = [{ path: "/tool", label: "Tool", title: "Tool title", group: "Studio+" as const, icon: Home }];
    expect(extensionTitleFor("/tool", metadata)).toBe("Tool title");
    expect(extensionTitleFor("/tool/child", metadata)).toBe("Tool title");
    expect(extensionTitleFor("/toolbox", metadata)).toBeUndefined();
  });

  it("scanner rejects forbidden imports in a synthetic route source", () => {
    expect(forbiddenRouteImport('import { STATIC_ROUTES, isKnownRoute, primaryNavItems } from "@/lib/nav";')).toBe(true);
    expect(forbiddenRouteImport('import "@/lib/nav";')).toBe(true);
    expect(forbiddenRouteImport('import AppShell from "@/components/shell/AppShell";')).toBe(true);
    expect(forbiddenRouteImport('import { STATIC_ROUTES } from "../../lib/nav";')).toBe(true);
    expect(forbiddenRouteImport('import("../../components/shell/AppShell");')).toBe(true);
    expect(forbiddenRouteImport('import View from "./View";')).toBe(false);
    expect(forbiddenRouteImport('import { STATIC_ROUTES } from "../../lib/nav.ts";')).toBe(true);
    expect(forbiddenRouteImport('import AppShell from "@/components/shell/AppShell.tsx";')).toBe(true);
    expect(forbiddenRouteImport('import("../../lib/nav.js");')).toBe(true);
    expect(forbiddenRouteImport('import View from "./navigation.ts";')).toBe(false);
  });

  it("meta scanner also rejects the extension route index", () => {
    expect(forbiddenMetaImport('import { x } from "@/lib/nav";')).toBe(true);
    expect(forbiddenMetaImport('import { x } from "@/routes/ext";')).toBe(true);
    expect(forbiddenMetaImport('import { x } from "@/routes/ext/index.ts";')).toBe(true);
    for (const spec of ["./index", "./index.ts", ".", "./", "./meta", "./meta.ts", "../ext", "../ext/index"]) {
      expect(forbiddenMetaImport(`import { x } from "${spec}";`), spec).toBe(true);
    }
    expect(forbiddenMetaImport('import("./index");')).toBe(true);
    expect(forbiddenMetaImport('import { x } from "./other.meta";')).toBe(false);
    expect(forbiddenMetaImport('import { Home } from "lucide-react";')).toBe(false);
  });

  it("keeps meta modules independent from navigation, shell and the route index", () => {
    const cwd = (globalThis as any).process.cwd();
    const dir = `${cwd}/src/routes/ext`;
    for (const filename of fs.readdirSync(dir).filter((name: string) => name.endsWith(".meta.ts"))) {
      expect(forbiddenMetaImport(fs.readFileSync(`${dir}/${filename}`, "utf8")), filename).toBe(false);
    }
  });

  it("keeps route modules independent from navigation and shell modules", () => {
    const cwd = (globalThis as any).process.cwd();
    const routeDirectory = `${cwd}/src/routes/ext`;
    for (const filename of fs.readdirSync(routeDirectory).filter((name: string) => name.endsWith(".route.tsx"))) {
      const source = fs.readFileSync(`${routeDirectory}/${filename}`, "utf8");
      expect(forbiddenRouteImport(source), filename).toBe(false);
    }
  });
});

const readSource = async (filename: string): Promise<string> =>
  fs.readFileSync(`${(globalThis as any).process.cwd()}/src/routes/ext/${filename}`, "utf8");
