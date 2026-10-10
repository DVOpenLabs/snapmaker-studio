// @vitest-environment jsdom
import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SceneError, type SceneV1 } from "@/lib/scene";
import { makeFakeFactory } from "./fakeViewport";
import { offBedScene, scene } from "./sceneFixtures";

const fake = vi.hoisted(() => ({ current: null as null | ReturnType<typeof import("./fakeViewport").makeFakeFactory> }));
const loader = vi.hoisted(() => ({ loadScene: vi.fn() }));
vi.mock("@/lib/scene", async (original) => ({ ...(await original<typeof import("@/lib/scene")>()), loadScene: loader.loadScene }));
vi.mock("./defaultViewport", () => ({
  createSceneViewer: (...args: Parameters<ReturnType<typeof makeFakeFactory>["factory"]>) => fake.current!.factory(...args),
}));

import ProjectScenePanel, { progressText } from "./ProjectScenePanel";

function resolveWith(s: SceneV1) {
  loader.loadScene.mockImplementation(async () => s);
}

beforeEach(() => {
  fake.current = makeFakeFactory();
  loader.loadScene.mockReset();
});
afterEach(() => cleanup());

describe("ProjectScenePanel", () => {
  it("lists objects as real buttons, shows the engine's note, and selecting an object selects it in the view", async () => {
    resolveWith(offBedScene());
    render(<ProjectScenePanel path="a.3mf" wide />);
    const second = await screen.findByRole("button", { name: /^Object 2/ });
    expect(second.getAttribute("aria-pressed")).toBe("false");
    expect(second.textContent).toContain("Placement note");
    fireEvent.click(second);
    expect(second.getAttribute("aria-pressed")).toBe("true");
    expect(fake.current!.stats.calls).toContain("setSelection:b1");
    expect(screen.getByText(/Placement: Object 2, right edge 4\.5 mm past the bed edge/)).toBeTruthy();
    fireEvent.click(second);
    expect(second.getAttribute("aria-pressed")).toBe("false");
  });

  it("camera buttons switch the view and the slope toggle shows the fixed label", async () => {
    resolveWith(scene());
    render(<ProjectScenePanel path="a.3mf" />);
    await screen.findByRole("button", { name: "Top" });
    fireEvent.click(screen.getByRole("button", { name: "Top" }));
    expect(fake.current!.stats.calls).toContain("view:top");
    const slope = screen.getByRole("button", { name: "Slope view" });
    expect(slope.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(slope);
    expect(slope.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Geometric slope visualization - review supports in Orca.")).toBeTruthy();
  });

  it("offers no editing control anywhere in the panel", async () => {
    resolveWith(offBedScene());
    render(<ProjectScenePanel path="a.3mf" wide />);
    await screen.findByRole("button", { name: "Top" });
    const names = screen.getAllByRole("button").map((b) => b.textContent ?? "").join("|");
    expect(names).not.toMatch(/move|rotate|scale|paint|cut|arrange|delete|remove|save|edit|sketch|extrude|lay on face/i);
    expect(document.querySelectorAll("input, select, textarea")).toHaveLength(0);
  });

  it("without WebGL keeps the object list and notes and offers Retry", async () => {
    let fail = true;
    fake.current = makeFakeFactory({ failCreate: () => fail });
    resolveWith(offBedScene());
    render(<ProjectScenePanel path="a.3mf" wide />);
    const retry = await screen.findByRole("button", { name: /Retry 3D view/ });
    expect(screen.getByRole("button", { name: /Object 1/ })).toBeTruthy();
    expect(screen.getByText(/Placement: Object 2/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Top" }) as HTMLButtonElement).disabled).toBe(true);
    fail = false;
    fireEvent.click(retry);
    await waitFor(() => expect(screen.queryByRole("button", { name: /Retry 3D view/ })).toBeNull());
    expect((screen.getByRole("button", { name: "Top" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows a lost graphics connection with Retry and a different canvas afterwards", async () => {
    resolveWith(scene());
    const { container } = render(<ProjectScenePanel path="a.3mf" />);
    await screen.findByRole("button", { name: "Top" });
    const first = container.querySelector("canvas");
    act(() => fake.current!.emit("error", { message: "lost" }));
    const retry = await screen.findByRole("button", { name: /Retry 3D view/ });
    expect(screen.getByText(/graphics connection was lost/)).toBeTruthy();
    expect(container.querySelectorAll("canvas")).toHaveLength(0);
    fireEvent.click(retry);
    await waitFor(() => expect(container.querySelector("canvas")).not.toBeNull());
    expect(container.querySelector("canvas")).not.toBe(first);
  });

  it("explains an engine refusal in plain words and Try again loads again", async () => {
    loader.loadScene.mockRejectedValueOnce(new SceneError("LIMIT_EXCEEDED"));
    render(<ProjectScenePanel path="a.3mf" />);
    expect((await screen.findByRole("alert")).textContent).toContain("larger than the 3D view can show");
    loader.loadScene.mockImplementation(async () => scene());
    fireEvent.click(screen.getByRole("button", { name: /Try again/ }));
    await screen.findByRole("button", { name: "Top" });
  });

  it("carries the SlicerX credit with its link and the license texts, and shows the legend only when highlighting is on", async () => {
    resolveWith(offBedScene());
    const { unmount } = render(<ProjectScenePanel path="a.3mf" wide />);
    await screen.findByRole("button", { name: "Top" });
    expect(screen.getByText(/^Made possible by SlicerX: https:\/\/slicerx\.app\/support$/)).toBeTruthy();
    expect(screen.getByRole("region", { name: "Apache License 2.0 (SlicerX viewport)" }).textContent).toContain("Apache License");
    expect(screen.getByRole("region", { name: "SlicerX notice (Apache-2.0)" }).textContent).toContain("Made possible by SlicerX");
    expect(screen.getByRole("region", { name: "three.js (MIT)" }).textContent).toContain("Copyright");
    expect(screen.getByText(/Studio keeps a 0\.5 mm margin/)).toBeTruthy();
    unmount();
    resolveWith(scene({ plates: [{ id: "1", ui_number: 1, origin_mm: null }, { id: "2", ui_number: 2, origin_mm: null }] }));
    render(<ProjectScenePanel path="b.3mf" wide />);
    await screen.findByRole("button", { name: "Top" });
    expect(screen.queryByText(/Studio keeps a 0\.5 mm margin/)).toBeNull();
  });

  it("shows a timeout in plain words with Try again instead of staying on the starting message", async () => {
    loader.loadScene.mockRejectedValueOnce(new SceneError("TIMEOUT"));
    render(<ProjectScenePanel path="a.3mf" />);
    expect((await screen.findByRole("alert")).textContent).toContain("took too long");
    expect(screen.queryByText("Starting the 3D view")).toBeNull();
    expect(screen.getByRole("button", { name: /Try again/ })).toBeTruthy();
  });

  it("shows the scene's limits in words when highlighting is off", async () => {
    const s = offBedScene();
    s.limitations = [{ code: "MULTI_PLATE_PLACEMENT_UNCHECKED", target_ids: [] }];
    s.plates.push({ id: "2", ui_number: 2, origin_mm: null });
    resolveWith(s);
    render(<ProjectScenePanel path="a.3mf" />);
    await screen.findByRole("button", { name: "Top" });
    expect(screen.getAllByText(/more than one plate/).length).toBeGreaterThan(0);
    expect(screen.queryByText("Placement note")).toBeNull();
  });

  it("works under StrictMode with exactly one live canvas, and unmount removes it", async () => {
    resolveWith(scene());
    const { container, unmount } = render(<StrictMode><ProjectScenePanel path="a.3mf" /></StrictMode>);
    await screen.findByRole("button", { name: "Top" });
    expect(container.querySelectorAll("canvas")).toHaveLength(1);
    expect(fake.current!.stats.liveContexts).toBe(1);
    unmount();
    expect(fake.current!.stats.liveContexts).toBe(0);
    expect(fake.current!.stats.liveListeners).toBe(0);
    expect(document.querySelectorAll("canvas")).toHaveLength(0);
  });

  it("changing the path loads the new project and drops the old canvas", async () => {
    resolveWith(scene());
    const { container, rerender } = render(<ProjectScenePanel path="a.3mf" />);
    await screen.findByRole("button", { name: "Top" });
    const first = container.querySelector("canvas");
    rerender(<ProjectScenePanel path="b.3mf" />);
    await waitFor(() => expect(container.querySelector("canvas")).not.toBe(first));
    expect(container.querySelectorAll("canvas")).toHaveLength(1);
    expect(loader.loadScene).toHaveBeenCalledTimes(2);
    expect(loader.loadScene.mock.calls.map((c) => c[0])).toEqual(["a.3mf", "b.3mf"]);
  });
});

describe("progressText", () => {
  it("speaks plainly", () => {
    expect(progressText(null)).toBe("Starting the 3D view");
    expect(progressText({ state: "queued", stage: null, completed: null, total: null })).toBe("Waiting for the engine");
    expect(progressText({ state: "running", stage: "parsing", completed: 1, total: 4 })).toBe("Reading the model (25%)");
    // Never 100%: at completed == total the figure is dropped, and a near-complete one stops at 99.
    expect(progressText({ state: "running", stage: "encoding", completed: 4, total: 4 })).toBe("Preparing the view");
    expect(progressText({ state: "running", stage: "encoding", completed: 999, total: 1000 })).toBe("Preparing the view (99%)");
  });
});
