export type EvidenceKind = "file" | "engine" | "estimate" | "orca";

// `file` maps to preflight `confirmed` and guide certainty `confirmed`: Studio read
// the value directly from the file. `engine` maps to Studio's own preflight check;
// its guide certainty is `likely` when the check supports a conclusion. `estimate`
// maps to preflight derived output and guide certainty `informational`. `orca` is
// advice to verify in Snapmaker Orca; it makes no claim about Orca's behavior.
// The existing UI phrase "Manual check in Orca required" remains the manual-review
// wording; this label is only the provenance badge for the accompanying explanation.

const LABELS: Record<EvidenceKind, string> = {
  file: "Read from your file",
  engine: "Studio's check",
  estimate: "Estimate",
  orca: "Verify in Snapmaker Orca",
};

export function evidenceKindLabel(kind: EvidenceKind | string | undefined): string | null {
  const hasOwn = (Object as unknown as { hasOwn: (value: object, key: PropertyKey) => boolean }).hasOwn;
  return typeof kind === "string" && hasOwn(LABELS, kind) ? LABELS[kind as EvidenceKind] : null;
}
