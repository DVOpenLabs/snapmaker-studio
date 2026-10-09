// Turns a scene/1 document into what the read-only project view shows: object rows, finding rows, plain-language notes
// about what the scene cannot prove, and the geometry handed to the viewer. Pure functions: no DOM, no WebGL.
// Highlighting comes ONLY from engine findings keyed to instance ids. Nothing here measures bounds or decides placement.
import {
  decodeMesh, type LimitationCode, type SceneFinding, type SceneNode, type SceneV1, type VolumeRole,
} from "@/lib/scene";

export type Tone = "placement" | "size";
export type ViewPart = { name: string; positions: Float32Array; indices: Uint32Array; color: string };
export type ViewObject = { id: string; name: string; transform: number[]; parts: ViewPart[] };
export type ViewScene = {
  bed: { widthMm: number; depthMm: number; heightMm: number };
  objects: ViewObject[];
  /** The 0.5 mm policy margin, as a closed outline inside the physical bed edge (bed frame, mm). */
  marginLoop: [number, number, number][] | null;
  /** True when at least one object is highlighted as past the bed edge; turns the bed outline to the alert color. */
  bedAlert: boolean;
};

export const COLORS = {
  part: "#68c6dc",
  placement: "#f26b5b",
  size: "#f3b461",
  other: "#9aa5b1",
} as const;

export type HighlightGate = { enabled: boolean; reasons: string[]; /** Limitation codes whose wording is already given by a reason, so they are not listed twice. */ covered: LimitationCode[] };

const LIMITATION_TEXT: Record<LimitationCode, string> = {
  UNKNOWN_VOLUME_ROLE: "Some parts of an object have a role the file does not state, so they are drawn in gray and left out of any size or placement note.",
  UNKNOWN_PLACEMENT: "The file does not say where some objects sit, so they are drawn at a stand-in position.",
  PLATE_MEMBERSHIP_AMBIGUOUS: "The file does not make clear which plate some objects belong to.",
  PLATE_MEMBERSHIP_UNKNOWN: "The file does not say which plate some objects belong to.",
  PLATES_UNAVAILABLE: "The plate layout could not be read from this file.",
  BED_TEMPLATE_UNAVAILABLE: "Studio could not load its printer bed outline, so no placement notes are shown.",
  REPEATED_INSTANCE_PLACEMENT_UNVERIFIED: "This project repeats an object. Each copy is drawn where the file puts it, but Studio does not make placement notes for repeated copies.",
  NON_MM_SOURCE_UNIT: "This project is not written in millimeters. It is converted for the view, and placement notes are turned off.",
  UNSUPPORTED_UNIT: "This project declares a unit Studio does not recognize. It is drawn as millimeters and no size or placement notes are made.",
  MULTI_PLATE_PLACEMENT_UNCHECKED: "This project has more than one plate. Studio does not know how the plates are spaced, so it does not check placement.",
  NO_BUILD_ITEMS: "This file lists no build items, so its objects are drawn without a known position.",
};
export function limitationText(code: LimitationCode): string {
  return LIMITATION_TEXT[code] ?? "Studio could not read part of this file, so the view is incomplete.";
}

/** Geometric highlighting is allowed only when the scene can prove it: millimeters, one plate, known placement, real bed. */
export function highlightGate(scene: SceneV1): HighlightGate {
  const reasons: string[] = [];
  const covered: LimitationCode[] = [];
  const codes = new Set(scene.limitations.map((l) => l.code));
  if (scene.sources.some((s) => s.unit !== "millimeter") || codes.has("NON_MM_SOURCE_UNIT") || codes.has("UNSUPPORTED_UNIT")) {
    if (codes.has("UNSUPPORTED_UNIT")) {
      reasons.push("Highlighting is off because this project declares a unit Studio does not recognize. It is drawn as if it were in millimeters.");
      covered.push("UNSUPPORTED_UNIT");
    } else {
      reasons.push("Highlighting is off because this project is not written in millimeters. It is converted to millimeters for the view.");
    }
    covered.push("NON_MM_SOURCE_UNIT");
  }
  if (scene.plates.length > 1 || codes.has("MULTI_PLATE_PLACEMENT_UNCHECKED")) {
    reasons.push("Highlighting is off because this project has more than one plate. All plates are drawn on one bed, so objects may look closer together than they are.");
    covered.push("MULTI_PLATE_PLACEMENT_UNCHECKED");
  }
  if (scene.nodes.some((n) => n.mesh_key !== null && n.placement_state !== "known") || codes.has("UNKNOWN_PLACEMENT")) {
    reasons.push("Highlighting is off because the file does not say where some objects sit, so they are drawn at a stand-in position that is not their real place.");
    covered.push("UNKNOWN_PLACEMENT");
  }
  if (scene.bed.policy !== "u1_template" || codes.has("BED_TEMPLATE_UNAVAILABLE")) {
    reasons.push("Highlighting is off because Studio could not load its printer bed outline, so no placement notes are shown.");
    covered.push("BED_TEMPLATE_UNAVAILABLE");
  }
  return { enabled: reasons.length === 0, reasons, covered };
}

