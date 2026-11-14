import { describe, expect, it } from "vitest";
import type { PlacementCheck, PlacementItem } from "@/api";
import { plateModel } from "@/lib/plateView";

const item = (over: Partial<PlacementItem> = {}): PlacementItem => ({
  object_id: "2", item_index: 0, instance_index: 0, instance_count: 1,
  bounds_mm: { min: [10, 20, 0], max: [60, 50, 8] },
  dimensions: { x: 50, y: 30, z: 8 }, position: { x: 35, y: 35 }, off_plate: false,
  overhang_mm: { left: 0, right: 0, front: 0, back: 0 }, edges: null, ...over,
});
const check = (over: Partial<PlacementCheck> = {}): PlacementCheck => ({
  schema_version: "placement/1", available: true, plate_count: 1, placement_established: true,
  bed: { min_x: 0.5, min_y: 1, max_x: 270.5, max_y: 271 }, item_count: 1, items: [item()], off_plate: [], fixable: false, ...over,
});

describe("plate drawing", () => {
  it("waits for the check", () => expect(plateModel(null).kind).toBe("loading"));

  it("draws established single-plate footprints relative to the bed", () => {
    const m = plateModel(check());
    expect(m.kind).toBe("drawn");
    if (m.kind !== "drawn") return;
    expect(m).toMatchObject({ width: 270, depth: 270 });
    expect(m.rects[0]).toMatchObject({ x: 9.5, y: 19, w: 50, h: 30, off: false });
  });

  it("marks an off-plate instance", () => {
    const m = plateModel(check({ items: [item({ off_plate: true })] }));
    expect(m.kind === "drawn" && m.rects[0].off).toBe(true);
  });

  it("tells repeated instances apart", () => {
    const m = plateModel(check({ item_count: 2, items: [
      item({ item_index: 0, instance_index: 0, instance_count: 2 }),
      item({ item_index: 1, instance_index: 1, instance_count: 2, bounds_mm: { min: [100, 20, 0], max: [150, 50, 8] } }),
    ] }));
    expect(m.kind === "drawn" && m.rects.map((r) => r.label)).toEqual(["Object 2 · instance 1 of 2", "Object 2 · instance 2 of 2"]);
    expect(m.kind === "drawn" && new Set(m.rects.map((r) => r.key)).size).toBe(2);
  });

  it("never draws a multi-plate project", () => {
    expect(plateModel(check({ plate_count: 2, placement_established: false })).kind).toBe("none");
    expect(plateModel(check({ plate_count: 2 })).kind).toBe("none");
    expect(plateModel(check({ placement_established: false })).kind).toBe("none");
  });

  it("does not draw when an instance could not be judged", () => {
    expect(plateModel(check({ not_judged: 1 })).kind).toBe("none");
  });

  it("does not draw an unavailable check, a missing bed, or a missing extent", () => {
    expect(plateModel(check({ available: false, reason: "No project settings." }))).toEqual({ kind: "none", reason: "No project settings." });
    expect(plateModel(check({ bed: undefined })).kind).toBe("none");
    expect(plateModel(check({ items: [item({ bounds_mm: undefined })] })).kind).toBe("none");
    expect(plateModel(check({ items: [item({ bounds_mm: { min: [Number.NaN, 0, 0], max: [1, 1, 1] } })] })).kind).toBe("none");
  });
});
