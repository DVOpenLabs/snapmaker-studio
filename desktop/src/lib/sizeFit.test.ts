import { describe, expect, it } from "vitest";
import type { ObjectSize } from "@/api";
import { sizeRow } from "./sizeFit";

const BED = { x: 270, y: 270, z: 270 };
const obj = (id: string, x: number, y = x, z = x): ObjectSize => ({
  object_id: id,
  instance_count: 1,
  dimensions_mm: { x, y, z },
});

describe("sizeRow", () => {
  it("says it is a size statement and points at placement for position", () => {
    const row = sizeRow([obj("1", 30)], { x: 30, y: 30, z: 30 }, BED, "the U1’s");
    expect(row?.level).toBe("ok");
    expect(row?.detail.startsWith("By size, ")).toBe(true);
    expect(row?.detail).toContain("Where it sits on the plate is checked separately");
  });

  it("judges each object, not the combined extents of separated ones", () => {
    // the overall extents (520 mm) are not an object's size
    const row = sizeRow([obj("1", 20), obj("2", 20)], { x: 520, y: 20, z: 20 }, BED, "the U1’s");
    expect(row?.level).toBe("ok");
    expect(row?.detail).toContain("each of the 2 objects fits");
    expect(row?.detail).not.toMatch(/scale|split/);
  });

  it("names the object that is too big", () => {
    const row = sizeRow([obj("1", 20), obj("2", 300, 20, 20)], null, BED, "the U1’s");
    expect(row?.level).toBe("risk");
    expect(row?.detail).toContain("By size, object 2 (300 × 20 × 20 mm) is larger than");
  });

  it("falls back to the overall extents and says so", () => {
    const row = sizeRow([], { x: 300, y: 10, z: 10 }, BED, "your connected U1");
    expect(row?.level).toBe("risk");
    expect(row?.detail).toContain("By size, the overall extents");
    expect(sizeRow(undefined, null, BED, "x")).toBeNull();
  });
});
