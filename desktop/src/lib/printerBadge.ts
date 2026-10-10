// The one-word state chip on the connected-printer card. It must agree with the health card below it and with the
// Intelligence Report's printer line: all three count the same conditions (the health result's `conditions`, one per
// condition id). "Healthy" is only shown when the firmware state is fine AND there are no concerns.
export interface BadgeInput {
  diag: { healthy?: boolean; klippy_state?: string | null } | null | undefined;
  /** Number of conditions the printer reported (`health.conditions.length`). */
  concerns: number;
}
export interface Badge { label: string; ok: boolean }

export function printerBadge({ diag, concerns }: BadgeInput): Badge | null {
  if (!diag) return null;
  if (concerns > 0) return { label: diag.healthy ? "See concerns" : (diag.klippy_state ?? "check"), ok: false };
  return diag.healthy ? { label: "Healthy", ok: true } : { label: diag.klippy_state ?? "check", ok: false };
}
