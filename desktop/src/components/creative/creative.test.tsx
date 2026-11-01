import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import CreativeReportView from "./CreativeReportView";
import CreativeView from "./CreativeView";
import creativeRoute from "@/routes/ext/creative.route";
import creativeMeta from "@/routes/ext/creative.meta";
import type { CreativeInspectResponse } from "@/lib/creativeApi";

const HASH = "a".repeat(64);

function report(over: Partial<CreativeInspectResponse> = {}): CreativeInspectResponse {
  return {
    origin: { generator: "fullspectrum", status: "detected", candidates: ["fullspectrum"] },
    understood: ["mixed_filament_definitions"],
    passed_through: [{ name: "layer_height", sha256: HASH }],
    could_not_interpret: ["fos_future_key"],
    missing: ["fos_physical_nozzle_diameter"],
    diagnostics: ["unrecognized_fullspectrum_row_shape"],
    recipes: [{ recipe_id: "fullspectrum:7", generator: { name: "FullSpectrum", version: "0.9.12" }, kind: "fullspectrum",
      components: [{ source: "project:1:1" }, { source: "project:1:2" }], simulated: true, execution_supported: false }],
    physical_slots_needed: 2,
    source: { name: "synthetic.3mf", size_bytes: 1234, sha256_before: HASH, sha256_after: HASH, unchanged: true },
    evidence: "fixture-tested", advisory: "Advisory read of one project file.",
    ...over,
  };
}

describe("creative route wiring", () => {
  it("route default export has the { path, Component } shape and meta agrees", () => {
    expect(Object.keys(creativeRoute).sort()).toEqual(["Component", "path"]);
    expect(typeof creativeRoute.Component).toBe("function");
    expect(creativeRoute.path).toBe("/creative");
    expect(creativeMeta.path).toBe(creativeRoute.path);
    expect(creativeMeta.group).toBe("Studio+");
    expect(creativeMeta.label).toBe("Creative import");
  });
});

describe("creative report view", () => {
  const html = renderToStaticMarkup(<CreativeReportView report={report()} />);

  it("shows understood, untouched and could-not-interpret buckets", () => {
    expect(html).toContain("mixed_filament_definitions");
    expect(html).toContain("layer_height (aaaaaaaa)");
    expect(html).toContain("fos_future_key");
    expect(html).toContain("fos_physical_nozzle_diameter (expected, not found)");
    expect(html).toContain("note: unrecognized_fullspectrum_row_shape");
  });

  it("labels recipes as simulated, not executed, ratios not stated", () => {
    expect(html).toContain("fullspectrum:7");
    expect(html).toContain("ratios not stated");
    expect(html).toContain("Simulated; execution not supported");
    expect(html).toContain("not a statement about your loaded filament");
  });

  it("shows the unchanged-original hash line and the evidence label", () => {
    expect(html).toContain("Original unchanged");
    expect(html).toContain("before aaaaaaaaaaaaaaaa, after aaaaaaaaaaaaaaaa");
    expect(html).toContain("fixture-tested");
  });

  it("reports a changed fingerprint instead of claiming it is unchanged", () => {
    const changed = renderToStaticMarkup(<CreativeReportView report={report({
      source: { name: "x.3mf", size_bytes: 1, sha256_before: HASH, sha256_after: "b".repeat(64), unchanged: false } })} />);
    expect(changed).not.toContain("Original unchanged");
    expect(changed).toContain("differs between the two reads");
  });

  it("unknown origin stays unknown", () => {
    const h = renderToStaticMarkup(<CreativeReportView report={report({ origin: { generator: "unknown", status: "unknown", candidates: [] }, recipes: [], physical_slots_needed: null })} />);
    expect(h).toContain("Origin unknown");
    expect(h).toContain("No recipes in this file.");
  });

  it("has no overclaiming or readiness wording", () => {
    const all = (html + renderToStaticMarkup(<CreativeView />)).toLowerCase();
    for (const banned of ["ready", "coming soon", "guarantee", "100%", "simultaneous", "print success", "printer doctor"]) {
      expect(all).not.toContain(banned);
    }
  });
});

describe("creative view", () => {
  it("renders the path input, format choice and a disabled inspect button", () => {
    const html = renderToStaticMarkup(<CreativeView />);
    expect(html).toContain("Project file path");
    expect(html).toContain("Detect from settings");
    expect(html).toMatch(/<button[^>]*disabled[^>]*>Inspect project/);
  });
});
