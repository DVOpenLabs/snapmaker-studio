import { callExt } from "./extApi";

export interface CreativeNamedPart { name: string; sha256: string }

export interface CreativeRecipeComponent { source: string; ratio?: unknown; ratio_kind?: string }

export interface CreativeRecipe {
  recipe_id: string;
  generator: { name: string; version: string | null };
  kind: string;
  components: CreativeRecipeComponent[];
  simulated: boolean;
  execution_supported: boolean | null;
}

export interface CreativeOrigin {
  generator: string;
  status: "detected" | "chosen" | "ambiguous" | "unknown";
  candidates: string[];
}

/** What one supported format reads and does not read. Mirrors SUPPORTED_FORMATS in the engine. */
export interface CreativeFormatInfo {
  key: string;
  label: string;
  carrier: string;
  selection: "automatic" | "manual only";
  identified_by: string[];
  reads: string[];
  kept_untouched: string[];
  not_read: string[];
  /** Why Prepare may refuse files of this format, when it does. Absent when there is nothing to say. */
  prepare_limits?: string[];
  upstream: string | null;
}

export interface CreativeExplanation {
  kind: "unknown_origin" | "ambiguous_origin";
  seen: string;
  not_supported: string;
  what_to_do: string[];
}

export interface CreativeSourceInfo { name: string; size_bytes: number; sha256_before: string; sha256_after: string; unchanged: boolean }

export interface CreativeInspectResponse {
  origin: CreativeOrigin;
  understood: string[];
  facts?: Record<string, Record<string, unknown>>;
  passed_through: CreativeNamedPart[];
  could_not_interpret: string[];
  missing: string[];
  diagnostics: string[];
  recipes: CreativeRecipe[];
  physical_slots_needed: number | null;
  format_info?: CreativeFormatInfo[];
  explanation?: CreativeExplanation | null;
  source: CreativeSourceInfo;
  evidence: string;
  advisory: string;
}

export interface CreativeComparison { preserved: string[]; modified: string[]; dropped: string[]; added: string[] }

export interface CreativeVerification {
  opens_as_zip: boolean;
  problem?: string;
  size_bytes?: number;
  sha256?: string;
  members?: CreativeNamedPart[];
  comparison?: CreativeComparison;
  counts?: Record<keyof CreativeComparison, number>;
  settings?: { removed_keys: string[]; removed_count?: number; changed_keys: string[]; changed_count?: number; added_key_count: number };
  per_face_paint?: { original_triangles: number | null; exported_triangles: number | null; kept: boolean | null };
}

export interface CreativePrepareDone {
  prepared: true;
  origin: CreativeOrigin;
  /** `local_path` is the one field that names a location; the UI uses it to link the copy to its job (Passport can then show it in a path field, like every job path). */
  output: { name: string; local_path: string; location: "studio_default" | "chosen"; location_label: string; in_source_folder: boolean };
  prepare: { mode: string; validated_ok: boolean; errors: string[]; compat_changed: unknown[]; mapped_to_u1: unknown[]; could_not_carry: unknown[]; warnings: unknown[] };
  verification: CreativeVerification;
  loss_notes: string[];
  original: { name: string; sha256_before: string; sha256_after: string; original_unchanged: boolean };
  source: CreativeSourceInfo;
  advisory: string;
}

export interface CreativePrepareRefused {
  prepared: false;
  refusal: { kind: string; seen: string; not_supported: string; what_to_do: string[]; problems?: string[] };
  origin: CreativeOrigin;
  source: CreativeSourceInfo;
  advisory: string;
}

export type CreativePrepareResponse = CreativePrepareDone | CreativePrepareRefused;

export const CREATIVE_FORMATS = ["auto", "ditherforge", "kromacut", "sindricad", "forcaslicer", "lixnix", "fullspectrum", "imagemap", "lumina"] as const;
export type CreativeFormat = (typeof CREATIVE_FORMATS)[number];

/** The request body for one inspection. A blank path is a sentence for the person, not a request. */
export function buildInspectBody(path: string, format: CreativeFormat = "auto"): { path: string; format?: CreativeFormat } {
  const trimmed = path.trim().replace(/^"(.*)"$/, "$1");
  if (trimmed === "") throw new Error("Enter the path of a .3mf project file.");
  return format === "auto" ? { path: trimmed } : { path: trimmed, format };
}

/** The project path exactly as it is sent (surrounding quotes removed), so the job record names the file that was prepared. */
export const normalizedProjectPath = (path: string): string => buildInspectBody(path).path;

/** Inspect one local project file through the local service. Read-only; nothing is sent off this computer. */
export function inspectCreative(path: string, format: CreativeFormat = "auto"): Promise<CreativeInspectResponse> {
  return callExt<CreativeInspectResponse>("/creative/inspect", buildInspectBody(path, format), "Creative project inspection");
}

/** The format list from the engine: what each format reads and does not. */
export function fetchCreativeFormats(): Promise<{ formats: CreativeFormatInfo[]; manual_only: string[]; note: string }> {
  return callExt("/creative/formats", {}, "Creative formats");
}

/** The request body for one Prepare. The output folder is sent only when the person typed one. */
export function buildPrepareBody(path: string, format: CreativeFormat = "auto", outDir = ""): { path: string; format?: CreativeFormat; out_dir?: string } {
  const body: { path: string; format?: CreativeFormat; out_dir?: string } = buildInspectBody(path, format);
  const folder = outDir.trim().replace(/^"(.*)"$/, "$1");
  if (folder !== "") body.out_dir = folder;
  return body;
}

