// Centralised nozzle mutation helper (v1.2 round-3 F2).
//
// Every consumer that changes nozzle notes goes through here rather than
// calling nozzleConfirm/nozzleClear directly, so the cross-component
// invalidation signal (bumpNozzleNotes) is raised in exactly one place and
// can never be forgotten by a component — including the case where the
// component that started the mutation has since unmounted (host switched
// away) before the response arrived: the bump still happens, because it does
// not depend on any component being there to receive it.
//
// When to bump: a successful write, obviously. Also a failure whose outcome
// is *uncertain* — a network error, a timeout, anything that isn't a
// response the backend actually sent — because Studio cannot tell whether
// the write landed; every consumer refetching is the safe reconciliation.
// When NOT to bump: a definite backend response saying the write did not
// happen (400 invalid_*, 404, 409 stale/duplicate_notes) — the outcome is
// known, nothing changed, and a 409 stale already gets its own recovery
// fetch on the same path as everything else (F4/S5), not a global bump.
import { ApiError, nozzleClear, nozzleConfirm, type NozzleStatus } from "@/api";
import { bumpNozzleNotes } from "@/store/nozzleRevision";

export type NozzleMutationResult =
  | { ok: true; status: NozzleStatus }
  | { ok: false; error: ApiError };

async function run(op: () => Promise<NozzleStatus>): Promise<NozzleMutationResult> {
  try {
    const status = await op();
    bumpNozzleNotes();
    return { ok: true, status };
  } catch (e) {
    // A definite response from the backend carries a `code` (invalid_*,
    // no_such_note, stale, duplicate_notes, storage_unavailable, ...) — that
    // outcome is known, nothing changed, no bump. Anything else — a plain
    // network error, or (N13) an ApiError that somehow carries no code at
    // all (a malformed/incomplete response) — is UNCERTAIN: Studio cannot
    // tell whether the write landed, so every consumer refetching is the
    // safe reconciliation. The controller (nozzleSettingsController.ts) makes
    // the exact same `code === undefined` distinction for its recovery fetch;
    // these two must never drift apart.
    if (e instanceof ApiError && e.code !== undefined) {
      return { ok: false, error: e };
    }
    bumpNozzleNotes();
    if (e instanceof ApiError) return { ok: false, error: e }; // keep its own message, just no code
    // A raw `e.message` ("Failed to fetch", "ECONNRESET", ...) is an
    // implementation detail, not something to show (R4-D7) — fixed text.
    return { ok: false, error: new ApiError("Studio couldn't reach its local service. Try again.") };
  }
}

export function confirmNozzles(
  host: string, port: number, diameters: (number | null)[], expectedRevision: number,
): Promise<NozzleMutationResult> {
  return run(() => nozzleConfirm(host, port, diameters, expectedRevision));
}

export function clearNozzles(
  host: string, port: number, expectedRevision: number,
): Promise<NozzleMutationResult> {
  return run(() => nozzleClear(host, port, expectedRevision));
}
