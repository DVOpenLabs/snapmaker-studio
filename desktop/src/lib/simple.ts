// Novice-first presentation helpers — turn engine values into beginner language.
// Pure functions over the existing /doctor result; no new data, no jargon.

export type Tone = "ready" | "repairable" | "convertible" | "risk";

/** Where the design came from, in plain words. */
export function familyLabel(family: string | null | undefined): string {
  switch ((family || "").toLowerCase()) {
    case "bambu":
    case "bambu/orca":
    case "orca": return "from a Bambu / Orca design";
    case "prusa": return "from a PrusaSlicer design";
    case "stl": return "a plain model (STL)";
    default: return "a 3D design";
  }
}

/** Verdict → friendly status (no READY/REPAIRABLE jargon). */
export function verdictStatus(verdict: string | null | undefined, prepareBlocked?: boolean | null): { icon: string; label: string; tone: Tone } {
  // Readable but not preparable: Studio will refuse to prepare it, so it is neither "fixable" nor "compatible".
  if (prepareBlocked && (verdict || "").toUpperCase() !== "HIGH_RISK") return { icon: "⚠️", label: "Review in Orca first", tone: "risk" };
  switch ((verdict || "").toUpperCase()) {
    case "READY": return { icon: "✅", label: "U1 compatible", tone: "ready" };
    case "REPAIRABLE": return { icon: "🛠", label: "Needs a fix first", tone: "repairable" };
    case "CONVERTIBLE": return { icon: "✨", label: "Can prepare a U1 copy", tone: "convertible" };
    case "HIGH_RISK": return { icon: "⚠️", label: "Review before printing", tone: "risk" };
    default: return { icon: "•", label: "Checking…", tone: "convertible" };
  }
}

/** The badge/stars headline when the readiness report says setup review remains. A compatible
 *  profile stays compatible (the Doctor's verdict is never rewritten); the headline says "review",
 *  using the readiness wording, not the unusable-project (HIGH_RISK) mapping. */
export function headlineWithReadiness(
  base: { icon: string; label: string; tone: Tone } | null,
  setupRisk: boolean,
): { icon: string; label: string; tone: Tone } | null {
  if (!base || !setupRisk || base.tone !== "ready") return base;
  return { icon: "⚠️", label: "Review before printing", tone: "repairable" };
}

/** "N color" / "N colors", guarding nulls. */
export function colorsLabel(n: number | null | undefined): string | null {
  if (n == null) return null;
  return `${n} color${n === 1 ? "" : "s"}`;
}

export function partsLabel(n: number | null | undefined): string | null {
  if (n == null) return null;
  return `${n} part${n === 1 ? "" : "s"}`;
}
