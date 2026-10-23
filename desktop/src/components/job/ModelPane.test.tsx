// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import bambu from "@/test-fixtures/paintedPreview.bambu-authored.json";
import type { PaintedPreview } from "@/lib/paintedPreview";

vi.mock("@/api", () => ({ paintedPreview: vi.fn() }));
vi.mock("@/components/job/PlateView", () => ({ PlateView: () => <div data-testid="plate-view" /> }));
vi.mock("@/components/PlacementCard", () => ({ usePlacement: () => ({}) }));

// The renderer needs a graphics context jsdom does not have. These tests stand in for it where they are about the
// pane, and use the real one (below) where they are about what happens when graphics are missing.
const viewer = vi.hoisted(() => ({ latest: null as null | Record<string, any>, lose: null as null | string, real: false }));
vi.mock("@/components/job/ModelViewer", async () => {
  const actual = await vi.importActual<typeof import("@/components/job/ModelViewer")>("@/components/job/ModelViewer");
  return {
    default: (p: any) => {
      if (viewer.real) return React.createElement(actual.default, p);
      viewer.latest = p;
      React.useEffect(() => { if (viewer.lose) p.onLost(viewer.lose); }, []);
      return React.createElement("div", { "data-testid": "viewer-stub", "data-highlight": String(p.highlightSlot) });
    },
  };
});

import { ModelPane } from "@/components/job/ModelPane";

const real = bambu as unknown as PaintedPreview;
const tri = btoa(String.fromCharCode(...new Uint8Array(new Float32Array([0, 0, 0, 10, 0, 0, 0, 10, 0]).buffer)));
const colours = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF"];

function preview(over: Partial<PaintedPreview> = {}, slots = 3): PaintedPreview {
  return {
    schema: "paintedpreview/1", available: true, state: "ok", reason: null, kind: "painted", bed: null,
    slots: Array.from({ length: slots }, (_, i) => ({
      slot: i + 1, colour: colours[i], declared: true, from_painting: true, from_assignment: false,
      painted_triangles: 1, area_mm2: 10, painted_area_mm2: 10,
    })),
    unknown_default: false,
    meshes: [{ key: "m#1", parts: Array.from({ length: slots }, (_, i) => ({ slot: i + 1, triangles: 1, positions_f32le_base64: tri })) }],
    instances: [{ id: "n1", mesh: "m#1", world_mm: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], label: "Object 1", instance_index: 0, instance_count: 1 }],
    counts: { triangles_out: slots, painted_triangles: slots, leaves: slots, malformed: 0 },
    notes: ["base note", "another note"], ...over,
  };
}

const placement = {} as any;
function pane(over: Partial<React.ComponentProps<typeof ModelPane>> & { fetcher: any }) {
  return <ModelPane path="C:\\work\\a.3mf" selections={[]} preparedPath={null} placement={placement} {...over} />;
}
const flush = async () => { await act(async () => { await Promise.resolve(); await Promise.resolve(); }); };
const pick = (slot: number | null) => viewer.latest!.colourFor(slot) as string;

beforeEach(() => { viewer.latest = null; viewer.lose = null; viewer.real = false; });
afterEach(cleanup);

