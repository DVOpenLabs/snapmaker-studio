import type { BytesState, ChainState, PassportLoss, VerifiedArtifact, VerifiedDerivation } from "./types";

export const CHAIN_LABEL: Record<ChainState, string> = {
  intact: "Matches the passport", invalidated: "Invalidated", unverified: "Not verified",
};
export const BYTES_LABEL: Record<BytesState, string> = {
  same: "Same bytes", changed: "Bytes changed", missing: "File not found",
  unreadable: "Could not read", unverified: "Not located",
};
const ROLE_LABEL: Record<string, string> = {
  original: "Original", prepared: "Prepared copy", sliced: "Sliced output", generated: "Generated", settings: "Settings",
};
const LOSS_REASON: Record<string, string> = {
  unknown_schema_version: "its format version is not known to this build",
  missing_schema_version: "it has no format version",
  bad_slot_ref: "the slot reference is not valid",
  duplicate: "it repeats an earlier entry",
  not_a_list: "it was not a list",
  dangling_ref: "it refers to a file that is not in the passport",
  bad_material: "the material is not valid", bad_colour: "the colour is not valid", bad_spool: "the spool is not valid",
};

export function roleLabel(role: string): string { return ROLE_LABEL[role] ?? role; }

/** "abcdef123456..." from a full sha256. */
export function shortSha(sha: string): string { return sha.length > 12 ? `${sha.slice(0, 12)}...` : sha; }

export function reasonText(reason: { code: string; artifact: string }): string {
  switch (reason.code) {
    case "bytes_changed": return `${reason.artifact} has different bytes than the passport recorded.`;
    case "ancestor_changed": return `It was made from ${reason.artifact}, which has changed.`;
    case "bytes_missing": case "ancestor_missing": return `${reason.artifact} was not found, so this cannot be checked.`;
    case "bytes_unverified": case "ancestor_unverified": return `${reason.artifact} was not located, so this cannot be checked.`;
    case "bytes_unreadable": case "ancestor_unreadable": return `${reason.artifact} could not be read.`;
    default: return reason.code;
  }
}

export function lossText(loss: PassportLoss): string {
  const kind = loss.kind === "material_mapping" ? "Material mapping" : loss.kind === "recipe" ? "Recipe" : loss.kind;
  if (loss.reason.startsWith("field_not_retained:")) {
    return `${kind} ${loss.id}: the field "${loss.reason.slice("field_not_retained:".length)}" is not kept.`;
  }
  return `${kind} ${loss.id} was not carried over: ${LOSS_REASON[loss.reason] ?? loss.reason}.`;
}

/** One sentence for the chain as a whole. Unknown stays unknown: nothing is "all good" unless every file matched. */
export function chainSummary(artifacts: VerifiedArtifact[]): string {
  if (artifacts.length === 0) return "No files in the passport.";
  const bad = artifacts.filter((a) => a.chain === "invalidated");
  if (bad.length > 0) return `${bad.map((a) => a.name).join(", ")} no longer match what the passport recorded.`;
  const unknown = artifacts.filter((a) => a.chain === "unverified");
  if (unknown.length > 0) return `${unknown.length} of ${artifacts.length} files could not be checked.`;
  return "Every file matches the bytes the passport recorded.";
}

export function derivationText(d: VerifiedDerivation): string {
  const from = d.inputs.map((i) => i.name).join(" + ");
  const who = d.witness === "declared" ? `declared${d.declared_by ? ` by ${d.declared_by}` : ""}` : "seen by Studio";
  const mismatch = d.declared_mismatch === true ? " A parent file here has different bytes than declared." : "";
  return `${d.output} from ${from} (${who}).${mismatch}`;
}
