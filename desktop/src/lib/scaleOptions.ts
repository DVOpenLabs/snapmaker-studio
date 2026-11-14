// Pure helpers for the Scale Doctor "Size Options Ladder". No React, no I/O —
// keeps the rendering logic unit-testable. Advisory only.
import type { ScaleOption, ScaleOptionsResult, ScalePartDims } from "@/api";

export const SCALE_LADDER_COPY = {
  groupSame: "Use the same scale on all related parts.",
  groupSeparate:
    "Do not scale related plates differently if they need to fit together.",
  theoretical:
    "The theoretical max leaves almost no room for brim, bed adhesion, or placement error.",
  notGuarantee: "This is a readiness estimate, not a guarantee of print success.",
};

export function recommendBlurb(r: ScaleOptionsResult): string {
  const pct = r.recommended_scale_percent;
  if (pct == null) return "";
  if ((r as { placement_verified?: boolean }).placement_verified) {
    return `Largest verified scale that stays on the plate: ${pct}%.`;
  }
  return `Largest fit by size only: ${pct}%. Snapmaker Orca can still reject a scale because `
    + `where the object sits on the plate also matters — check it in Snapmaker Orca after scaling.`;
}

// The green "recommended" badge only appears when placement is actually verified —
// a size-only fit is never marked recommended (Orca may reject it on placement).
export function isRecommended(o: ScaleOption, r: ScaleOptionsResult): boolean {
  return !!(r as { placement_verified?: boolean }).placement_verified
    && r.recommended_scale_percent != null && o.scale_percent === r.recommended_scale_percent;
}

export function isCaution(o: ScaleOption): boolean {
  return o.risk_level === "high" || /not recommended/i.test(o.recommendation);
}

export function riskLabel(risk: ScaleOption["risk_level"]): string {
  return risk === "low" ? "Recommended" : risk === "medium" ? "Tight" : "Risky";
}

export function fmtDims(d: { x: number; y: number; z: number }): string {
  return `${d.x.toFixed(1)} × ${d.y.toFixed(1)} × ${d.z.toFixed(1)} mm`;
}

export function partLabel(p: ScalePartDims): string {
  return p.plate_index != null ? `Plate ${p.plate_index}` : p.name;
}
