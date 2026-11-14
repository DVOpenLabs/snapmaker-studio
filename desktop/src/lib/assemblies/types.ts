/** Mirror of the report returned by POST /assemblies/evaluate (backend/snapstudio_core/assemblies/evaluate.py). */
export type Verdict = "enough" | "shortage" | "stale" | "unknown";

export interface SpoolRef {
  provider_instance_id: string;
  provider_spool_id: string;
}

export interface TileSlotRow {
  slot: string;
  role: string | null;
  grams: number | null;
  spool: SpoolRef | null;
  unresolved: "no_role" | "ambiguous_role" | "no_binding" | null;
}

export interface TileReport {
  tile_id: string;
  name: string;
  plate: string | null;
  part_id: string | null;
  usage_source: "declared" | "slot_usage" | "gcode_facts" | null;
  scale: number | null;
  library: { status: "linked" | "changed" | "missing" | "unverified" | "unlinked"; detail: string };
  attribution: Record<string, string | null>;
  slots: TileSlotRow[];
  need_known_g: number;
  need_complete: boolean;
  unknown_slots: string[];
}

export interface SpoolReport {
  spool: SpoolRef;
  same_spool_as: SpoolRef[];
  roles: string[];
  remaining_g: number | null;
  supply_state: "usable" | "stale" | "unknown";
  verdict: Verdict;
  reason: string;
  need_known_g: number;
  need_complete: boolean;
  unknown_tiles: string[];
  starving_tiles: string[];
  shortfall_g: number | null;
  tiles: { tile_id: string; grams: number; unknown: boolean; roles: string[] }[];
}

export interface AssemblyReport {
  name: string;
  advisory: string;
  verdict: Verdict;
  tiles: TileReport[];
  spools: SpoolReport[];
  unresolved: { tile_id: string; slot: string; grams: number | null; reason: string; roles: string[] }[];
  roles: { role: string; tiles: string[]; plates: string[]; shared_across_plates: boolean; spool: SpoolRef | null }[];
  parts: { missing: { part_id: string; name: string }[]; unlisted_tiles: string[] };
  seam_scale: { status: "consistent" | "mismatch" | "unknown"; known: { tile_id: string; scale: number }[]; unknown: string[] };
  attribution: Record<string, string | null>[];
}

export interface EvaluateResponse {
  report: AssemblyReport;
}

export interface SavedAssembly {
  id: number;
  name: string;
  tiles: number;
  revision: number;
  updated_at: string;
}

export interface SaveResponse {
  id: number;
  revision: number;
  assembly: unknown;
}
