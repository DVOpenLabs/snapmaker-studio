// The one-word state chip on the connected-printer card. It must agree with the health card below it:
// "Healthy" is only shown when the firmware state is fine AND the health card lists no concerns.
export interface BadgeInput {
  diag: { healthy?: boolean; klippy_state?: string | null } | null | undefined;
  drivers: string[] | null | undefined;
}
export interface Badge { label: string; ok: boolean }

export function hasConcerns(drivers: string[] | null | undefined): boolean {
  return (drivers ?? []).some((d) => !/no problems? found/i.test(d));
}

export function printerBadge({ diag, drivers }: BadgeInput): Badge | null {
  if (!diag) return null;
  if (hasConcerns(drivers)) return { label: diag.healthy ? "See concerns" : (diag.klippy_state ?? "check"), ok: false };
  return diag.healthy ? { label: "Healthy", ok: true } : { label: diag.klippy_state ?? "check", ok: false };
}
