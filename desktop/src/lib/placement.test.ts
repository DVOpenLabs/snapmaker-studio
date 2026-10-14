import { describe, expect, it } from "vitest";
import type { PlacementCheck, PlacementItem } from "@/api";
import { blockedReason, overhangText, placementVerdict } from "./placement";

const item = (over: Partial<PlacementItem["overhang_mm"]> = {}): PlacementItem => ({
  object_id: "1",
  dimensions: { x: 10, y: 10, z: 10 },
  position: { x: 300, y: 100 },
  off_plate: true,
  overhang_mm: { left: 0, right: 0, front: 0, back: 0, ...over },
  edges: null,
});

const check = (over: Partial<PlacementCheck> = {}): PlacementCheck => ({
  schema_version: "placement/1",
  available: true,
  items: [],
  off_plate: [],
  fixable: false,
  item_count: 1,
  ...over,
});

describe("placementVerdict", () => {
  it("waits rather than claiming anything before the check returns", () => {
    expect(placementVerdict(null).tone).toBe("unknown");
    expect(placementVerdict(null).canFix).toBe(false);
  });

  it("passes an on-plate project", () => {
    const v = placementVerdict(check());
    expect(v.tone).toBe("ok");
    expect(v.canFix).toBe(false);
  });

  it("uses plural wording for a multi-object plate", () => {
    expect(placementVerdict(check({ item_count: 3 })).headline).toContain("Every object");
  });

  it("warns and offers the fix when one move solves it", () => {
    const v = placementVerdict(check({ off_plate: [item({ right: 30 })], fixable: true }));
    expect(v.tone).toBe("warn");
    expect(v.canFix).toBe(true);
    expect(v.headline).toContain("1 object is");
  });

  it("blocks the fix when Studio will not move things", () => {
    const v = placementVerdict(check({ off_plate: [item({ right: 30 })], fixable: false }));
    expect(v.tone).toBe("blocked");
    expect(v.canFix).toBe(false);
  });

  it("counts several off-plate objects with plural wording", () => {
    const v = placementVerdict(check({
      off_plate: [item({ right: 5 }), item({ left: 5 })], fixable: true,
    }));
    expect(v.headline).toContain("2 objects are");
  });

  it("reports an unreadable project with the engine's own reason", () => {
    const v = placementVerdict(check({ available: false, reason: "Could not open that file." }));
    expect(v.tone).toBe("unknown");
    expect(v.headline).toBe("Could not open that file.");
    expect(v.canFix).toBe(false);
  });
});

describe("overhangText", () => {
  it("names one edge", () => {
    expect(overhangText(item({ right: 12.5 }))).toBe("Hangs 12.5 mm past the right edge.");
  });

  it("joins two edges readably", () => {
    expect(overhangText(item({ left: 3, front: 4 })))
      .toBe("Hangs 3.0 mm past the left edge and 4.0 mm past the front edge.");
  });

  it("says nothing alarming when the object is on the plate", () => {
    expect(overhangText(item())).toBe("On the plate.");
  });
});

describe("blockedReason", () => {
  it("is silent when there is nothing to explain", () => {
    expect(blockedReason(check())).toBeNull();
    expect(blockedReason(check({ off_plate: [item()], fixable: true }))).toBeNull();
    expect(blockedReason(null)).toBeNull();
  });

  it("explains an object that belongs to no plate", () => {
    const reason = blockedReason(check({
      off_plate: [item()], fixable: false, unresolved_objects: [{ object_id: "3" }],
    }));
    expect(reason).toContain("not listed on any plate");
  });

  it("explains an all-or-nothing plate refusal", () => {
    const reason = blockedReason(check({
      off_plate: [item()], fixable: false,
      skipped_plates: [{ plate: 2, reason: "too big" }],
    }));
    expect(reason).toContain("every plate or none");
  });

  it("falls back to the single-move explanation", () => {
    expect(blockedReason(check({ off_plate: [item()], fixable: false })))
      .toContain("will not guess");
  });
});

describe("placementVerdict for several plates", () => {
  it("is unverified, not ok, and offers no fix when every plate fits on its own", () => {
    const v = placementVerdict(check({ plate_count: 2, item_count: 2 }));
    expect(v.tone).toBe("unverified");
    expect(v.canFix).toBe(false);
    expect(v.headline).toContain("Studio cannot check where the plates sit");
    expect(v.headline).not.toMatch(/inside/i);
  });

  it("still reports an oversized plate as outside", () => {
    expect(placementVerdict(check({ plate_count: 2, off_plate: [item()] })).tone).toBe("blocked");
  });
});