const EDGE_ORDER = ["left", "right", "front", "back"] as const;

function mm(value: number): string {
  return value.toFixed(1);
}

/** Words for one finding. "Placement" is about position; the scene never says a model "fits". */
export function findingText(finding: SceneFinding, label: string, marginMm: number): string {
  if (finding.value.code === "SIZE_EXCEEDS_BED") {
    return `Size: ${label} is larger than the usable bed area, which is the bed minus a ${mm(marginMm)} mm margin on every edge.`;
  }
  const over = finding.value.overhang_mm;
  if (!over) return `Placement: ${label} reaches past the bed edge.`;
  const parts: string[] = [];
  for (const edge of EDGE_ORDER) {
    const value = over[edge];
    if (!(value > 0)) continue;
    // The engine measures past the margin line. The physical edge is one margin further out.
    if (value > marginMm) parts.push(`${edge} edge ${mm(value - marginMm)} mm past the bed edge`);
    else parts.push(`${edge} edge inside the bed but within the ${mm(marginMm)} mm margin Studio keeps`);
  }
  return `Placement: ${label}, ${parts.join("; ") || "reaches past the bed edge"}.`;
}

export type ObjectRow = {
  id: string; label: string; plateText: string; roleText: string; tone: Tone | null; hasGeometry: boolean;
};
export type FindingRow = {
  id: string; text: string; tone: Tone; targetIds: string[]; projectLevel: boolean;
  /** The top-level object row to select when this note is chosen; null for a project-level note. */
  selectId: string | null;
};
export type SceneModel = {
  gate: HighlightGate;
  objects: ObjectRow[];
  findings: FindingRow[];
  limitations: string[];
  /** Node ids (with geometry) to draw highlighted, by tone. Empty when the gate is off. */
  highlighted: Map<string, Tone>;
  summary: string;
  partial: boolean;
  /** The policy margin inside the bed edge, from the scene. */
  marginMm: number;
};

function childrenOf(nodes: SceneNode[]): Map<string, SceneNode[]> {
  const map = new Map<string, SceneNode[]>();
  for (const n of nodes) {
    if (n.parent_id === null) continue;
    const list = map.get(n.parent_id);
    if (list) list.push(n); else map.set(n.parent_id, [n]);
  }
  return map;
}

function subtree(root: SceneNode, kids: Map<string, SceneNode[]>): SceneNode[] {
  const out: SceneNode[] = [];
  const stack = [root];
  const seen = new Set<string>();
  while (stack.length) {
    const n = stack.pop()!;
    if (seen.has(n.id)) continue;
    seen.add(n.id);
    out.push(n);
    for (const k of kids.get(n.id) ?? []) stack.push(k);
  }
  return out;
}

export function buildModel(scene: SceneV1): SceneModel {
  const gate = highlightGate(scene);
  const byId = new Map(scene.nodes.map((n) => [n.id, n]));
  const kids = childrenOf(scene.nodes);
  const tops = scene.nodes.filter((n) => n.parent_id === null);
  const labelOf = new Map<string, string>();
  tops.forEach((n, i) => labelOf.set(n.id, `Object ${i + 1}`));
  // A nested node is named after the object it sits in.
  const topOf = (n: SceneNode): SceneNode => {
    let cur = n;
    for (let guard = 0; cur.parent_id !== null && guard < 80; guard++) {
      const parent = byId.get(cur.parent_id);
      if (!parent) break;
      cur = parent;
    }
    return cur;
  };
  const nameOf = (n: SceneNode) => labelOf.get(topOf(n).id) ?? "An object";

  const highlighted = new Map<string, Tone>();
  const findings: FindingRow[] = [];
  for (const f of scene.findings) {
    if (f.kind !== "placement" && f.kind !== "size") continue;
    const tone: Tone = f.kind === "placement" ? "placement" : "size";
    const targets = f.target_ids.map((id) => byId.get(id));
    // Object-level only when the finding names known nodes that are one object: a single target, or several that all sit
    // under the same top-level object. Unknown ids, or targets in different objects, stay project-level: picking "the
    // first" would select and highlight the wrong thing.
    const resolved = f.scope === "instance" && targets.length > 0 && targets.every((t): t is SceneNode => t !== undefined);
    const topIds = resolved ? new Set((targets as SceneNode[]).map((t) => topOf(t).id)) : new Set<string>();
    const exact = resolved && topIds.size === 1;
    const known = exact ? (targets as SceneNode[]) : [];
    const label = exact ? nameOf(known[0]) : "An object";
    const projectLevel = !exact || !gate.enabled;
    findings.push({
      id: f.id, tone, text: findingText(f, label, scene.bed.edge_margin_mm),
      targetIds: projectLevel ? [] : known.map((n) => n.id), projectLevel,
      selectId: projectLevel ? null : topOf(known[0]).id,
    });
    if (!projectLevel) {
      for (const n of known) {
        for (const d of subtree(n, kids)) {
          if (d.mesh_key === null) continue;
          // Placement outranks size when both apply to the same node.
          if (tone === "placement" || !highlighted.has(d.id)) highlighted.set(d.id, tone);
        }
      }
    }
  }

  const toneOfTop = (top: SceneNode): Tone | null => {
    let found: Tone | null = null;
    for (const d of subtree(top, kids)) {
      const t = highlighted.get(d.id);
      if (t === "placement") return t;
      if (t) found = t;
    }
    return found;
  };
  const plateNumber = new Map(scene.plates.map((p) => [p.id, p.ui_number]));
  const objects: ObjectRow[] = tops.map((n) => {
    const sub = subtree(n, kids);
    return {
      id: n.id,
      label: labelOf.get(n.id) ?? "Object",
      plateText: n.plate.state === "known" ? `Plate ${plateNumber.get(n.plate.plate_id ?? "") ?? n.plate.plate_id}` : n.plate.state === "ambiguous" ? "Plate unclear" : "Plate unknown",
      roleText: n.role_context && n.role_context !== "part" ? roleWords(n.role_context) : "Part",
      tone: toneOfTop(n),
      hasGeometry: sub.some((d) => d.mesh_key !== null),
    };
  });

  const limitations = [...gate.reasons];
  for (const l of scene.limitations) {
    if (gate.covered.includes(l.code)) continue;
    const text = limitationText(l.code);
    if (!limitations.includes(text)) limitations.push(text);
  }
  const shown = objects.filter((o) => o.hasGeometry).length;
  const summary = `${shown} ${shown === 1 ? "object" : "objects"}, ${scene.counts.rendered_triangles.toLocaleString("en-US")} triangles`;
  return {
    gate, objects, findings, limitations, highlighted, summary, partial: scene.status === "partial", marginMm: scene.bed.edge_margin_mm,
  };
}

