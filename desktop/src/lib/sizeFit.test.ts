import { describe, expect, it } from "vitest";
import type { ObjectSize } from "@/api";
import { UNMEASURED, sizeRow } from "./sizeFit";

const BED = { x: 270, y: 270, z: 270 };
const obj = (id: string, x: number, y = x, z = x): ObjectSize => ({
  object_id: id,
  instance_count: 1,
  dimensions_mm: { x, y, z },
});

describe("sizeRow", () => {
  it("says it is a size statement and that position is a separate check", () => {
    const row = sizeRow([obj("1", 30)], { x: 30, y: 30, z: 30 }, BED, "the U1’s");
    expect(row?.level).toBe("ok");
    expect(row?.detail.startsWith("By size, ")).toBe(true);
    expect(row?.detail).toContain("Size only: where it sits on the plate is a separate check.");
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

  it("keeps an unknown size unknown and never falls back to the combined extents", () => {
    for (const overall of [{ x: 300, y: 10, z: 10 }, { x: 20, y: 20, z: 20 }]) {
      const row = sizeRow([], overall, BED, "your connected U1");
      expect(row).toEqual({ level: "warn", status: "Unknown", detail: UNMEASURED });
    }
    expect(sizeRow(undefined, { x: 520, y: 20, z: 20 }, BED, "x")?.detail).not.toMatch(/scale|split|fit /);
    expect(sizeRow(undefined, null, BED, "x")).toBeNull();
  });

  it("does not say everything fits while some build items could not be measured", () => {
    const row = sizeRow([obj("1", 30)], null, BED, "the U1’s", 2);
    expect(row?.level).toBe("warn");
    expect(row?.status).toBe("Check");
    expect(row?.detail).toContain("2 build items could not be measured");
  });
});
