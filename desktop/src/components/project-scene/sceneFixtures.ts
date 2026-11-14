// Anonymous scene/1 fixtures for tests and screenshots. Shapes follow backend/tests/fixtures/scene/golden-scene-1.json.
import type { SceneMesh, SceneNode, SceneV1 } from "@/lib/scene";

const b64 = (bytes: Uint8Array) => btoa(Array.from(bytes, (b) => String.fromCharCode(b)).join(""));

export function cubeMesh(objectId = "1", size = 20, part = "3D/3dmodel.model"): SceneMesh {
  const s = size;
  const positions = [0, 0, 0, s, 0, 0, s, s, 0, 0, s, 0, 0, 0, s, s, 0, s, s, s, s, 0, s, s];
  const indices = [
    0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 1, 2, 6, 1, 6, 5, 2, 3, 7, 2, 7, 6, 3, 0, 4, 3, 4, 7,
  ];
  return {
    key: { part, object_id: objectId }, vertex_count: 8, triangle_count: 12,
    positions_f32le_base64: b64(new Uint8Array(new Float32Array(positions).buffer)),
    indices_u32le_base64: b64(new Uint8Array(new Uint32Array(indices).buffer)),
    volumes: [{ id: "v0", triangle_start: 0, triangle_count: 12, role: "part", source: "object" }],
  };
}

export function matrixAt(x: number, y: number, z = 0): number[] {
  return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1];
}

export function node(id: string, objectId: string, x: number, y: number, extra: Partial<SceneNode> = {}): SceneNode {
  const m = matrixAt(x, y);
  return {
    id, parent_id: null, resource: { part: "3D/3dmodel.model", object_id: objectId },
    mesh_key: { part: "3D/3dmodel.model", object_id: objectId },
    local_to_parent_mm: m, world_mm: m, mirrored: false, role_context: null, build_index: 0,
    instance_ref: { build_index: 0, component_path: [] },
    plate: { state: "known", plate_id: "1", source: "plate_config" },
    placement_state: "known", printable: true, has_non_part_volumes: false,
    bounds_mm: { min: [x, y, 0], max: [x + 20, y + 20, 20] }, finding_ids: [], ...extra,
  };
}

export function scene(extra: Partial<SceneV1> = {}): SceneV1 {
  return {
    schema: "scene/1", revision: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    status: "complete", units: "mm", axes: "right-handed-z-up",
    sources: [{ part: "3D/3dmodel.model", unit: "millimeter", mm_per_unit: 1 }],
    bed: { polygon_mm: [[0.5, 1], [270.5, 1], [270.5, 271], [0.5, 271]], height_mm: 270.05, edge_margin_mm: 0.5, policy: "u1_template" },
    meshes: [cubeMesh("1"), cubeMesh("2")],
    nodes: [node("b0", "1", 100, 100), node("b1", "2", 140, 100)],
    plates: [{ id: "1", ui_number: 1, origin_mm: null }],
    findings: [], limitations: [],
    counts: { nodes: 2, meshes: 2, vertices: 16, triangles: 24, rendered_triangles: 24, plates: 1, findings: 0, limitations: 0 },
    limits: {},
    ...extra,
  };
}

/** One object 4.5 mm past the right edge, flagged by an engine finding keyed to its node id. */
export function offBedScene(): SceneV1 {
  const far = node("b1", "2", 255, 100, { bounds_mm: { min: [255, 100, 0], max: [275, 120, 20] }, finding_ids: ["f0"] });
  return scene({
    nodes: [node("b0", "1", 100, 100), far],
    findings: [{
      id: "f0", engine: "scene", schema: "scene/1", pointer: "/nodes/1", scope: "instance", kind: "placement", target_ids: ["b1"],
      value: { code: "PLACEMENT_OUTSIDE_BED", overhang_mm: { left: 0, right: 5, front: 0, back: 0 } },
    }],
    counts: { nodes: 2, meshes: 2, vertices: 16, triangles: 24, rendered_triangles: 24, plates: 1, findings: 1, limitations: 0 },
  });
}
