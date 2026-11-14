import { beforeEach, describe, expect, it, vi } from "vitest";

// The vendored viewport is replaced by a stand-in that records what is created and what is called. This file proves what
// the real adapter (defaultViewport.ts) does with it: tool fixed to probe, clean-up when start-up fails half way.
const fake = vi.hoisted(() => ({
  log: [] as string[], live: 0, failOn: null as null | string, failCreate: false,
  handlers: new Map<string, Set<(p: never) => void>>(),
}));

vi.mock("@/vendor/slicerx/entry", () => ({
  createViewport: () => {
    if (fake.failCreate) throw new Error("no webgl");
    fake.live++;
    fake.log.push("create");
    const guard = (name: string) => { if (fake.failOn === name) throw new Error(`${name} failed`); };
    const rec = (name: string) => (..._a: unknown[]) => { fake.log.push(name); guard(name); };
    return {
      setTool: rec("setTool"), setTheme: rec("setTheme"), setPlate: rec("setPlate"), setSelection: rec("setSelection"),
      view: rec("view"), zoomBy: rec("zoomBy"), setRenderMode: rec("setRenderMode"), setOverhangAngle: rec("setOverhangAngle"),
      setGuides: rec("setGuides"), setBedAlert: rec("setBedAlert"),
      on: (event: string, cb: (p: never) => void) => {
        guard(`on:${event}`);
        let set = fake.handlers.get(event);
        if (!set) fake.handlers.set(event, (set = new Set()));
        set.add(cb);
        fake.log.push(`on:${event}`);
        return () => { set!.delete(cb); };
      },
      dispose: () => { fake.live--; fake.log.push("dispose"); },
    };
  },
}));

import { createSceneViewer } from "./defaultViewport";
import { ViewerUnavailableError } from "./readOnlyViewport";

const canvas = {} as HTMLCanvasElement;
const listeners = () => [...fake.handlers.values()].reduce((n, s) => n + s.size, 0);

beforeEach(() => { fake.log.length = 0; fake.live = 0; fake.failOn = null; fake.failCreate = false; fake.handlers.clear(); });

describe("createSceneViewer (the only adapter to the vendored viewport)", () => {
  it("sets the tool to probe exactly once, before anything else is called, and hands out no setTool", () => {
    const viewer = createSceneViewer(canvas, { theme: "dark" });
    expect(fake.log.filter((l) => l === "setTool")).toHaveLength(1);
    expect(fake.log.indexOf("setTool")).toBe(1);
    expect(Object.keys(viewer)).not.toContain("setTool");
    expect(Object.keys(viewer)).not.toContain("on");
    viewer.dispose();
    expect(fake.live).toBe(0);
  });

  it("reports unavailable graphics when the viewport cannot be created", () => {
    fake.failCreate = true;
    expect(() => createSceneViewer(canvas, { theme: "dark" })).toThrow(ViewerUnavailableError);
    expect(fake.live).toBe(0);
  });

  it.each(["setTool", "setTheme", "on:pick", "on:select", "on:error", "on:degrade"])(
    "disposes the partly built viewport when %s throws after it was created",
    (name) => {
      fake.failOn = name;
      expect(() => createSceneViewer(canvas, { theme: "light" })).toThrow();
      expect(fake.log).toContain("create");
      expect(fake.log.filter((l) => l === "dispose")).toHaveLength(1);
      expect(fake.live).toBe(0);
    },
  );

  it("leaves no registered viewport listener behind after a normal dispose", () => {
    const viewer = createSceneViewer(canvas, { theme: "dark" });
    expect(listeners()).toBe(4);
    viewer.dispose();
    expect(listeners()).toBe(0);
  });
});
