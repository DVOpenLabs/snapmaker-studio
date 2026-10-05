import { describe, it, expect } from "vitest";
import {
  PRIMARY_NAV, SECONDARY_NAV, BEGINNER_NAV, MORE_NAV, SIMPLE_SECONDARY_NAV,
  isKnownRoute,
} from "./nav";
import { DOCTORS } from "./doctors";

const primaryLabels = PRIMARY_NAV.map((n) => n.label);
const primaryRoutes = PRIMARY_NAV.map((n) => n.to);

// Doctors folded out of the primary sidebar into a combined page:
//  - cost/pricing/profit -> one "Cost & Pricing Doctor"
//  - first-layer -> a "Print Quality" tab; multi-material -> a "Colors & Materials" tab
const MERGED_IDS = new Set(["cost", "pricing", "profit", "first-layer", "multi-material"]);

describe("1. sidebar exposes core Doctors directly", () => {
  it("every non-merged Doctor is reachable from the primary sidebar", () => {
    for (const d of DOCTORS) {
      if (MERGED_IDS.has(d.id)) continue; // folded into a combined page below
      expect(primaryRoutes).toContain(d.route);
    }
  });
  it("Cost/Pricing/Profit are one combined sidebar item, not three", () => {
    const bizItems = PRIMARY_NAV.filter((n) => n.doctorId && ["cost", "pricing", "profit"].includes(n.doctorId));
    expect(bizItems).toHaveLength(1);
    expect(bizItems[0].label).toBe("Cost & Pricing Doctor");
  });
  it("each merged combined page appears exactly once in the primary sidebar", () => {
    for (const route of ["/compatibility", "/print-quality", "/colors", "/doctor/cost"]) {
      expect(primaryRoutes.filter((r) => r === route)).toHaveLength(1);
    }
  });
  it("old/merged routes still resolve (aliases, no crash)", () => {
    for (const route of ["/doctor/pricing", "/doctor/profit", "/first-layer", "/doctor/multi-material", "/source", "/plate-remap"]) {
      expect(isKnownRoute(route)).toBe(true);
    }
  });
  it("core primary items are present by name", () => {
    for (const name of ["Project Doctor", "Printer Hub", "Compatibility", "Print Quality", "Colors & Materials", "Cost & Pricing Doctor"]) {
      expect(primaryLabels).toContain(name);
    }
  });
});

describe("1b. Ready now is reachable in both modes, right after the projects page", () => {
  it("sits after Projects in the advanced sidebar", () => {
    expect(primaryLabels.indexOf("Ready now")).toBe(primaryLabels.indexOf("Projects") + 1);
  });
  it("sits after My designs in Simple mode", () => {
    const labels = BEGINNER_NAV.map((n) => n.label);
    expect(labels.indexOf("Ready now")).toBe(labels.indexOf("My designs") + 1);
    expect(isKnownRoute("/ready-now")).toBe(true);
  });
});

describe("2. Why Studio? is not in primary workflow nav", () => {
  it("lives in secondary, not primary", () => {
    expect(primaryLabels).not.toContain("Why Studio?");
    expect(SECONDARY_NAV.map((n) => n.label)).toContain("Why Studio?");
  });
});

describe("3. merged tools are not duplicated as separate primary items", () => {
  it("First Layer / Multi-Material / Source Check / Plate Color Remap are not separate primary entries", () => {
    for (const gone of ["First Layer Doctor", "Multi-Material Doctor", "Source Check", "Plate Color Remap"]) {
      expect(primaryLabels).not.toContain(gone);
    }
  });
});

describe("4. Dashboard Doctor cards route to matching pages / safe landings", () => {
  it("every Doctor route resolves to a known route", () => {
    for (const d of DOCTORS) {
      expect(isKnownRoute(d.route)).toBe(true);
    }
  });
});

describe("5. no broken routes / blank pages", () => {
  it("every primary + secondary nav target is a known route", () => {
    for (const n of [...PRIMARY_NAV, ...SECONDARY_NAV]) {
      expect(isKnownRoute(n.to)).toBe(true);
    }
  });
  it("rejects an unknown route", () => {
    expect(isKnownRoute("/doctor/does-not-exist")).toBe(false);
    expect(isKnownRoute("/nope")).toBe(false);
  });
});

describe("6. Simple mode IA (one clear path for a novice)", () => {
  it("has at most 6 primary items, in the novice order", () => {
    expect(BEGINNER_NAV.length).toBeLessThanOrEqual(6);
    // "This print" replaced "Check my model" in v0.6.0: the cockpit opens on the
    // same findings and then stays with the job through slicing and sending,
    // which is the journey a beginner actually has. The standalone Project
    // Doctor keeps its route and moves to More tools — nothing was removed.
    expect(BEGINNER_NAV.map((n) => n.label)).toEqual([
      "Home", "This print", "My designs", "Ready now", "Printer", "Help",
    ]);
  });
  it("keeps every advanced tool reachable (More tools covers the rest of PRIMARY_NAV)", () => {
    const simpleRoutes = new Set([...BEGINNER_NAV, ...MORE_NAV].map((n) => n.to));
    for (const n of PRIMARY_NAV) expect(simpleRoutes.has(n.to)).toBe(true);
  });
  it("does not repeat Help in the Simple footer", () => {
    expect(SIMPLE_SECONDARY_NAV.some((n) => n.to === "/help")).toBe(false);
    expect(SECONDARY_NAV.some((n) => n.to === "/help")).toBe(true);
  });
  it("every Simple destination resolves to a real route", () => {
    for (const n of [...BEGINNER_NAV, ...MORE_NAV, ...SIMPLE_SECONDARY_NAV]) {
      expect(isKnownRoute(n.to)).toBe(true);
    }
  });
});
