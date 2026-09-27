import { create } from "zustand";

// v1.2 round-3 re-diagnosis (F1): the shared client revision floor tried in
// rounds 1-2 (canonical-host keying, per-consumer generation counters, a
// decideNozzleResponse accept/drop function) was deleted after three
// consecutive review rounds kept finding races in it — phase-2 live results
// discarded when phase-1 raised the floor, mutations raising the floor
// without a self-trigger guard, PreflightCard's hardcoded degraded:false,
// stale-write recovery bypassing the guard, IPv4-embedded IPv6 splitting a
// key. Freshness within one component is now a single monotonic request
// token per component instance (lib/nozzleSettingsController.ts,
// lib/nozzleFetch.ts). Freshness ACROSS components (a mutation in Settings
// should make Printer Hub/PreflightCard refetch) is this one small global
// counter: bumped only by a successful (or uncertain-outcome) mutation, read
// by every consumer as a fetch trigger. No host/port keying, because nothing
// here decides what to keep vs. drop by comparing to anything — it only ever
// says "something changed somewhere, refetch". Backend revision numbers are
// unaffected: they remain the optimistic-concurrency guard on
// /nozzles/confirm and /nozzles/clear (expected_revision -> 409 "stale").

interface NozzleNotesVersionState {
  version: number;
}

export const useNozzleNotesVersion = create<NozzleNotesVersionState>(() => ({ version: 0 }));

/** Called by lib/nozzleMutations.ts after a nozzle confirm/clear that either
 *  succeeded or whose outcome is uncertain (network error) — never after a
 *  read, and never after a definite failure (400/404/409) whose outcome is
 *  known and did not change anything. */
export function bumpNozzleNotes(): void {
  useNozzleNotesVersion.setState((s) => ({ version: s.version + 1 }));
}

// ---- Stale-write message lifecycle (R2-D3) -----------------------------------
// After a 409 stale write, the component shows "Changed elsewhere — reloaded,
// try again." and automatically refetches to recover. That automatic refetch
// must not itself clear the message it exists to explain — only a fresh user
// action (Save, Update, Remove) does. Extracted as a pure reducer so this
// exact rule is enforced in one place and is directly testable without a DOM.

export type NozzleMessageEvent =
  | { type: "user_action_started" }
  | { type: "mutation_failed"; message: string; code?: string }
  | { type: "status_refetched" };

const STALE_MESSAGE = "Changed elsewhere — reloaded, try again.";

export function nextNozzleErrorMessage(
  current: string | null, event: NozzleMessageEvent,
): string | null {
  switch (event.type) {
    case "user_action_started":
      return null;
    case "mutation_failed":
      return event.code === "stale" ? STALE_MESSAGE : event.message;
    case "status_refetched":
      // The automatic recovery fetch after a stale write never clears
      // whatever message is already showing.
      return current;
  }
}