/** Write a new prepared copy through the local service and compare it with the original. */
export function prepareCreative(path: string, format: CreativeFormat = "auto", outDir = ""): Promise<CreativePrepareResponse> {
  return callExt<CreativePrepareResponse>("/creative/prepare", buildPrepareBody(path, format, outDir), "Prepare a U1 copy");
}

export const GENERATOR_LABEL: Record<string, string> = {
  ditherforge: "DitherForge",
  kromacut: "Kromacut",
  sindricad: "SindriCAD",
  forcaslicer: "FOrcaSlicer",
  lixnix: "LixNix Full Multi-Nozzle",
  fullspectrum: "FullSpectrum",
  imagemap: "OrcaSlicer ImageMap",
  lumina: "Lumina Layers",
};

/** One sentence about where the project came from. Unknown stays unknown. */
export function originSentence(origin: CreativeOrigin): string {
  if (origin.status === "ambiguous") {
    const names = origin.candidates.map((c) => GENERATOR_LABEL[c] ?? c).join(" and ");
    return `Origin not decided: the file's markers or settings match ${names}.`;
  }
  if (origin.generator === "unknown") return "Origin unknown: Studio does not recognise the generator of this project.";
  const name = GENERATOR_LABEL[origin.generator] ?? origin.generator;
  return origin.status === "chosen" ? `Read as ${name} (your choice).` : `Looks like ${name}, from the markers or settings it contains.`;
}

function colours(value: unknown): string {
  return Array.isArray(value) ? value.map((c) => (typeof c === "string" ? c : "?")).join(", ") : "";
}

function named(items: unknown, key: string): string {
  if (!Array.isArray(items)) return "";
  return items.map((i) => {
    const row = i as Record<string, unknown>;
    return `${String(row.name ?? "unnamed")} (${key} ${String(row[key] ?? "unknown")})`;
  }).join(", ");
}

/** Plain lines for the facts a reader proved from the file. A fact that is absent produces no line. */
export function factLines(facts: Record<string, unknown> | undefined): string[] {
  if (!facts) return [];
  const out: string[] = [];
  const add = (label: string, value: unknown) => {
    if (value === undefined || value === null || value === "") return;
    out.push(`${label}: ${String(value)}`);
  };
  add("Written by (Application tag)", facts.application);
  add("Variant", facts.variant === "bambu_project" ? "Bambu-style project tag" : facts.variant);
  add("Objects in the build", facts.build_item_count);
  add("Body count", facts.body_count);
  add("Colour layer objects", facts.layer_object_count);
  if (facts.assembly_present === true) out.push("Layers are grouped in one assembly object");
  add("Layer height (mm)", facts.layer_height);
  add("First layer height (mm)", facts.first_layer_height);
  add("Triangles", facts.triangle_count);
  if (typeof facts.painted_triangle_count === "number") {
    out.push(facts.painted_triangle_count > 0
      ? `Per-face paint: ${facts.painted_triangle_count} painted triangle(s)`
      : "Per-face paint: none found");
  }
  if (Array.isArray(facts.paint_extruders_used) && facts.paint_extruders_used.length > 0) {
    add("Extruders used by paint", facts.paint_extruders_used.join(", "));
  }
  add("Objects", named(facts.objects, "extruder"));
  add("Bodies", named(facts.bodies, "extruder"));
  add("Parts", named(facts.parts, "extruder"));
  const palette = Array.isArray(facts.palette) ? facts.palette.map((p) => `${String((p as Record<string, unknown>).name)} ${String((p as Record<string, unknown>).colour)}`).join(", ") : "";
  add("Base materials", palette);
  add("Filament colours", colours(facts.filament_colour));
  add("Filament types", colours(facts.filament_type));
  add("Printer settings id", facts.printer_settings_id);
  return out;
}

export interface CreativeBucket { key: keyof CreativeComparison; title: string; note: string; items: string[]; total: number; truncated: boolean }

/**
 * The four buckets of the export comparison, in the order a person reads them. `total` is the engine's
 * own count (verification.counts) and falls back to the listed names only when the engine sent none;
 * `truncated` is true when the name list is shorter than the total.
 */
export function comparisonBuckets(v: CreativeVerification): CreativeBucket[] {
  const c = v.comparison;
  const bucket = (key: keyof CreativeComparison, title: string, note: string): CreativeBucket => {
    const items = c?.[key] ?? [];
    const total = v.counts?.[key] ?? items.length;
    return { key, title, note, items, total, truncated: total > items.length };
  };
  return [
    bucket("preserved", "Kept identical", "Same part name and same content fingerprint as the original."),
    bucket("modified", "Changed", "Same part name, different content."),
    bucket("dropped", "Dropped", "In the original, not in the copy."),
    bucket("added", "Added", "In the copy, not in the original."),
  ];
}

/** Project-settings totals from the engine's counts; the key lists are bounded and may be shorter. */
export function settingsTotals(s: NonNullable<CreativeVerification["settings"]>): { removed: number; changed: number; added: number } {
  return { removed: s.removed_count ?? s.removed_keys.length, changed: s.changed_count ?? s.changed_keys.length, added: s.added_key_count };
}
