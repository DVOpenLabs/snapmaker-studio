import type { Topology } from "./extTypes";

/** Mirror of the backend `setup_report/1` document (backend/snapstudio_core/setup_view.py). */
export type CapabilityStateName = "available" | "unavailable" | "stale" | "unknown";

export interface SetupCapability {
  key: string;
  label: string;
  state: CapabilityStateName;
  reason: string;
  /** True when every observation behind it was restored from an earlier session. */
  historical: boolean;
}

export interface SetupObservationRow {
  observation_id: string;
  subject: { kind: string; id: string };
  field: string;
  value: unknown;
  state: "fresh" | "ageing" | "stale" | "unknown" | "unusable";
  age_s: number | null;
  usable_for_loadout: boolean;
  reason: string;
  historical: boolean;
  observed_at: string | null;
  received_at: string;
}

export interface SetupCounts {
  physical_heads: number | null;
  logical_slots: number;
  lanes: number;
  lanes_with_known_reach: number;
  complete: boolean;
}

export type AssignabilityVerdict = "can_match" | "cannot_match" | "unknown";
export interface SetupAssignability {
  verdict: AssignabilityVerdict;
  assignable: boolean | null;
  text: string;
  requested: number;
  bound: { min: number; max: number } | null;
  per_requirement: { slot_id: string; candidates: string[]; result: "ok" | "contended" | "unreachable" | "unknown" }[];
  reasons: string[];
}

export interface SetupEntry {
  label: string;
  status: "ok" | "unavailable" | "unrecognised";
  kind: string | null;
  variant: string | null;
  adapter_id: string | null;
  source_version: string | null;
  reason: string | null;
  reason_text: string | null;
  counts: SetupCounts | null;
  topology: Topology | null;
  capabilities: SetupCapability[];
  observations: SetupObservationRow[];
  unknowns: string[];
  assignability: SetupAssignability | null;
}

export interface LegacyLimitation { applies: boolean; reasons: string[]; text: string | null }

export interface SetupReport {
  schema_version: "setup_report/1";
  entries: SetupEntry[];
  legacy_limitation: LegacyLimitation;
  inputs_revision: { revision: string; [input: string]: unknown };
  advisory: string;
}

export interface HostReadSummary {
  status: string; kind: string | null; variant: string | null; adapter_id: string | null;
  reason: string | null; requests: string[]; retries: number; notes: string[];
}

export interface EvaluateResponse { report: SetupReport; read: HostReadSummary }
export interface ListResponse {
  adapters: { id: string; kind: string; versions_supported: string[]; ttl_s: number }[];
  coverage: string;
}

export interface EvaluateRequest {
  host: string;
  port?: number;
  /** OctoPrint key: sent in this one request, never stored. */
  api_key?: string;
  requirements?: { material?: string | null; colour?: string | null }[];
}
