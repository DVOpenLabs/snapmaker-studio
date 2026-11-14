import type { PassportDocument, Verification } from "./types";

/** Synthetic data for tests: made-up names and digests, not a capture of any real job. */
const SHA = (c: string) => c.repeat(64);

export const SAMPLE_PASSPORT: PassportDocument = {
  schema_version: "passport/1", passport_id: "pp:synthetic0000000000000000000000000000000000",
  created_at: "2026-01-01T00:00:00Z",
  artifacts: [
    { artifact_id: `sha256:${SHA("a")}:10`, role: "original", name: "bracket.3mf", bytes: { sha256: SHA("a"), size_bytes: 10 } },
    { artifact_id: `sha256:${SHA("b")}:12`, role: "prepared", name: "bracket_u1.3mf", bytes: { sha256: SHA("b"), size_bytes: 12 } },
    { artifact_id: `sha256:${SHA("c")}:14`, role: "sliced", name: "bracket_u1.gcode", bytes: { sha256: SHA("c"), size_bytes: 14 } },
  ],
  derivations: [], recipes: [], material_mappings: [], losses: [],
};

export function sampleVerification(over: Partial<Verification> = {}): Verification {
  return {
    passport_id: SAMPLE_PASSPORT.passport_id,
    artifacts: [
      { artifact_id: "a", name: "bracket.3mf", role: "original", size_bytes: 10, sha256: SHA("a"), bytes: "same", chain: "intact", reasons: [] },
      { artifact_id: "b", name: "bracket_u1.3mf", role: "prepared", size_bytes: 12, sha256: SHA("b"), bytes: "same", chain: "intact", reasons: [] },
      { artifact_id: "c", name: "bracket_u1.gcode", role: "sliced", size_bytes: 14, sha256: SHA("c"), bytes: "same", chain: "intact", reasons: [] },
    ],
    derivations: [
      { derivation_id: "d1", output: "bracket_u1.3mf", inputs: [{ kind: "artifact", name: "bracket.3mf" }], producer: { tool: "user", version: null }, witness: "declared", declared_by: "user", declared_mismatch: false, status: "intact" },
      { derivation_id: "d2", output: "bracket_u1.gcode", inputs: [{ kind: "artifact", name: "bracket_u1.3mf" }], producer: { tool: "user", version: null }, witness: "declared", declared_by: "user", declared_mismatch: false, status: "intact" },
    ],
    recipes_retained: ["synthetic:mix-a"], material_mappings_retained: ["slot:0"],
    losses: [{ kind: "recipe", id: "synthetic:from-the-future", reason: "unknown_schema_version" },
             { kind: "material_mapping", id: "project:1:2", reason: "field_not_retained:note" }],
    note: "A match means the bytes are the same as the passport recorded. A declared link is the declarer's statement; Studio did not watch the file being made.",
    summary: { all_intact: true, intact: ["bracket.3mf", "bracket_u1.3mf", "bracket_u1.gcode"], invalidated: [], unverified: [], declared_mismatch: [] },
    ...over,
  };
}

export function invalidatedVerification(): Verification {
  const base = sampleVerification();
  return sampleVerification({
    artifacts: [
      { ...base.artifacts[0], bytes: "changed", chain: "invalidated", reasons: [{ code: "bytes_changed", artifact: "bracket.3mf" }] },
      { ...base.artifacts[1], chain: "invalidated", reasons: [{ code: "ancestor_changed", artifact: "bracket.3mf" }] },
      { ...base.artifacts[2], chain: "invalidated", reasons: [{ code: "ancestor_changed", artifact: "bracket.3mf" }] },
    ],
    derivations: [{ ...base.derivations[0], status: "invalidated", declared_mismatch: true }, base.derivations[1]],
    summary: { all_intact: false, intact: [], invalidated: ["bracket.3mf", "bracket_u1.3mf", "bracket_u1.gcode"], unverified: [], declared_mismatch: ["bracket_u1.3mf"] },
  });
}
