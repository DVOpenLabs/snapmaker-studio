// Builders for Project Materials tests: engine-shaped data with sensible defaults.
import type { MaterialCandidate, MaterialMapping, MaterialSlot } from "./projectMaterials";

export function mapping(over: Partial<MaterialMapping> = {}): MaterialMapping {
  return { status: "no_match", match_source: "none", preset_name: null, base_name: null, reason: "No preset has been chosen for this spool yet.",
    candidates: [], stale: false, ...over };
}

export function candidate(over: Partial<MaterialCandidate> = {}): MaterialCandidate {
  return {
    provider: "spoolease", spool_id: "124", rank: 1, label: "Yoopai PLA Matte", vendor: "Yoopai", material: "PLA", subtype: "Matte",
    colour: "#FF0000", color_name: "red", remaining_g: 412, remaining_quality: "tracked", loaded_slot: null, slicer_filament: null,
    mapping: mapping(), reasons: [{ code: "material_exact", text: "Material matches: PLA" }], ...over,
  };
}

export function slot(over: Partial<MaterialSlot> = {}): MaterialSlot {
  return { slot: 0, material: "PLA", family: "PLA", subtype: null, colour: "#FF0000", required_g: 180, required_source: "the source file's own slice",
    settings_id: "Generic PLA @BBL H2D", vendor: "Bambu Lab", declared_keys: [], candidates: [candidate()], candidate_count: 1, close_call: false,
    selected: null, current_preset: null, suggestion: null, ...over };
}

