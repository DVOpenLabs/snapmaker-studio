/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";

// The vendored viewport still contains editing code (move, rotate, scale, paint, cut, sketch) because its entry class
// imports it. These checks prove Studio's own code cannot reach any of it. They scan ALL of src/ (not just this folder),
// so a bypass dropped into any component, route, store or lib file fails the build.
//
// What is enforced, and where:
//   * the vendor tree is named only by three files: readOnlyViewport.ts (a type import), defaultViewport.ts (the value
//     import of the entry file) and credits.ts (the NOTICE and LICENSE-APACHE texts, imported as plain text). No other file may mention it in any import, re-export, dynamic import() or string;
//   * every dynamic import() must have a plain string-literal argument;
//   * editing members (setTool, setCutPlane, ...) may not appear anywhere in src/ outside tests, except one literal
//     `setTool("probe")` in defaultViewport.ts;
//   * createViewport may appear only in defaultViewport.ts.
// Limit: this is a source scan. It cannot see a member name built at run time ("set" + "Tool"); code review covers that.
const files = import.meta.glob(["../../**/*.ts", "../../**/*.tsx", "!../../vendor/**", "!../../**/*.test.ts", "!../../**/*.test.tsx"], {
  query: "?raw", import: "default", eager: true,
}) as Record<string, string>;
const entry = import.meta.glob("../../vendor/slicerx/entry.ts", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

// Vite names a file by its shortest path from this folder ("./x.ts", "../shell/y.tsx", "../../z.ts"); make them src-relative.
const norm = (p: string) => new URL(p, "file:///src/components/project-scene/").pathname.replace(/^\/src\//, "");
const real: Record<string, string> = Object.fromEntries(Object.entries(files).map(([k, v]) => [norm(k), v]));
const FACADE = "components/project-scene/readOnlyViewport.ts";
const ADAPTER = "components/project-scene/defaultViewport.ts";
const CREDITS = "components/project-scene/credits.ts";
const CREDIT_ASSETS = ["@/vendor/slicerx/NOTICE?raw", "@/vendor/slicerx/LICENSE-APACHE?raw"];

const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const EDITING = [
  "setTool", "setPaintSettings", "setPaintData", "setPaintColors", "applyPaintEdits", "paintHeightRange", "performGapFill",
  "setCutPlane", "setTransforms", "setPush", "setSketch", "setSketchCursor", "setBrimEars", "setBrimHoverRadius", "setDimensions",
  "setPartStyle", "setEdgePreview", "setGapLines", "setRotateSpace", "setControls", "setProbeHover", "setProbeFaces",
];

/** Every way the scan knows to fail a file set. Returns readable violations; an empty list means the set is clean. */
function scan(set: Record<string, string>): string[] {
  const out: string[] = [];
  for (const [file, raw] of Object.entries(set)) {
    const text = code(raw);
    // 1. any quoted string that names the vendor tree or the SlicerX package.
    for (const m of text.matchAll(/["'`]([^"'`\n]*)["'`]/g)) {
      const spec = m[1];
      // Prose and URLs are not module specifiers (which never contain a space).
      if (/^https?:/i.test(spec) || /\s/.test(spec) || !spec.includes("/") || !(/(^|\/)vendor(\/|$)/.test(spec) || /slicerx/i.test(spec))) continue;
      const ok = ((file === FACADE || file === ADAPTER) && spec === "@/vendor/slicerx/entry") || (file === CREDITS && CREDIT_ASSETS.includes(spec));
      if (!ok) out.push(`${file}: names the vendor tree ("${spec}")`);
    }
    if (file === FACADE && /^import\s+(?!type\b)[^;]*["']@\/vendor\/slicerx\/entry["']/m.test(text)) out.push(`${file}: value import of the vendor entry`);
    if (file === ADAPTER && !/^import \{ createViewport, type Viewport \} from "@\/vendor\/slicerx\/entry";$/m.test(text)) out.push(`${file}: unexpected vendor import form`);
    // 2. dynamic import() needs a literal argument.
    for (const m of text.matchAll(/\bimport\s*\(\s*([^)]*)\)/g)) {
      if (!/^["'][^"'\n]*["']\s*$/.test(m[1].trim())) out.push(`${file}: dynamic import() with a computed argument`);
    }
    // 3. editing members, in any spelling that keeps the name (call, bracket access, destructuring, alias, string).
    for (const name of EDITING) {
      if (!text.includes(name)) continue;
      if (name === "setTool" && file === ADAPTER) continue; // counted below
      out.push(`${file}: mentions ${name}`);
    }
    // "arrange" is also ordinary English in the app's copy, so only member-style uses count: .arrange(, ["arrange"], { arrange } = x.
    if (/\.\s*arrange\s*\(|\[\s*["'`]arrange["'`]\s*\]|\{[^{}]*\barrange\b[^{}]*\}\s*=[^=]/.test(text)) out.push(`${file}: mentions arrange`);
    // 4. the raw factory.
    if (text.includes("createViewport") && file !== ADAPTER) out.push(`${file}: mentions createViewport`);
  }
  const adapter = set[ADAPTER];
  if (adapter !== undefined) {
    // In the adapter createViewport may appear exactly twice: in its import, and as ONE call expression. Re-exports, aliases,
    // a second call or passing it on as a value all add an occurrence and fail.
    const words = [...code(adapter).matchAll(/\bcreateViewport\b/g)].length;
    const calls = [...code(adapter).matchAll(/\bcreateViewport\s*\(/g)].length;
    if (words !== 2 || calls !== 1) out.push(`${ADAPTER}: createViewport must appear only in its import and in one call`);
    const tools = [...code(adapter).matchAll(/setTool[^\n]*/g)].map((m) => m[0]);
    if (tools.length !== 1 || !/^setTool\("probe"\);?$/.test(tools[0].trim())) out.push(`${ADAPTER}: setTool must appear once, as setTool("probe")`);
  }
  return out;
}

describe("read-only guard (scans all of src/)", () => {
  it("scans the files it means to", () => {
    const names = Object.keys(real);
    expect(names).toEqual(expect.arrayContaining([FACADE, ADAPTER, "api.ts", "App.tsx", "routes/DesignInsights.tsx", "components/project-scene/sceneController.ts"]));
    expect(names.some((n) => n.startsWith("vendor/"))).toBe(false);
    expect(names.some((n) => /\.test\.tsx?$/.test(n))).toBe(false);
    expect(names.length).toBeGreaterThan(60);
    expect(Object.keys(entry)).toHaveLength(1);
  });

  it("the real source tree is clean", () => {
    expect(scan(real)).toEqual([]);
  });

  it("the entry file re-exports the factory and types, nothing editing", () => {
    const text = code(Object.values(entry)[0]);
    expect(text).toMatch(/export \{ createViewport \}/);
    expect(text).not.toMatch(/gizmo|paint|cut|cadtools|rings|scaling|sketch|arrange|faces/i);
  });

  it("the facade's pass-through list names only inspection members", () => {
    const text = code(real[FACADE]);
    const block = /InspectionCalls\s*=\s*Pick<\s*Viewport,([\s\S]*?)>;/.exec(text)![1];
    const names = [...block.matchAll(/"(\w+)"/g)].map((m) => m[1]).sort();
    expect(names).toEqual([
      "dispose", "setBedAlert", "setGuides", "setOverhangAngle", "setPlate", "setRenderMode", "setSelection", "setTheme", "view", "zoomBy",
    ]);
  });

  it("the view's code writes no file and calls no desktop shell command", () => {
    const own = Object.entries(real).filter(([k]) => k.startsWith("components/project-scene/")).map(([, v]) => code(v)).join("\n");
    expect(own).not.toMatch(/@tauri-apps|from\s+["']@\/api["']|writeFile|createWritable|showSaveFilePicker|localStorage|indexedDB|XMLHttpRequest|\bfetch\(/);
  });
});

describe("the guard fails when a bypass is added (mutation tests)", () => {
  const base = real;
  const bypasses: [string, string, string][] = [
    ["a file in project-scene/sub/ imports the factory", "components/project-scene/sub/bypass.ts",
      'import { createViewport } from "@/vendor/slicerx/entry";\nexport const v = createViewport(document.createElement("canvas"));\nv.setTool("move");\n'],
    ["a route imports the vendor entry", "routes/Bypass.tsx",
      'import { createViewport as cv } from "@/vendor/slicerx/entry";\nexport default function B() { return cv ? null : null; }\n'],
    ["a route reaches into the viewport source by relative path", "routes/Bypass2.tsx",
      'import { CutGizmo } from "../vendor/slicerx/viewport/cutplane";\nexport const g = CutGizmo;\n'],
    ["a dynamic import of the vendor tree", "routes/Bypass3.tsx",
      'export const load = () => import("@/vendor/slicerx/viewport/viewport");\n'],
    ["a computed dynamic import", "lib/bypass.ts", 'const p = "@/ven" + "dor/slicerx/entry";\nexport const load = () => import(p);\n'],
    ["credits.ts importing more than its two text assets", "components/project-scene/credits.ts", 'import x from "@/vendor/slicerx/viewport/viewport?raw";\nexport const y = x;\n'],
    ["a re-export of the vendor entry", "lib/reexport.ts", 'export * from "@/vendor/slicerx/entry";\n'],
    ["bracket access to setTool", "lib/bracket.ts", 'export const f = (v: any) => v["setTool"]("select");\n'],
    ["destructuring an editing member", "lib/destructure.ts", "export const f = (v: any) => { const { setCutPlane } = v; return setCutPlane; };\n"],
    ["an editing member alias", "lib/alias.ts", "export const f = (v: any) => { const t = v.setTransforms; return t; };\n"],
    ["arrange", "lib/arr.ts", "export const f = (v: any) => v.arrange();\n"],
  ];
  for (const [label, path, source] of bypasses) {
    it(`fails when ${label}`, () => {
      const violations = scan({ ...base, [path]: source });
      expect(violations.length).toBeGreaterThan(0);
      expect(violations.join("\n")).toContain(path);
    });
  }

  it("fails when the facade value-imports the vendor entry", () => {
    const mutated = real[FACADE].replace('import type { Viewport } from "@/vendor/slicerx/entry";', 'import { Viewport } from "@/vendor/slicerx/entry";');
    expect(mutated).not.toBe(real[FACADE]);
    expect(scan({ ...base, [FACADE]: mutated }).join("\n")).toContain("value import");
  });

  it("fails when the adapter sets another tool, or the probe tool twice", () => {
    const other = real[ADAPTER].replace('raw.setTool("probe");', 'raw.setTool("select");');
    expect(scan({ ...base, [ADAPTER]: other }).join("\n")).toContain("setTool must appear once");
    const twice = real[ADAPTER].replace('raw.setTool("probe");', 'raw.setTool("probe");\n    raw.setTool("probe");');
    expect(scan({ ...base, [ADAPTER]: twice }).join("\n")).toContain("setTool must appear once");
  });

  it("fails when the adapter re-exports, aliases or calls createViewport again", () => {
    const base = real[ADAPTER];
    const variants = [
      `${base}
export { createViewport };
`,
      `${base}
export const make = createViewport;
`,
      `${base}
const alias = createViewport;
export const other = alias;
`,
      `${base}
export const second = (c: HTMLCanvasElement) => createViewport(c);
`,
    ];
    for (const mutated of variants) expect(scan({ ...real, [ADAPTER]: mutated }).join(" ; ")).toContain("createViewport must appear only");
  });

  it("fails when the adapter mentions an editing member other than the probe tool", () => {
    const extra = real[ADAPTER].replace("dispose: () => raw.dispose(),", "dispose: () => raw.dispose(),\n    setCutPlane: (c: never) => raw.setCutPlane(c),");
    expect(scan({ ...base, [ADAPTER]: extra }).join("\n")).toContain("setCutPlane");
  });
});
