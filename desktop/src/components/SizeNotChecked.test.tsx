// @vitest-environment jsdom
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DesignHealth } from "@/components/DesignHealth";
import { BedFitNotChecked, FirstLayerNotChecked } from "@/components/SizeNotChecked";
import { NotCheckedReason, rawSizeQualifier, sizeNotEstablished } from "@/components/GeometryNotice";
import { recTone } from "@/routes/ScaleDoctor";
import type { BedFit, FirstLayerReport, GeometryBasis, MeshReport, PrintFindings } from "@/api";
import { PrintRiskSignals } from "@/components/PrintRiskSignals";

afterEach(cleanup);

const REASON = "The file declares its unit as inch, but Studio reads its numbers as millimetres and does not convert them.";
const NOT_ESTABLISHED: GeometryBasis = {
  schema_version: "geometry-basis/1", established: false, reasons: ["unit_not_millimeter"], summary: REASON,
  withheld: ["bed fit", "the print risk signals"],
};
const ESTABLISHED: GeometryBasis = { schema_version: "geometry-basis/1", established: true, reasons: [], summary: "", withheld: [] };

const bed = (over: Partial<BedFit>): BedFit => ({ available: false, status: "not_checked", reason: REASON, scope: "bed fit", ...over });
const MESH: MeshReport = {
  schema_version: "mesh/1", available: true, triangle_count: 12,
  integrity: { watertight: true, manifold: true, open_edges: 0, holes: 0, non_manifold_edges: 0, degenerate_faces: 0, duplicate_faces: 0, winding_consistent: true },
  overhang: { overhang_pct: 0, severe_pct: 0, supports_likely: false },
  stability: { tip_risk: false, com_over_base: true, margin_mm: 5, height_mm: 30, aspect: 1.5 },
  volume_cm3: 6, surface_area_mm2: 2200, findings: [],
};
const DIMS = { x: 10, y: 20, z: 30 };

describe("a not-checked verdict names its scope and gives one shared reason", () => {
  it("bed fit, first layer and the print risk signals show the same reason and never a verdict", () => {
    const fl: FirstLayerReport = { available: false, status: "not_checked", reason: REASON, scope: "first-layer footprint checks" };
    const pr: PrintFindings = { available: true, status: "not_checked", reason: REASON, scope: "the print risk signals that rest on the model's size",
      signals: [{ id: "toolhead-fit", kind: "engine", level: "risk", title: "More colors than toolheads", meaning: "m", action: "a" }],
      checked: ["colors against toolheads"], not_checked: ["design validation", "first-layer risk"] };
    render(<><BedFitNotChecked bed={bed({})} /><FirstLayerNotChecked report={fl} /><PrintRiskSignals findings={pr} /></>);
    const notes = screen.getAllByTestId("not-checked-reason");
    expect(notes).toHaveLength(3);
    notes.forEach((n) => expect(n.textContent).toContain(REASON));
    expect(notes.map((n) => n.textContent)).toEqual([
      expect.stringContaining("Not checked: bed fit."),
      expect.stringContaining("Not checked: first-layer footprint checks."),
      expect.stringContaining("Not checked: the print risk signals that rest on the model's size."),
    ]);
    expect(screen.getByText(/More colors than toolheads/)).toBeTruthy();   // independent signals stay visible
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/Fits|Out of bounds|Few risks|Likely|\d+%/);
  });

  it("control: an ordinary verdict renders none of the not-checked cards or notes", () => {
    const { container } = render(<>
      <BedFitNotChecked bed={{ available: true, overall_level: "ok" }} />
      <FirstLayerNotChecked report={{ available: true, overall_level: "ok" }} />
    </>);
    expect(container.textContent).toBe("");
  });
});

const objectsOf = (d: { x: number; y: number; z: number }) =>
  [{ object_id: "1", part: "3D/3dmodel.model", instance_count: 1, dimensions_mm: d }];

