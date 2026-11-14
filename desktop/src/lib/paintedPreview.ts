// What the painted 3D preview shows, as plain data.
//
// The engine returns geometry split by filament slot (`paintedpreview/1`). Colours are carried per slot
// so the same geometry can be shown with the colours the project lists ("Original") or with the spool
// colours the person has picked so far ("Proposed"). Nothing here guesses: a slot the project gives no
// colour stays neutral, a slot beyond the U1's toolheads stays visible and flagged, and a colour is a
// label for "which filament prints where", never a picture of the printed result.

export const U1_HEADS = 4;

export interface PreviewSlot {
  slot: number;                       // 1-based, as the project numbers them
  colour: string | null;              // the project's own colour for it, if it lists one
  declared: boolean;
  from_painting: boolean;
  from_assignment: boolean;
  painted_triangles: number;
  area_mm2: number;
  painted_area_mm2: number;
}

export interface PreviewPart { slot: number | null; triangles: number; positions_f32le_base64: string }
export interface PreviewMesh { key: string; parts: PreviewPart[] }
export interface PreviewInstance {
  id: string; object_node?: string; mesh: string; world_mm: number[]; label: string;
  instance_index: number; instance_count: number; build_index?: number | null;
}

export interface PaintedPreview {
  schema: string;
  available: boolean;
  state: "ok" | "unsupported" | "unreadable" | "limit";
  reason: string | null;
  kind: "painted" | "assigned" | "geometry" | null;
  bed: { polygon_mm: number[][] | null; height_mm: number | null } | null;
  slots: PreviewSlot[];
  unknown_default: boolean;
  meshes: PreviewMesh[];
  instances: PreviewInstance[];
  counts: { triangles_out: number; painted_triangles: number; leaves: number; malformed: number };
  notes: string[];
}

export type PreviewMode = "original" | "proposed" | "copy";

/** The neutral colour for surface whose filament the project does not state. */
export const NEUTRAL = "#9aa0a6";

/** Slot (1-based) → colour chosen so far, from the selections Prepare would be sent (their slots are 0-based). */
export function draftColours(selections: { slot: number; colour: string | null }[]): Record<number, string> {
  const out: Record<number, string> = {};
  for (const s of selections) if (s.colour && /^#[0-9a-f]{6}$/i.test(s.colour)) out[s.slot + 1] = s.colour.toUpperCase();
  return out;
}

export interface LegendRow {
  slot: number;
  /** The toolhead that prints this slot, or null when the slot is past the U1's four. */
  head: number | null;
  original: string | null;
  proposed: string | null;
  changed: boolean;
  /** False when the project lists the slot but nothing prints in it. */
  used: boolean;
  /** This slot's share of the surface that has a stated filament (one copy of each mesh), 0..1. */
  share: number | null;
  paintedAreaMm2: number;
}

export function legend(preview: PaintedPreview, draft: Record<number, string>): LegendRow[] {
  // Every slot is measured the same way: the surface of the mesh that prints in it, of one copy of each mesh.
  const total = preview.slots.reduce((sum, s) => sum + s.area_mm2, 0);
  return preview.slots.map((s) => {
    const original = s.colour ? s.colour.toUpperCase() : null;
    const proposed = draft[s.slot] ?? original;
    return {
      slot: s.slot,
      head: s.slot <= U1_HEADS ? s.slot : null,
      original,
      proposed,
      changed: !!draft[s.slot] && draft[s.slot] !== original,
      used: s.area_mm2 > 0 || s.painted_area_mm2 > 0,
      share: total > 0 ? s.area_mm2 / total : null,
      paintedAreaMm2: s.painted_area_mm2,
    };
  });
}

/** The colour to draw a slot in, per mode. Null slot (stated nowhere) and colourless slots are neutral. */
export function colourOf(rows: LegendRow[], mode: PreviewMode): (slot: number | null) => string {
  const bySlot = new Map(rows.map((r) => [r.slot, r]));
  return (slot) => {
    if (slot === null) return NEUTRAL;
    const row = bySlot.get(slot);
    return (mode === "proposed" ? row?.proposed : row?.original) ?? NEUTRAL;
  };
}

/** Placed objects, not meshes: a multi-part object is one object however many meshes it is made of. */
export function objectCount(p: PaintedPreview): number {
  return new Set(p.instances.map((i) => i.object_node ?? i.id)).size;
}

/** Slots past the U1's four that something actually prints in. A listed but unused fifth colour is the Materials pane's concern. */
export function beyondHeads(rows: LegendRow[]): LegendRow[] {
  return rows.filter((r) => r.head === null && r.used);
}

/** What the person is told when the preview cannot be drawn. Never a reason to doubt the rest of the screen. */
export function unavailableCopy(p: PaintedPreview | null, failed: boolean): string {
  if (failed || !p) return "Studio could not build the colour preview for this file. The plate view below is still correct.";
  if (p.available) return "";
  switch (p.state) {
    case "limit":
      return `${p.reason ?? "This project is too detailed for the preview."} The plate view below is unaffected.`;
    case "unreadable":
      return `${p.reason ?? "Studio could not read this file."} The plate view below is unaffected.`;
    default:
      return `${p.reason ?? "Studio does not draw this kind of project."} The plate view below is unaffected.`;
  }
}

/**
 * Whether what is drawn tells the person anything about painted coverage. A geometry-only drawing (an STL, or a
 * project with no filament information) shows the shape and nothing else, and says so.
 */
export function coverageClaim(p: PaintedPreview): "painted" | "assigned" | "geometry" {
  if (p.kind === "painted" && p.slots.some((s) => s.from_painting)) return "painted";
  if (p.kind === "assigned") return "assigned";
  return "geometry";
}

export function decodeFloat32(base64: string): Float32Array {
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Float32Array(bytes.buffer, 0, Math.floor(bytes.length / 4));
}

/** "34%" for a share, "<1%" when there is some but it rounds away, "—" when unknown. */
export function percent(share: number | null): string {
  if (share === null) return "—";
  if (share > 0 && share < 0.01) return "<1%";
  return `${Math.round(share * 100)}%`;
}
