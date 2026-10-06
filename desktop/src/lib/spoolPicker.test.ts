import { describe, it, expect } from "vitest";
import type { ProviderSpool } from "@/api";
import {
  MAX_VISIBLE, describeSpool, filterSpools, initialListbox, listboxReduce, sortSpools, spoolColourName,
  weightStatus,
} from "./spoolPicker";

const spool = (id: number | string, over: Partial<ProviderSpool> = {}): ProviderSpool => ({
  id, label: `spool ${id}`, vendor: "Acme", material: "PLA", subtype: null, color: "#FF0000",
  color_name: null, remaining_g: null, remaining_quality: null, archived: false, ...over,
});

describe("describeSpool", () => {
  it("says vendor, material, subtype, colour name, id and weight in words", () => {
    const d = describeSpool(spool(124, { vendor: "Yoopai", subtype: "Matte", remaining_g: 250, remaining_quality: "estimated" }));
    expect(d.text).toBe("Yoopai PLA Matte — Red · #124 · 250 g estimated");
    expect(d.swatch).toBe("#FF0000");
  });
  it("says 'weight unknown' rather than inventing one", () => {
    expect(describeSpool(spool(133, { vendor: "Sunlu", material: "ABS", color: "#000000" })).text)
      .toBe("Sunlu ABS — Black · #133 · weight unknown");
  });
  it("labels a tracked weight as tracked and the rest as estimated", () => {
    expect(weightStatus(spool(1, { remaining_g: 99.6, remaining_quality: "tracked" }))).toBe("100 g tracked");
    expect(weightStatus(spool(1, { remaining_g: 99.6, remaining_quality: "untracked" }))).toBe("100 g estimated");
    expect(weightStatus(spool(1, { remaining_g: 0, remaining_quality: "estimated" }))).toBe("0 g estimated");
  });
  it("colour is never the only signal: the colour name and id are always in the text", () => {
    for (const color of ["#FF0000", "#00FF00", null, "garbage"]) {
      const d = describeSpool(spool(7, { color: color as string | null }));
      expect(d.idText).toBe("#7");
      expect(d.text).toContain("#7");
      if (color === "#FF0000") expect(d.text).toContain("Red");
    }
  });
  it("prefers the provider's own colour name and capitalises it", () => {
    expect(spoolColourName(spool(1, { color_name: "cherry" }))).toBe("Cherry");
  });
  it("marks an archived spool and falls back to the label when the engine sends no identity", () => {
    expect(describeSpool(spool(1, { archived: true })).text).toContain("archived");
    const bare: ProviderSpool = { id: 5, label: "Old engine spool" };
    expect(describeSpool(bare).text).toBe("Old engine spool · #5 · weight unknown");
  });
});

describe("sortSpools", () => {
  const set = [
    spool(9, { vendor: "Sunlu", material: "ABS", color: "#000000" }),
    spool(3, { subtype: "Silk" }),
    spool(2, { subtype: "Matte" }),
    spool(1, { material: "PETG" }),
    spool(7, { vendor: "acme", subtype: "Matte", color: "#0000FF" }),
    spool(10, { subtype: "Matte" }),
  ];
  it("orders by vendor, family, subtype, colour, then id", () => {
    expect(sortSpools(set).map((s) => s.id)).toEqual([1, 7, 2, 10, 3, 9]);
  });
  it("is deterministic whatever order the provider used, and never mutates its input", () => {
    const before = set.map((s) => s.id);
    const a = sortSpools(set).map((s) => s.id);
    const b = sortSpools([...set].reverse()).map((s) => s.id);
    expect(a).toEqual(b);
    expect(set.map((s) => s.id)).toEqual(before);
  });
  it("sorts numeric ids as numbers and text ids after them", () => {
    const ids = sortSpools([spool("A1"), spool(1000), spool(124), spool("b2"), spool(5)]).map((s) => s.id);
    expect(ids).toEqual([5, 124, 1000, "A1", "b2"]);
  });
  it("puts a spool that does not name its vendor after one that does", () => {
    expect(sortSpools([spool(1, { vendor: null }), spool(2, { vendor: "Zeta" })]).map((s) => s.id)).toEqual([2, 1]);
  });
  it("keeps two similar spools apart by id", () => {
    const twins = sortSpools([spool(134, { vendor: "Sunlu", material: "ABS" }), spool(133, { vendor: "Sunlu", material: "ABS" })]);
    expect(twins.map((s) => describeSpool(s).name)).toEqual(["Sunlu ABS", "Sunlu ABS"]);
    expect(twins.map((s) => s.id)).toEqual([133, 134]);
  });
});