describe("Design Health does not judge the bed or vouch for a raw size", () => {
  it("not established: bed fit is Not checked with the reason, and never Fits or Too big", () => {
    render(<DesignHealth mesh={{ ...MESH, geometry_basis: NOT_ESTABLISHED }} dims={DIMS} mode="simple" />);
    const text = document.body.textContent ?? "";
    expect(text).toContain("Bed fit");
    expect(text).toContain("Not checked");
    expect(text).toContain(REASON);
    expect(text).not.toMatch(/Fits|Too big/);
    expect(text).toContain("not a confirmed physical size");               // stability is qualified
  });

  it("the raw-size qualifier also applies to a tip-risk stability finding", () => {
    const tippy: MeshReport = { ...MESH, geometry_basis: NOT_ESTABLISHED,
      stability: { tip_risk: true, com_over_base: false, margin_mm: 0, height_mm: 30, aspect: 6 } };
    render(<DesignHealth mesh={tippy} dims={DIMS} mode="simple" />);
    expect(document.body.textContent).toMatch(/Tall and narrow[^]*not a confirmed physical size/);
  });

  it("not established with no overall dims but per-object sizes: still Not checked, never Fits or Too big", () => {
    render(<DesignHealth mesh={{ ...MESH, geometry_basis: NOT_ESTABLISHED }} dims={null} objects={objectsOf(DIMS)} mode="simple" />);
    const text = document.body.textContent ?? "";
    expect(text).toContain("Not checked");
    expect(text).toContain(REASON);
    expect(text).not.toMatch(/Fits|Too big|10 × 20 × 30/);
  });

  it("control: established size keeps the normal Fits verdict", () => {
    render(<DesignHealth mesh={{ ...MESH, geometry_basis: ESTABLISHED }} dims={DIMS} objects={objectsOf(DIMS)} mode="simple" />);
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/Fits/);
    expect(text).not.toMatch(/Not checked|not a confirmed physical size/);
  });

  it("control: a mesh without a basis judges the per-object sizes", () => {
    render(<DesignHealth mesh={MESH} dims={DIMS} objects={objectsOf(DIMS)} mode="simple" />);
    expect(document.body.textContent).toMatch(/Fits/);
  });

  it("control: no per-object sizes at all reads Unknown, not Fits", () => {
    render(<DesignHealth mesh={MESH} dims={DIMS} mode="simple" />);
    expect(document.body.textContent).toMatch(/Unknown/);
    expect(document.body.textContent).not.toMatch(/Fits/);
  });

  it("a too-large established model is still Too big (the guard does not soften real verdicts)", () => {
    render(<DesignHealth mesh={{ ...MESH, geometry_basis: ESTABLISHED }} dims={{ x: 300, y: 20, z: 30 }} objects={objectsOf({ x: 300, y: 20, z: 30 })} mode="simple" />);
    expect(document.body.textContent).toMatch(/Too big/);
  });
});

describe("shared helpers", () => {
  it("only an explicit established=false counts as not established", () => {
    expect(sizeNotEstablished(NOT_ESTABLISHED)).toBe(true);
    expect(sizeNotEstablished(ESTABLISHED)).toBe(false);
    expect(sizeNotEstablished(undefined)).toBe(false);
    expect(rawSizeQualifier(NOT_ESTABLISHED)).toMatch(/not a confirmed physical size/);
    expect(rawSizeQualifier(ESTABLISHED)).toBeNull();
  });

  it("NotCheckedReason falls back to a plain Not checked without a scope", () => {
    render(<NotCheckedReason reason={REASON} />);
    expect(screen.getByTestId("not-checked-reason").textContent).toBe(`Not checked. ${REASON}`);
  });

  it("Scale Doctor never labels a not-checked preview Recommended", () => {
    expect(recTone("not checked").label).toBe("Fit not checked");
    expect(recTone("not recommended").label).toBe("Not recommended");
    expect(recTone("caution").label).toBe("Caution");
  });
});
