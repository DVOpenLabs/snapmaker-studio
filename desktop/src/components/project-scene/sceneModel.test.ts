import { describe, expect, it } from "vitest";
import { buildModel, buildViewScene, findingText, highlightGate, limitationText, COLORS } from "./sceneModel";
import { node, offBedScene, scene, cubeMesh } from "./sceneFixtures";
import type { LimitationCode, SceneFinding, SceneV1 } from "@/lib/scene";

const finding = (over: Partial<SceneFinding> = {}): SceneFinding => ({
  id: "f0", engine: "scene", schema: "scene/1", pointer: "/nodes/1", scope: "instance", kind: "placement", target_ids: ["b1"],
  value: { code: "PLACEMENT_OUTSIDE_BED", overhang_mm: { left: 0, right: 5, front: 0, back: 0 } }, ...over,
});

describe("highlight gate", () => {
  it("is open for one plate, millimeters, known placement and the real bed", () => {
    expect(highlightGate(scene())).toEqual({ enabled: true, reasons: [], covered: [] });
  });
  it.each<[string, Partial<SceneV1>]>([
    ["inch source", { sources: [{ part: "3D/3dmodel.model", unit: "inch", mm_per_unit: 25.4 }] }],
    ["two plates", { plates: [{ id: "1", ui_number: 1, origin_mm: null }, { id: "2", ui_number: 2, origin_mm: null }] }],
    ["unknown placement", { nodes: [node("b0", "1", 0, 0, { placement_state: "unknown" }), node("b1", "2", 1, 1)] }],
    ["fallback bed", { bed: { ...scene().bed, policy: "fallback" } }],
    ["unit limitation", { limitations: [{ code: "UNSUPPORTED_UNIT", target_ids: [] }] }],
  ])("closes for %s and says why in words", (_name, extra) => {
    const gate = highlightGate(scene(extra));
    expect(gate.enabled).toBe(false);
    expect(gate.reasons[0]).toMatch(/^Highlighting is off because/);
  });
});

describe("findings and highlighting", () => {
  it("highlights only the node an engine finding names, and turns the bed alert on", () => {
    const s = offBedScene();
    const model = buildModel(s);
    expect([...model.highlighted.entries()]).toEqual([["b1", "placement"]]);
    expect(model.objects.map((o) => o.tone)).toEqual([null, "placement"]);
    expect(buildViewScene(s, model).bedAlert).toBe(true);
    const colors = buildViewScene(s, model).objects.map((o) => o.parts[0].color);
    expect(colors).toEqual([COLORS.part, COLORS.placement]);
  });

  it("does not highlight geometry that merely looks off the bed when the engine named nothing", () => {
    const s = scene({ nodes: [node("b0", "1", 400, 400), node("b1", "2", 140, 100)] });
    const model = buildModel(s);
    expect(model.highlighted.size).toBe(0);
    expect(buildViewScene(s, model).bedAlert).toBe(false);
  });

  it("keeps a finding project-level when its target is not exactly one known node", () => {
    const s = scene({ findings: [finding({ target_ids: ["nope"] })] });
    const row = buildModel(s).findings[0];
    expect(row.projectLevel).toBe(true);
    expect(row.selectId).toBeNull();
    expect(buildModel(s).highlighted.size).toBe(0);
  });

  it("keeps findings project-level and highlights nothing when the gate is closed", () => {
    const s = offBedScene();
    s.plates.push({ id: "2", ui_number: 2, origin_mm: null });
    const model = buildModel(s);
    expect(model.gate.enabled).toBe(false);
    expect(model.highlighted.size).toBe(0);
    expect(model.findings[0].projectLevel).toBe(true);
    expect(model.limitations[0]).toMatch(/more than one plate/);
    expect(model.limitations.filter((l) => /more than one plate/.test(l))).toHaveLength(1);
  });

  it("highlights every drawn piece under a named assembly", () => {
    const parent = node("p0", "9", 100, 100, { mesh_key: null });
    const a = node("p0.0", "1", 100, 100, { parent_id: "p0" });
    const b = node("p0.1", "2", 110, 100, { parent_id: "p0" });
    const s = scene({ nodes: [parent, a, b], findings: [finding({ target_ids: ["p0"] })] });
    const model = buildModel(s);
    expect([...model.highlighted.keys()].sort()).toEqual(["p0.0", "p0.1"]);
    expect(model.objects).toHaveLength(1);
    expect(model.findings[0].selectId).toBe("p0");
  });

  it("lets a placement note outrank a size note on the same node", () => {
    const s = scene({ findings: [finding({ id: "f1", kind: "size", value: { code: "SIZE_EXCEEDS_BED", overhang_mm: null } }), finding()] });
    expect(buildModel(s).highlighted.get("b1")).toBe("placement");
  });
});

