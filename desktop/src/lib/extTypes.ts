export type DiagnosticSeverity = "error" | "warning" | "note";
export interface Diagnostic { code: string; field: string; severity: DiagnosticSeverity }
export interface Decoded<T> {
  schema_version: string | null;
  value: T | null;
  diagnostics: Diagnostic[];
  valid_for_evaluation: boolean;
  raw?: unknown;
}

export type LaneState = "loaded" | "empty" | "uncertain" | "unknown";
export interface SpoolRef { provider_instance_id: string; provider_spool_id: string }
export interface LaneOccupancy {
  lane_id: string; spool: SpoolRef | null; state: LaneState; observation_id: string | null;
}
export interface PhysicalToolhead { id: string; index: number; nozzle_mm: number | null; evidence: string[] }
export interface Lane {
  id: string; unit_id: string; index: number; reachable_heads: string[] | null;
  path: string[] | null; state: LaneState; occupancy: LaneOccupancy | null;
}
export interface FeederUnit { id: string; kind: string; source_version: string | null; lanes: Lane[] }
export interface LogicalSlot { id: string; index: number; binding: string | null; nozzle_mm: number | null }
export interface SlotBinding { slot_id: string; target: string | null; evidence: string[] }
export interface Topology {
  schema_version: "topology/1"; snapshot_id: string; received_at: string; observed_at: string | null;
  mapping_revision: string | null; heads: PhysicalToolhead[]; units: FeederUnit[]; slots: LogicalSlot[];
  bindings: SlotBinding[]; complete: boolean; evidence: string[]; diagnostics: Diagnostic[];
}

export type FreshnessState = "fresh" | "ageing" | "stale" | "unknown" | "unusable";
/** usable_for_loadout is false for historical or history_uncertain observations; reason may say history is uncertain. */
export interface Freshness { state: FreshnessState; age_s: number | null; usable_for_loadout: boolean; reason: string }
export type MaterialProvenance = "rfid" | "user" | "provider" | "project" | "derived" | "unknown";
export interface MaterialField { value: unknown; provenance: MaterialProvenance; observation_id: string; freshness: Freshness }
export interface MaterialFact { field: string; value: unknown; provenance: MaterialProvenance; observation_id: string }
export interface MaterialView {
  schema_version: "material_view/1"; spool: SpoolRef | null; fields: Record<string, MaterialField>;
  conflicts: { field: string; a: MaterialFact; b: MaterialFact }[]; diagnostics: Diagnostic[];
}

export interface Observation {
  schema_version: "observation/1"; observation_id: string;
  subject: { kind: "lane" | "head" | "slot" | "spool" | "host" | "file"; id: string };
  field: string; value: unknown;
  source: { provider_instance_id: string; kind: string; source_version: string | null; snapshot_id: string | null };
  source_kind: "live_query" | "cached_record"; observed_at: string | null; received_at: string;
  ttl_s: number | null; ageing_ok: boolean; historical: boolean;
  /** Emitted only when true: the tracker lost history, so freshness.usable_for_loadout is withheld (display state unchanged). */
  history_uncertain?: boolean;
}

export type ArtifactRole = "original" | "prepared" | "generated" | "sliced" | "image" | "settings" | "lut_ref" | "calibration";
export interface ArtifactRef {
  schema_version: "artifact_ref/1"; artifact_id: string; role: ArtifactRole;
  bytes: { sha256: string; size_bytes: number }; name: string;
  locator: { path: string; mtime_ns: number } | null; created_at: string;
}
export interface Derivation {
  schema_version: "derivation/1"; derivation_id: string; output: string;
  inputs: { kind: "image" | "project" | "settings" | "recipe" | "lut" | "calibration_basis" | "artifact"; ref: string }[];
  producer: { tool: string; version: string | null }; witness: "local" | "declared";
  declared_by: string | null; created_at: string;
}
export interface VirtualRecipe {
  schema_version: "virtual_recipe/1"; recipe_id: string; generator: { name: string; version: string | null };
  kind: string; components: { slot_ref: string; ratio: number | null; ratio_kind: "mass" | "area" | "layer" | "unknown"; ratio_invalid?: true }[];
  simulated: true; execution_supported: boolean | null;
}
export type CapabilityState = "supported" | "unsupported" | "unknown" | "conflicting";
export interface Capability {
  key: string; state: CapabilityState;
  scope: { generator: string | null; host: string | null; process: string | null; slicer: string | null; version: string | null };
  evidence: string[];
}
export interface CapabilitySet { schema_version: "capability_set/1"; capabilities: Record<string, Capability[]> }

/** Revision envelope attached to evaluations; additional keys identify their inputs. */
export interface InputsRevision { revision: string; [input: string]: unknown }
export type CapabilityEvaluationResult = {
  key: string; result: "satisfied" | "unmet" | "unknown"; matched: Capability | null; evidence: string[];
};
export interface CapabilityEvaluation {
  inputs_revision: InputsRevision | null;
  results: CapabilityEvaluationResult[];
}

export type JobState = "queued" | "running" | "cancel_requested" | "succeeded" | "failed" | "cancelled" | "interrupted";
export interface JobStatus {
  job_id: string; kind: string; state: JobState; inputs_revision: string; wedged: boolean; timed_out: boolean; late: boolean;
  stage: string | null; fraction: number | null; error: { code: string; message: string } | null;
  result_available: boolean; note?: string; restored?: boolean;
}
