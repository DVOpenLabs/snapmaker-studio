// The one-word state chip on the connected-printer card. It must agree with the health card below it and with the
// Intelligence Report's printer line: all three count the same conditions (the health result's `conditions`, one per
// condition id). Any concern reads "See concerns" while the firmware itself is ready; a firmware that is not ready shows
// its own state. "Healthy" only appears with ready firmware and no concerns.
export interface BadgeInput {
  diag: { healthy?: boolean; klippy_state?: string | null } | null | undefined;
  /** Number of conditions the printer reported (`health.conditions.length`). */
  concerns: number;
}
export interface Badge { label: string; ok: boolean }

export function printerBadge({ diag, concerns }: BadgeInput): Badge | null {
  if (!diag) return null;
  const state = diag.klippy_state ?? null;
  const firmwareReady = state === "ready";
  if (!firmwareReady && state) return { label: state, ok: false };       // shutdown, error, startup: say so
  if (concerns > 0) return { label: "See concerns", ok: false };
  return diag.healthy ? { label: "Healthy", ok: true } : { label: state ?? "check", ok: false };
}
