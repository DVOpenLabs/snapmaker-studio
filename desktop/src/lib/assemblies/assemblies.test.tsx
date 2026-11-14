import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import AssemblyReportView, { VERDICT_LABEL } from "./AssemblyReportView";
import { parseJsonBox } from "./api";
import { SAMPLE_ASSEMBLY, sampleSupply } from "./sample";
import type { AssemblyReport } from "./types";

const ROAD = { provider_instance_id: "sample", provider_spool_id: "road-1" };

function report(over: Partial<AssemblyReport> = {}): AssemblyReport {
  return {
    name: "Sample", advisory: "Advisory only: a test sentence.", verdict: "shortage",
    tiles: [
      { tile_id: "t1", name: "Tile 1", plate: "1", part_id: "quay", usage_source: "declared", scale: 100,
        library: { status: "missing", detail: "gone" }, attribution: {}, slots: [], need_known_g: 40, need_complete: true, unknown_slots: [] },
      { tile_id: "t2", name: "Tile 2", plate: "2", part_id: null, usage_source: null, scale: null,
        library: { status: "unlinked", detail: "" }, attribution: {}, slots: [], need_known_g: 0, need_complete: false, unknown_slots: [] },
    ],
    spools: [{ spool: ROAD, same_spool_as: [], roles: ["road"], remaining_g: 30, supply_state: "usable", verdict: "shortage",
      reason: "The tiles state 40 g against 30 g left.", need_known_g: 40, need_complete: false, unknown_tiles: ["t2"],
      starving_tiles: ["t1"], shortfall_g: 10, tiles: [] }],
    unresolved: [{ tile_id: "t2", slot: "slot:1", grams: null, reason: "no_binding", roles: ["water"] }],
    roles: [{ role: "road", tiles: ["t1", "t2"], plates: ["1", "2"], shared_across_plates: true, spool: ROAD }],
    parts: { missing: [{ part_id: "pier", name: "Pier" }], unlisted_tiles: [] },
    seam_scale: { status: "unknown", known: [], unknown: ["t2"] },
    attribution: [{ item: "Set", author: "Example Maker" }],
    ...over,
  };
}

describe("assembly report view", () => {
  const html = renderToStaticMarkup(<AssemblyReportView report={report()} />);

  it("names the spool, the starving tiles and the shortfall", () => {
    expect(html).toContain("sample / road-1");
    expect(html).toContain("Tiles that run short: t1. Short by 10 g.");
    expect(html).toContain("Shortage");
  });

  it("says a need is a lower bound when some grams are not stated, and never shows them as zero", () => {
    expect(html).toContain("Tiles state 40 g or more");
    expect(html).toContain("Tiles with no stated grams for this spool: t2.");
    expect(html).toContain("not stated for any slot");
  });

  it("reports unresolved slots, missing library projects, missing parts and unknown seam scale", () => {
    expect(html).toContain("serves a role with no spool chosen");
    expect(html).toContain("Missing from library");
    expect(html).toContain("Parts with no tile: Pier.");
    expect(html).toContain("Seam scale: not stated for t2.");
    expect(html).toContain("Attribution kept: Set, Example Maker.");
  });

  it("keeps the advisory sentence next to the verdict", () => {
    expect(html).toContain("Advisory only");
  });

  it("labels each verdict in words, with no readiness score", () => {
    expect(Object.values(VERDICT_LABEL).join(" ").toLowerCase()).not.toMatch(/ready|score|%/);
    expect(renderToStaticMarkup(<AssemblyReportView report={report({ verdict: "stale" })} />)).toContain("Reading too old");
  });

  it("says plainly when nothing is tied to a spool", () => {
    const empty = renderToStaticMarkup(<AssemblyReportView report={report({ spools: [], verdict: "unknown" })} />);
    expect(empty).toContain("No tile slot is tied to a spool yet");
  });
});

describe("assembly inputs", () => {
  it("turns a typing mistake into a sentence, not a stack trace", () => {
    expect(() => parseJsonBox("{", "The assembly")).toThrow("The assembly is not valid JSON.");
    expect(() => parseJsonBox("  ", "The assembly")).toThrow("The assembly is empty.");
    expect(parseJsonBox<{ a: number }>('{"a":1}', "x").a).toBe(1);
  });

  it("ships a six-tile sample whose figures are invented and whose readings are dated now", () => {
    expect(SAMPLE_ASSEMBLY.tiles).toHaveLength(6);
    const supply = sampleSupply(1_800_000_000);
    expect(supply.every((s) => s.observed_at === 1_800_000_000 && s.ttl_s > 0)).toBe(true);
    const text = JSON.stringify(SAMPLE_ASSEMBLY);
    expect(text).not.toMatch(/\d+\.\d+\.\d+\.\d+|[A-Za-z]:\\|\/home\//);
  });
});