export function roleWords(role: VolumeRole): string {
  switch (role) {
    case "part": return "Part";
    case "modifier": return "Modifier";
    case "negative": return "Negative volume";
    case "support_enforcer": return "Support enforcer";
    case "support_blocker": return "Support blocker";
    default: return "Role unknown";
  }
}

// ---- Geometry for the viewer ---------------------------------------------------------------------------------------

// A mirrored instance (negative-determinant world matrix) keeps its triangle order. three.js reads the sign of the matrix
// determinant and flips the front face itself when drawing, and ray picking works in the mesh's own space. Reversing the
// triangles as well would turn the faces inward a second time.

const meshId = (k: { part: string; object_id: string }) => `${k.part}\u0000${k.object_id}`;

export function buildViewScene(scene: SceneV1, model: SceneModel): ViewScene {
  const xs = scene.bed.polygon_mm.map((p) => p[0]);
  const ys = scene.bed.polygon_mm.map((p) => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const decoded = new Map<string, ReturnType<typeof decodeMesh>>();
  const meshes = new Map(scene.meshes.map((m) => [meshId(m.key), m]));
  const byId = new Map(scene.nodes.map((n) => [n.id, n]));
  const labelOf = new Map(model.objects.map((o) => [o.id, o.label]));
  const topOf = (n: SceneNode): SceneNode => {
    let cur = n;
    for (let guard = 0; cur.parent_id !== null && guard < 80; guard++) {
      const parent = byId.get(cur.parent_id);
      if (!parent) break;
      cur = parent;
    }
    return cur;
  };

  const objects: ViewObject[] = [];
  for (const node of scene.nodes) {
    if (!node.mesh_key) continue;
    const mesh = meshes.get(meshId(node.mesh_key));
    if (!mesh) continue;
    let data = decoded.get(meshId(mesh.key));
    if (!data) { data = decodeMesh(mesh); decoded.set(meshId(mesh.key), data); }
    const tone = model.highlighted.get(node.id);
    const contextRole = node.role_context;
    const indices = data.indices;
    const parts: ViewPart[] = mesh.volumes.map((v) => {
      const role = contextRole ?? v.role;
      const color = role !== "part" ? COLORS.other : tone ? COLORS[tone] : COLORS.part;
      return {
        name: roleWords(role), positions: data!.positions, color,
        indices: indices.subarray(v.triangle_start * 3, (v.triangle_start + v.triangle_count) * 3),
      };
    }).filter((p) => p.indices.length > 0);
    if (!parts.length) continue;
    const transform = node.world_mm.slice();
    transform[12] -= minX;
    transform[13] -= minY;
    objects.push({ id: node.id, name: labelOf.get(topOf(node).id) ?? "Object", transform, parts });
  }

  const margin = scene.bed.edge_margin_mm;
  const w = maxX - minX, d = maxY - minY;
  const marginLoop: [number, number, number][] | null = margin > 0 && w > 2 * margin && d > 2 * margin
    ? [[margin, margin, 0.05], [w - margin, margin, 0.05], [w - margin, d - margin, 0.05], [margin, d - margin, 0.05]]
    : null;
  return {
    bed: { widthMm: w, depthMm: d, heightMm: scene.bed.height_mm ?? 270 },
    objects, marginLoop,
    bedAlert: [...model.highlighted.values()].includes("placement"),
  };
}
