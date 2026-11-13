import { afterEach, describe, expect, it, vi } from "vitest";
// @ts-expect-error Node builtin is used at runtime; this checkout omits @types/node.
import * as fs from "node:fs";
import { __resetAppLifecycleForTests, installAppLifecycle, onAppStart, onBeforeUnload, onVisibilityChange } from "./extLifecycle";

afterEach(() => __resetAppLifecycleForTests());

describe("extension application lifecycle", () => {
  it("installs DOM listeners before start and replays a start-time subscriber once", () => {
    const fakeWindow = new EventTarget();
    const fakeDocument = Object.assign(new EventTarget(), { visibilityState: "visible" });
    const addWindowListener = vi.spyOn(fakeWindow, "addEventListener");
    const addDocumentListener = vi.spyOn(fakeDocument, "addEventListener");
    const late = vi.fn();
    const first = vi.fn(() => {
      expect(addWindowListener).toHaveBeenCalledWith("beforeunload", expect.any(Function));
      expect(addDocumentListener).toHaveBeenCalledWith("visibilitychange", expect.any(Function));
      onAppStart(late);
    });
    onAppStart(first);

    installAppLifecycle({ window: fakeWindow, document: fakeDocument });
    expect(first).toHaveBeenCalledTimes(1);
    expect(late).toHaveBeenCalledTimes(1);
    expect(addWindowListener).toHaveBeenCalledWith("beforeunload", expect.any(Function));
    expect(addDocumentListener).toHaveBeenCalledWith("visibilitychange", expect.any(Function));
  });

  it("isolates throwing subscribers and dispatches over a stable snapshot", () => {
    const fakeWindow = new EventTarget();
    const fakeDocument = Object.assign(new EventTarget(), { visibilityState: "hidden" });
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const startNext = vi.fn();
    onAppStart(() => { throw new Error("start"); });
    onAppStart(() => { onAppStart(startNext); });
    const before = vi.fn();
    const visibility = vi.fn();
    onBeforeUnload(() => { throw new Error("unload"); });
    onBeforeUnload(before);
    onVisibilityChange(() => { throw new Error("visibility"); });
    onVisibilityChange(visibility);

    installAppLifecycle({ window: fakeWindow, document: fakeDocument });
    expect(startNext).toHaveBeenCalledTimes(1);
    fakeWindow.dispatchEvent(new Event("beforeunload"));
    fakeDocument.dispatchEvent(new Event("visibilitychange"));
    expect(before).toHaveBeenCalledTimes(1);
    expect(visibility).toHaveBeenCalledWith(false);
    expect(error).toHaveBeenCalledTimes(3);
  });

  it("supports unsubscribe for lifecycle events", () => {
    const fakeWindow = new EventTarget();
    const fakeDocument = Object.assign(new EventTarget(), { visibilityState: "visible" });
    const before = vi.fn();
    const visibility = vi.fn();
    const stopBefore = onBeforeUnload(before);
    const stopVisibility = onVisibilityChange(visibility);
    installAppLifecycle({ window: fakeWindow, document: fakeDocument });
    stopBefore(); stopVisibility();
    fakeWindow.dispatchEvent(new Event("beforeunload"));
    fakeDocument.dispatchEvent(new Event("visibilitychange"));
    expect(before).not.toHaveBeenCalled();
    expect(visibility).not.toHaveBeenCalled();
  });

  it("installs application lifecycle exactly once from App.tsx", async () => {
    const source = fs.readFileSync(`${(globalThis as any).process.cwd()}/src/App.tsx`, "utf8");
    expect(source.match(/installAppLifecycle\s*\(/g)).toHaveLength(1);
  });
});
