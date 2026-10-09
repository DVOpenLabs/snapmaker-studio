/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";

// Source scan: the vendored viewport still contains editing code (move, rotate, scale, paint, cut, sketch) because its
// own entry class imports it. These checks prove Studio's code cannot reach any of it.
const own = import.meta.glob(["./*.ts", "./*.tsx", "!./*.test.ts", "!./*.test.tsx", "!./fakeViewport.ts", "!./sceneFixtures.ts"], {
  query: "?raw", import: "default", eager: true,
}) as Record<string, string>;
const entry = import.meta.glob("../../vendor/slicerx/entry.ts", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

describe("read-only guard", () => {
  it("scans the files it means to", () => {
    expect(Object.keys(own).sort()).toEqual([
      "./ProjectScenePanel.tsx", "./ProjectSceneSection.tsx", "./defaultViewport.ts", "./readOnlyViewport.ts",
      "./sceneController.ts", "./sceneModel.ts",
    ]);
    expect(Object.keys(entry)).toHaveLength(1);
  });

  it("imports the vendored viewport only through its entry file, and as a value only in defaultViewport.ts", () => {
    for (const [file, raw] of Object.entries(own)) {
      for (const m of code(raw).matchAll(/from\s+["']([^"']*vendor[^"']*)["']/g)) {
        expect(m[1], file).toBe("@/vendor/slicerx/entry");
      }
      const valueImport = /^import\s+(?!type\b)[^;]*from\s+["']@\/vendor\/slicerx\/entry["']/m.test(code(raw));
      expect(valueImport, file).toBe(file === "./defaultViewport.ts");
    }
  });

  it("the entry file re-exports the factory and types, nothing editing", () => {
    const text = code(Object.values(entry)[0]);
    expect(text).toMatch(/export \{ createViewport \}/);
    expect(text).not.toMatch(/gizmo|paint|cut|cadtools|rings|scaling|sketch|arrange|faces/i);
  });

  it("only ever sets the probe tool and never listens for edit events", () => {
    const all = Object.values(own).map(code).join("\n");
    const tools = [...all.matchAll(/setTool\(([^)]*)\)/g)].map((m) => m[1]);
    expect(tools).toEqual(['"probe"']);
    expect(all).not.toMatch(/\.on\(\s*["'](transform|rotate|scale|paintstroke|paintsettings|cutplane|cutconnector|push|sketch|brim\w*)["']/);
    expect(all).not.toMatch(/setTransforms|setPaint|applyPaintEdits|setCutPlane|setPush|setSketch|arrange\(|setBrimEars|setDimensions|setPartStyle|setProbeHover/);
  });

  it("the facade's viewport subset names only inspection members", () => {
    const text = code(own["./readOnlyViewport.ts"]);
    const block = /Pick<\s*Viewport,([\s\S]*?)>;/.exec(text)![1];
    const names = [...block.matchAll(/"(\w+)"/g)].map((m) => m[1]).sort();
    expect(names).toEqual([
      "canvas", "dispose", "on", "setBedAlert", "setDisplayStyle", "setGuides", "setOverhangAngle", "setPlate", "setRenderMode",
      "setSelection", "setTheme", "setTool", "view", "zoomBy",
    ]);
  });

  it("writes no file and calls no desktop shell command", () => {
    const all = Object.values(own).map(code).join("\n");
    expect(all).not.toMatch(/@tauri-apps|from\s+["']@\/api["']|writeFile|createWritable|showSaveFilePicker|localStorage|indexedDB|XMLHttpRequest|\bfetch\(/);
  });
});
