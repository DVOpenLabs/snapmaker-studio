/** Mirror of the backend `passport/1` document and the verification report
 *  (backend/snapstudio_core/passport/). Paths never appear in a passport: names only. */
export type ChainRole = "original" | "prepared" | "generated" | "sliced" | "settings";
export type BytesState = "same" | "changed" | "missing" | "unreadable" | "unverified";
export type ChainState = "intact" | "invalidated" | "unverified";

export interface PassportLoss { kind: string; id: string; reason: string }
export interface PassportDiagnostic { code: string; field: string; severity: "error" | "warning" | "note" }

export interface PassportDocument {
  schema_version: "passport/1";
  passport_id: string;
  created_at: string;
  artifacts: { artifact_id: string; role: string; name: string; bytes: { sha256: string; size_bytes: number } }[];
  derivations: unknown[];
  recipes: { recipe_id: string; execution_supported: boolean | null }[];
  material_mappings: { slot_ref: string; material?: string; colour?: string }[];
  losses: PassportLoss[];
}

export interface VerifiedArtifact {
  artifact_id: string; name: string; role: string; size_bytes: number; sha256: string;
  bytes: BytesState; chain: ChainState; reasons: { code: string; artifact: string }[];
}
export interface VerifiedDerivation {
  derivation_id: string; output: string; inputs: { kind: string; name: string }[];
  producer: { tool: string; version: string | null }; witness: "local" | "declared"; declared_by: string | null;
  declared_mismatch: boolean | null; status: ChainState;
}
export interface Verification {
  passport_id: string; artifacts: VerifiedArtifact[]; derivations: VerifiedDerivation[];
  recipes_retained: string[]; material_mappings_retained: string[]; losses: PassportLoss[]; note: string;
  summary: { all_intact: boolean; intact: string[]; invalidated: string[]; unverified: string[]; declared_mismatch: string[] };
}

export interface BuildEntry { path: string; role: ChainRole }
export interface BuildRequest { entries: BuildEntry[]; recipes?: unknown; material_mappings?: unknown }
export interface BuildResponse {
  passport: PassportDocument | null; paths: Record<string, string>;
  diagnostics: PassportDiagnostic[]; losses: PassportLoss[];
}
export interface VerifyRequest { passport: PassportDocument; paths?: Record<string, string> }
export interface VerifyResponse { verification: Verification | null; diagnostics: PassportDiagnostic[] }