describe("ModelPane", () => {
  it("says it is building while the preview loads, and then shows the viewer and the legend", async () => {
    let done!: (p: PaintedPreview) => void;
    render(pane({ fetcher: () => new Promise((r) => { done = r; }) }));
    expect(screen.getByText(/Building the colour preview/)).toBeTruthy();
    await act(async () => { done(preview()); });
    expect(await screen.findByTestId("viewer-stub")).toBeTruthy();
    expect(within(screen.getByTestId("legend")).getAllByRole("button").map((b) => b.getAttribute("data-slot"))).toEqual(["1", "2", "3"]);
  });

  it("links each slot to its toolhead and shows the project's own colour", async () => {
    render(pane({ fetcher: async () => real }));
    await screen.findByTestId("viewer-stub");
    const row = within(screen.getByTestId("legend")).getAllByRole("button")[1];
    expect(row.getAttribute("aria-label")).toMatch(/^Toolhead 2: #FFFF00, /);
    expect([1, 2, 3].map(pick)).toEqual(["#00AE42", "#FFFF00", "#FF0000"]);
  });

  it("Original and Your choices differ only in the slots chosen, and the comparison is off until there is one", async () => {
    const fetcher = async () => preview();
    const { rerender } = render(pane({ fetcher }));
    await screen.findByTestId("viewer-stub");
    const proposed = () => screen.getByRole("button", { name: "Your choices" }) as HTMLButtonElement;
    expect(proposed().disabled).toBe(true);
    rerender(pane({ fetcher, selections: [{ slot: 1, colour: "#112233" }] }));
    expect(proposed().disabled).toBe(false);
    fireEvent.click(proposed());
    expect([1, 2, 3].map(pick)).toEqual(["#FF0000", "#112233", "#0000FF"]);
    fireEvent.click(screen.getByRole("button", { name: "Original" }));
    expect([1, 2, 3].map(pick)).toEqual(["#FF0000", "#00FF00", "#0000FF"]);
    // The choice is withdrawn: the comparison goes with it rather than showing a stale one.
    fireEvent.click(proposed());
    rerender(pane({ fetcher, selections: [] }));
    expect(screen.getByRole("button", { name: "Original" }).getAttribute("aria-pressed")).toBe("true");
    expect([1, 2, 3].map(pick)).toEqual(["#FF0000", "#00FF00", "#0000FF"]);
  });

  it("the U1 copy view shows the colours read back from the written file", async () => {
    const written = preview();
    written.slots[0].colour = "#ABCDEF";
    const fetcher = vi.fn(async (p: string) => (p.endsWith("_U1.3mf") ? written : preview()));
    render(pane({ fetcher, preparedPath: "C:\\work\\a_U1.3mf" }));
    await screen.findByTestId("viewer-stub");
    fireEvent.click(await screen.findByRole("button", { name: "U1 copy" }));
    expect([1, 2, 3].map(pick)).toEqual(["#ABCDEF", "#00FF00", "#0000FF"]);
    expect(fetcher).toHaveBeenCalledWith("C:\\work\\a_U1.3mf");
  });

  it("the U1 copy view is unavailable when the written file cannot be read back", async () => {
    const fetcher = vi.fn(async (p: string) => { if (p.endsWith("_U1.3mf")) throw new Error("gone"); return preview(); });
    render(pane({ fetcher, preparedPath: "C:\\work\\a_U1.3mf" }));
    await screen.findByTestId("viewer-stub");
    expect((screen.getByRole("button", { name: "U1 copy" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("more than four colours stay visible, each in its own colour, with an explicit note and no silent merge", async () => {
    render(pane({ fetcher: async () => preview({}, 5) }));
    await screen.findByTestId("viewer-stub");
    const rows = within(screen.getByTestId("legend")).getAllByRole("button");
    expect(rows).toHaveLength(5);
    expect(rows[4].getAttribute("aria-label")).toMatch(/^Slot 5, no toolhead: #FF00FF/);
    expect(pick(5)).toBe("#FF00FF");
    const note = screen.getByTestId("beyond-heads").textContent!;
    expect(note).toMatch(/Slot 5 has no toolhead/);
    expect(note).toMatch(/does not remove or merge colours/);
  });

  it("surface the project does not assign is grey and explained, not credited to a filament", async () => {
    render(pane({ fetcher: async () => preview({ unknown_default: true }) }));
    await screen.findByTestId("viewer-stub");
    expect(pick(null).toUpperCase()).toBe("#9AA0A6");
    expect(screen.getByTestId("unknown-default").textContent).toMatch(/does not say which filament/);
  });

  it("a geometry-only file is labelled as shape only and not as painted coverage", async () => {
    render(pane({ fetcher: async () => preview({ kind: "geometry", slots: [], unknown_default: true }, 0) }));
    await screen.findByTestId("viewer-stub");
    fireEvent.click(screen.getByText("About this preview"));
    expect(screen.getByTestId("coverage-note").textContent).toMatch(/Shape only/);
    expect(screen.getByTestId("coverage-note").textContent).toMatch(/no painted coverage to check/);
    expect(screen.queryByTestId("legend")).toBeNull();
    expect(screen.getByTestId("shape-only").textContent).toMatch(/Shape only/);
  });

  it("lists every placed instance so repeated objects are told apart", async () => {
    const p = preview();
    p.instances = [0, 1].map((i) => ({ ...p.instances[0], id: `n${i}`, label: `Object 1 · instance ${i + 1} of 2`, instance_index: i, instance_count: 2 }));
    render(pane({ fetcher: async () => p }));
    await screen.findByTestId("viewer-stub");
    expect(screen.getByTestId("preview-notes").textContent).toContain("2 objects placed: Object 1 · instance 1 of 2; Object 1 · instance 2 of 2");
  });

  it("keeps surface percentages out of the default legend and says what they count in a details section", async () => {
    render(pane({ fetcher: async () => preview({ unknown_default: true }, 5) }));
    await screen.findByTestId("viewer-stub");
    const legend = screen.getByTestId("legend");
    const details = within(legend).getByTestId("legend-shares") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    // no percentage anywhere in the legend outside the details
    const outside = legend.cloneNode(true) as HTMLElement;
    outside.querySelector("[data-testid=legend-shares]")!.remove();
    expect(outside.textContent).not.toMatch(/%/);
    for (const b of within(legend).getAllByRole("button")) expect(b.getAttribute("aria-label")).not.toMatch(/%/);
    // inside: the figures, with the scope in full
    expect(details.textContent).toMatch(/%/);
    const scope = within(details).getByTestId("legend-shares-scope").textContent!;
    expect(scope).toMatch(/one copy of each mesh/);
    expect(scope).toMatch(/only the surface that has a stated filament/);
    expect(scope).toMatch(/Grey \(unassigned\) surface is left out/);
    expect(scope).toMatch(/not an amount of filament/);
    // the warnings are not folded away
    expect(screen.getByTestId("beyond-heads")).toBeTruthy();
    expect(screen.getByTestId("unknown-default")).toBeTruthy();
    expect(details.contains(screen.getByTestId("beyond-heads"))).toBe(false);
  });

  it("hovering or focusing a legend row highlights that slot, and leaving clears it", async () => {
    render(pane({ fetcher: async () => preview() }));
    const stub = await screen.findByTestId("viewer-stub");
    const row = within(screen.getByTestId("legend")).getAllByRole("button")[2];
    fireEvent.focus(row);
    expect(stub.getAttribute("data-highlight")).toBe("3");
    fireEvent.blur(row);
    expect(stub.getAttribute("data-highlight")).toBe("null");
    fireEvent.mouseEnter(row);
    expect(stub.getAttribute("data-highlight")).toBe("3");
  });

  it.each([
    ["limit", "This project is too detailed to preview in full."],
    ["unsupported", "This project is not in millimetres."],
  ] as const)("a %s answer shows its plain reason and the plate instead of a drawing", async (state, reason) => {
    render(pane({ fetcher: async () => preview({ available: false, state, reason, slots: [], meshes: [], instances: [] }, 0) }));
    expect((await screen.findByTestId("preview-unavailable")).textContent).toContain(reason);
    expect(screen.getByTestId("plate-view")).toBeTruthy();
    expect(screen.queryByTestId("viewer-stub")).toBeNull();
    expect(screen.queryByTestId("legend")).toBeNull();
  });

  it("an unreadable preview of a file the screen already calls unreadable is not told again, but any other unreadable reason is", async () => {
    const changed = preview({ available: false, state: "unreadable", reason: "The file changed while Studio was reading it. Open it again.", slots: [], meshes: [], instances: [] }, 0);
    render(pane({ fetcher: async () => changed }));
    expect((await screen.findByTestId("preview-unavailable")).textContent).toContain("Open it again");
    cleanup();
    render(pane({ fileUnreadable: true, fetcher: async () => preview({ available: false, state: "unreadable", reason: "Studio could not read this file.", slots: [], meshes: [], instances: [] }, 0) }));
    expect(await screen.findByTestId("plate-view")).toBeTruthy();
    expect(screen.queryByTestId("preview-unavailable")).toBeNull();
  });

  it("when the copy goes away (a new Prepare starts) its colours are no longer shown", async () => {
    const written = preview(); written.slots[0].colour = "#ABCDEF";
    const fetcher = async (p: string) => (p.endsWith("_U1.3mf") ? written : preview());
    const { rerender } = render(pane({ fetcher, preparedPath: "C:\work\a_U1.3mf" }));
    await screen.findByTestId("viewer-stub");
    fireEvent.click(await screen.findByRole("button", { name: "U1 copy" }));
    expect(pick(1)).toBe("#ABCDEF");
    rerender(pane({ fetcher, preparedPath: null }));
    expect(pick(1)).toBe("#FF0000");                                   // back to the project's own colour
    expect(screen.queryByRole("button", { name: "U1 copy" })).toBeNull();
    // A second copy later does not resurrect the first one's colours before its own answer is in.
    let hang = false;
    const slow = (p: string) => (hang && p.endsWith("_U1.3mf") ? new Promise<PaintedPreview>(() => {}) : fetcher(p));
    rerender(pane({ fetcher: slow, preparedPath: null }));
    await flush();
    hang = true;
    rerender(pane({ fetcher: slow, preparedPath: "C:\work\a_U1.3mf" }));
    expect((screen.getByRole("button", { name: "U1 copy" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("counts objects, not meshes: a three-part object is one object", async () => {
    const p = preview();
    p.instances = [0, 1, 2].map((i) => ({ ...p.instances[0], id: `m${i}`, object_node: "top1", label: "Object 5" }));
    render(pane({ fetcher: async () => p }));
    await screen.findByTestId("viewer-stub");
    expect(screen.getByTestId("preview-notes").textContent).toContain("1 object placed.");
  });

  it("a failed request is a calm sentence and the plate, never a stack or an error code", async () => {
    render(pane({ fetcher: async () => { throw new Error("preview failed (500)"); } }));
    const msg = (await screen.findByTestId("preview-unavailable")).textContent!;
    expect(msg).toMatch(/could not build the colour preview/);
    expect(msg).not.toMatch(/500|Error/);
    expect(screen.getByTestId("plate-view")).toBeTruthy();
  });

  it("when graphics are lost the drawing is replaced by the plate, with the reason", async () => {
    viewer.lose = "context-lost";
    render(pane({ fetcher: async () => preview() }));
    expect((await screen.findByTestId("preview-unavailable")).textContent).toMatch(/graphics were interrupted/);
    expect(screen.getByTestId("plate-view")).toBeTruthy();
    expect(screen.queryByTestId("legend")).toBeNull();
  });

  it("with no 3D graphics at all (the real viewer in a context without WebGL) it falls back the same way", async () => {
    viewer.real = true;
    render(pane({ fetcher: async () => preview() }));
    expect((await screen.findByTestId("preview-unavailable", {}, { timeout: 3000 })).textContent).toMatch(/could not start 3D graphics/);
    expect(screen.getByTestId("plate-view")).toBeTruthy();
  });

  it("a late answer for the previous project never replaces the current one", async () => {
    const answers = new Map<string, (p: PaintedPreview) => void>();
    const fetcher = (p: string) => new Promise<PaintedPreview>((r) => { answers.set(p, r); });
    const { rerender } = render(pane({ fetcher, path: "C:\\a.3mf" }));
    rerender(pane({ fetcher, path: "C:\\b.3mf" }));
    await act(async () => { answers.get("C:\\b.3mf")!(preview({}, 2)); });
    await screen.findByTestId("viewer-stub");
    await act(async () => { answers.get("C:\\a.3mf")!(preview({}, 3)); });
    expect(within(screen.getByTestId("legend")).getAllByRole("button")).toHaveLength(2);
  });

  it("the plate fit stays one click away and Reset view is a real control", async () => {
    render(pane({ fetcher: async () => preview() }));
    await screen.findByTestId("viewer-stub");
    expect(screen.getByRole("button", { name: /Reset view/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Plate fit" }));
    expect(screen.getByTestId("plate-view")).toBeTruthy();
    expect(screen.queryByTestId("viewer-stub")).toBeNull();
  });
});
