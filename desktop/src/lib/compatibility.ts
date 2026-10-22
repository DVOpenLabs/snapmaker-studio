// Pure presentation logic + copy for the Compatibility Doctor. No JSX so the
// beginner wording and finding-ordering are unit-testable. Read-only feature:
// Studio diagnoses and explains; it never claims to auto-fix.
import type { CompatibilityFinding } from "@/api";

export const COMPAT_COPY = {
  title: "Compatibility Doctor",
  subtitle: "Checks a 3MF for common Snapmaker U1 and Snapmaker Orca problems — read-only.",
  cleanTitle: "No known compatibility issues",
  intro: "Open a 3MF project and Studio reads its settings to spot issues before you slice.",
  // Explicitly NOT an auto-fix claim:
  readOnlyNote: "Read-only check. Create a U1 profile copy when issues are repairable.",
  beginnerForeign: "This file likely carries settings from another printer.",
  beginnerImport: "Import the model into a clean Snapmaker U1 project instead of opening the foreign 3MF as the active project.",
  beginnerRelE: "Your profile uses relative extrusion but may not reset the extruder each layer.",
} as const;

const RANK: Record<string, number> = { error: 0, warning: 1, info: 2 };

/** Errors first, then warnings, then info; stable within a severity. */
export function sortFindings(findings: CompatibilityFinding[]): CompatibilityFinding[] {
  return [...findings].sort((a, b) => (RANK[a.severity] ?? 9) - (RANK[b.severity] ?? 9));
}

export function severityLabel(sev: string): string {
  if (sev === "error") return "Needs attention";
  if (sev === "warning") return "Heads up";
  return "Note";
}

/** Brand status token for a severity (used for swatch/border colour). */
export function severityToken(sev: string): string {
  if (sev === "error") return "--stage-input";       // risk-ish
  if (sev === "warning") return "--doctor-cost";      // amber-ish
  return "--doctor-project";
}

export interface CompatCounts { errors: number; warnings: number; info: number; total: number; }
export function countFindings(findings: CompatibilityFinding[]): CompatCounts {
  const c: CompatCounts = { errors: 0, warnings: 0, info: 0, total: findings.length };
  for (const f of findings) {
    if (f.severity === "error") c.errors++;
    else if (f.severity === "warning") c.warnings++;
    else c.info++;
  }
  return c;
}

/** Why Prepare is off for a compatibility result, from the engine's one eligibility record:
 *  "unreadable" = Studio cannot open it as a project (project.unreadable); "blocked" = readable
 *  but Studio would refuse to prepare it (prepare.blocked). Either one turns every Prepare entry
 *  point off. */
export type PrepareGate = "open" | "blocked" | "unreadable";
export function prepareGate(findings: CompatibilityFinding[] | null | undefined): PrepareGate {
  const ids = new Set((findings ?? []).map((f) => f.id));
  if (ids.has("project.unreadable")) return "unreadable";
  if (ids.has("prepare.blocked")) return "blocked";
  return "open";
}