describe("filterSpools (type-ahead)", () => {
  const list = [
    spool(124, { vendor: "Yoopai", subtype: "Matte" }),
    spool(133, { vendor: "Sunlu", material: "ABS", color: "#000000" }),
    spool(134, { vendor: "Sunlu", material: "ABS", color: "#FFFFFF" }),
  ];
  it("every word must match, in any order, case-insensitively", () => {
    expect(filterSpools(list, "sunlu black").map((s) => s.id)).toEqual([133]);
    expect(filterSpools(list, "ABS SUNLU").map((s) => s.id)).toEqual([133, 134]);
    expect(filterSpools(list, "red matte").map((s) => s.id)).toEqual([124]);
  });
  it("finds a spool by its id, with or without the #", () => {
    expect(filterSpools(list, "#134").map((s) => s.id)).toEqual([134]);
    expect(filterSpools(list, "124").map((s) => s.id)).toEqual([124]);
  });
  it("an empty query shows everything, and no match shows nothing", () => {
    expect(filterSpools(list, "  ")).toHaveLength(3);
    expect(filterSpools(list, "nope")).toHaveLength(0);
  });
});

describe("listbox keyboard reducer", () => {
  it("opens on the selected row and closes cleanly", () => {
    const open = listboxReduce(initialListbox, { type: "open", selectedIndex: 4 });
    expect(open).toEqual({ open: true, query: "", active: 4 });
    expect(listboxReduce(open, { type: "close" })).toEqual(initialListbox);
  });
  it("arrow keys move through the rows and wrap, including the 'nothing mapped' row", () => {
    let s = listboxReduce(initialListbox, { type: "open", selectedIndex: -1 });
    s = listboxReduce(s, { type: "move", delta: 1, count: 3 });
    expect(s.active).toBe(0);
    s = listboxReduce(s, { type: "move", delta: 1, count: 3 });
    s = listboxReduce(s, { type: "move", delta: 1, count: 3 });
    expect(s.active).toBe(2);
    s = listboxReduce(s, { type: "move", delta: 1, count: 3 });
    expect(s.active).toBe(-1);          // wraps to "nothing mapped"
    s = listboxReduce(s, { type: "move", delta: -1, count: 3 });
    expect(s.active).toBe(2);           // and back round to the last row
  });
  it("Home and End jump to the ends", () => {
    const s = listboxReduce(initialListbox, { type: "open", selectedIndex: 1 });
    expect(listboxReduce(s, { type: "end", count: 5 }).active).toBe(4);
    expect(listboxReduce(s, { type: "home" }).active).toBe(-1);
  });
  it("typing narrows the list and highlights the first match", () => {
    const s = listboxReduce(initialListbox, { type: "type", query: "sun" });
    expect(s).toEqual({ open: true, query: "sun", active: 0 });
    expect(listboxReduce(s, { type: "type", query: "" }).active).toBe(-1);
  });
});

describe("a long list (100+ spools)", () => {
  const many: ProviderSpool[] = Array.from({ length: 140 }, (_, i) =>
    spool(i + 1, { vendor: ["Acme", "Sunlu", "Yoopai", "eSun"][i % 4], material: ["PLA", "PETG", "ABS"][i % 3],
      color: ["#FF0000", "#00FF00", "#0000FF", "#000000", "#FFFFFF"][i % 5] }));
  it("sorts the same way twice and quickly", () => {
    const t0 = performance.now();
    const a = sortSpools(many).map((s) => s.id);
    const b = sortSpools([...many].reverse()).map((s) => s.id);
    expect(a).toEqual(b);
    expect(a).toHaveLength(140);
    expect(performance.now() - t0).toBeLessThan(500);
  });
  it("narrows to a handful with a few typed words", () => {
    const hits = filterSpools(sortSpools(many), "sunlu abs red");
    expect(hits.length).toBeGreaterThan(0);
    expect(hits.length).toBeLessThan(10);
    expect(hits.every((s) => s.vendor === "Sunlu" && s.material === "ABS")).toBe(true);
  });
  it("caps how many rows are drawn", () => {
    expect(MAX_VISIBLE).toBeGreaterThanOrEqual(140);
  });
});
