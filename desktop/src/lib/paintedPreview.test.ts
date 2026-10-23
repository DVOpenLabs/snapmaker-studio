import { describe, expect, it } from "vitest";
import {
  NEUTRAL, beyondHeads, colourOf, coverageClaim, decodeFloat32, draftColours, legend, percent, unavailableCopy,
  type PaintedPreview, type PreviewSlot,
} from "@/lib/paintedPreview";

const slot = (n: number, colour: string | null, area = 10, painted = true): PreviewSlot => ({
  slot: n, colour, declared: colour !== null, from_painting: painted, from_assignment: !painted,
  painted_triangles: 1, area_mm2: area, painted_area_mm2: painted ? area : 0,
});

const preview = (slots: PreviewSlot[], over: Partial<PaintedPreview> = {}): PaintedPreview => ({
  schema: "paintedpreview/1", available: true, state: "ok", reason: null, kind: "painted", bed: null, slots,
  unknown_default: false, meshes: [], instances: [], counts: { triangles_out: 1, painted_triangles: 1, leaves: 1, malformed: 0 },
  notes: [], ...over,
});

describe("draftColours", () => {
  it("turns the 0-based selections Prepare is sent into 1-based slots", () => {
    expect(draftColours([{ slot: 1, colour: "#112233" }, { slot: 0, colour: null }])).toEqual({ 2: "#112233" });
  });
  it("ignores anything that is not a six-digit hex colour", () => {
    expect(draftColours([{ slot: 0, colour: "red" }, { slot: 1, colour: "#12" }])).toEqual({});
  });
});

describe("legend", () => {
  const p = preview([slot(1, "#ff0000"), slot(2, "#00ff00"), slot(5, null)]);

  it("links slot k to head k, and leaves slots beyond four without a head", () => {
    expect(legend(p, {}).map((r) => r.head)).toEqual([1, 2, null]);
    expect(beyondHeads(legend(p, {})).map((r) => r.slot)).toEqual([5]);
  });

  it("a slot past four that nothing prints in is listed as unused and does not raise the no-toolhead warning", () => {
    const unused = preview([slot(1, "#f00"), { ...slot(5, "#0f0", 0), painted_area_mm2: 0 }]);
    const rows = legend(unused, {});
    expect(rows[1].used).toBe(false);
    expect(beyondHeads(rows)).toEqual([]);
  });

  it("an unchosen slot is the same colour in Original and Proposed and is not marked changed", () => {
    const rows = legend(p, {});
    expect(rows.every((r) => r.proposed === r.original && !r.changed)).toBe(true);
  });

  it("a chosen colour changes Proposed for that slot only", () => {
    const rows = legend(p, { 2: "#0000FF" });
    expect(rows.map((r) => [r.original, r.proposed, r.changed])).toEqual([
      ["#FF0000", "#FF0000", false], ["#00FF00", "#0000FF", true], [null, null, false],
    ]);
  });

  it("choosing the colour a slot already has is not a change", () => {
    expect(legend(p, { 1: "#FF0000" })[0].changed).toBe(false);
  });

  it("shares are of painted surface and sum to one", () => {
    const rows = legend(preview([slot(1, "#f00", 30), slot(2, "#0f0", 10)]), {});
    expect(rows.map((r) => r.share)).toEqual([0.75, 0.25]);
  });

  it("an unpainted project uses the surface each slot is assigned", () => {
    const rows = legend(preview([slot(1, "#f00", 30, false), slot(3, "#0f0", 10, false)], { kind: "assigned" }), {});
    expect(rows.map((r) => r.share)).toEqual([0.75, 0.25]);
  });
});

describe("colourOf", () => {
  const rows = legend(preview([slot(1, "#ff0000"), slot(2, null)]), { 2: "#0000FF" });
  it("draws a null slot and a colourless slot neutral in Original", () => {
    const pick = colourOf(rows, "original");
    expect(pick(null)).toBe(NEUTRAL);
    expect(pick(2)).toBe(NEUTRAL);
    expect(pick(1)).toBe("#FF0000");
  });
  it("draws the chosen colour in Proposed, and still draws unknown surface neutral", () => {
    const pick = colourOf(rows, "proposed");
    expect(pick(2)).toBe("#0000FF");
    expect(pick(null)).toBe(NEUTRAL);
  });
  it("a slot the table does not know is neutral, not slot 1's colour", () => {
    expect(colourOf(rows, "original")(9)).toBe(NEUTRAL);
  });
});

describe("coverageClaim", () => {
  it("only a project with real painting claims painted coverage", () => {
    expect(coverageClaim(preview([slot(1, "#f00")]))).toBe("painted");
    expect(coverageClaim(preview([slot(1, "#f00", 5, false)], { kind: "assigned" }))).toBe("assigned");
    expect(coverageClaim(preview([], { kind: "geometry" }))).toBe("geometry");
  });
  it("a project flagged painted whose slots carry no painting is not a painted-coverage result", () => {
    expect(coverageClaim(preview([slot(1, "#f00", 5, false)]))).toBe("geometry");
  });
});

describe("unavailableCopy", () => {
  it("says the plate view is unaffected, and uses the engine's reason", () => {
    const p = preview([], { available: false, state: "limit", reason: "Too detailed." });
    expect(unavailableCopy(p, false)).toContain("Too detailed.");
    expect(unavailableCopy(p, false)).toContain("unaffected");
  });
  it("a failed request or missing answer gets a plain sentence, not an error string", () => {
    expect(unavailableCopy(null, true)).toMatch(/could not build/);
    expect(unavailableCopy(null, false)).toMatch(/could not build/);
  });
  it("an available preview needs no message", () => {
    expect(unavailableCopy(preview([]), false)).toBe("");
  });
});

describe("helpers", () => {
  it("decodes little-endian float32 from base64", () => {
    const f = new Float32Array([1.5, -2, 3]);
    const b64 = btoa(String.fromCharCode(...new Uint8Array(f.buffer)));
    expect(Array.from(decodeFloat32(b64))).toEqual([1.5, -2, 3]);
  });
  it("formats shares without rounding something present down to nothing", () => {
    expect(percent(null)).toBe("—");
    expect(percent(0.004)).toBe("<1%");
    expect(percent(0)).toBe("0%");
    expect(percent(0.256)).toBe("26%");
  });
});