describe("wording", () => {
  it("separates the physical bed edge from the 0.5 mm margin", () => {
    const f = finding({ value: { code: "PLACEMENT_OUTSIDE_BED", overhang_mm: { left: 0.3, right: 5, front: 0, back: 0 } } });
    const text = findingText(f, "Object 2", 0.5);
    expect(text).toContain("right edge 4.5 mm past the bed edge");
    expect(text).toContain("left edge inside the bed but within the 0.5 mm margin Studio keeps");
  });

  it("says Placement for position and never claims a fit, readiness, a guarantee or 100%", () => {
    const s = offBedScene();
    s.findings.push(finding({ id: "f1", kind: "size", value: { code: "SIZE_EXCEEDS_BED", overhang_mm: null } }));
    const model = buildModel(s);
    const all = [
      ...model.findings.map((f) => f.text), ...model.limitations, model.summary,
      ...(Object.keys({ a: 1 }) as string[]),
      ...(["UNKNOWN_VOLUME_ROLE", "UNKNOWN_PLACEMENT", "PLATE_MEMBERSHIP_AMBIGUOUS", "PLATE_MEMBERSHIP_UNKNOWN", "PLATES_UNAVAILABLE",
        "BED_TEMPLATE_UNAVAILABLE", "REPEATED_INSTANCE_PLACEMENT_UNVERIFIED", "NON_MM_SOURCE_UNIT", "UNSUPPORTED_UNIT",
        "MULTI_PLATE_PLACEMENT_UNCHECKED", "NO_BUILD_ITEMS"] as LimitationCode[]).map(limitationText),
    ].join("\n").toLowerCase();
    expect(model.findings[0].text.startsWith("Placement:")).toBe(true);
    expect(all).not.toMatch(/\bfits?\b|ready|guarantee|100%|\bsafe\b|best|clean|optimi/);
  });
});

describe("geometry for the viewer", () => {
  it("moves the bed corner to the origin and keeps the rest of each world matrix", () => {
    const s = scene();
    const v = buildViewScene(s, buildModel(s));
    expect(v.bed).toEqual({ widthMm: 270, depthMm: 270, heightMm: 270.05 });
    expect(v.objects[0].transform.slice(12, 15)).toEqual([99.5, 99, 0]);
    expect(v.marginLoop?.[0]).toEqual([0.5, 0.5, 0.05]);
  });

  it("draws non-part volumes in a neutral color and a non-part instance entirely neutral", () => {
    const mesh = cubeMesh("1");
    mesh.volumes = [
      { id: "v0", triangle_start: 0, triangle_count: 6, role: "part", source: "bambu_part" },
      { id: "v1", triangle_start: 6, triangle_count: 6, role: "negative", source: "bambu_part" },
    ];
    const s = scene({ meshes: [mesh, cubeMesh("2")], nodes: [node("b0", "1", 0, 0), node("b1", "2", 50, 0, { role_context: "modifier" })] });
    const v = buildViewScene(s, buildModel(s));
    expect(v.objects[0].parts.map((p) => p.color)).toEqual([COLORS.part, COLORS.other]);
    expect(v.objects[1].parts.map((p) => p.color)).toEqual([COLORS.other]);
  });

  it("flips triangle winding for a mirrored instance only", () => {
    const s = scene({ nodes: [node("b0", "1", 0, 0), node("b1", "1", 50, 0, { mirrored: true })] });
    const v = buildViewScene(s, buildModel(s));
    const a = v.objects[0].parts[0].indices, b = v.objects[1].parts[0].indices;
    expect([a[1], a[2]]).toEqual([b[2], b[1]]);
    expect(a[0]).toBe(b[0]);
  });
});
