// Single source of truth for "ready / clean / safe / pass" UI language (beta.19).
//
// Raw profile verdict (doctor.verdict) and validated_ok mean ONLY "profile compatible" /
// "structure validated" / "U1 profile copy saved" — they must NEVER drive ready language.
// Only readiness_report.ready may show "Ready for Orca review". Every readiness surface
// (Workspace, Batch, Projects, Source Wizard, Plate Remap, Intelligence Report) routes its
// "ready" wording through readinessView() so the honest report is the only authority.
import type { ReadinessReport } from "@/api";

export type ReadinessTone = "ready" | "risk" | "checking";

export interface ReadinessView {
  ready: boolean;
  tone: ReadinessTone;
  headline: string;          // user-facing headline
  badge: string;             // short chip label
  atRisk: string[];
  nextActions: string[];
}

export function readinessView(report: ReadinessReport | null | undefined): ReadinessView {
  if (!report) {
    return {
      ready: false, tone: "checking", headline: "Checking readiness…", badge: "Checking…",
      atRisk: [], nextActions: [],
    };
  }
  if (report.ready) {
    return {
      ready: true, tone: "ready", headline: "Ready for Orca review", badge: "Ready for Orca",
      atRisk: [],
      nextActions: ["Open in Snapmaker Orca to slice."],
    };
  }
  const atRisk = report.at_risk ?? [];
  const next = deriveNextActions(atRisk);
  return {
    ready: false, tone: "risk", headline: "Review before printing", badge: "Review needed",
    atRisk,
    nextActions: next.length ? next : ["Open in Snapmaker Orca and review before slicing."],
  };
}

function deriveNextActions(atRisk: string[]): string[] {
  const out: string[] = [];
  const blob = atRisk.join(" ").toLowerCase();
  if (blob.includes("toolhead") || blob.includes("colour") || blob.includes("color"))
    out.push("Plan colour swaps or remap to 4 colours in Snapmaker Orca.");
  if (blob.includes("support") || blob.includes("overhang"))
    out.push("Check / enable supports in Snapmaker Orca.");
  if (blob.includes("plate") || blob.includes("layout") || blob.includes("arrange"))
    out.push("Arrange all plates in Snapmaker Orca before slicing.");
  return out;
}

// Allowed wording for a converted/remapped/validated copy — profile/structure only.
// NEVER "U1-ready / clean / safe / ready to slice" from validated_ok alone.
export const PROFILE_COPY_SAVED = "U1 profile copy saved";
export const PROFILE_COPY_NEXT =
  "Open in Snapmaker Orca and review layout, supports and colours before slicing.";
