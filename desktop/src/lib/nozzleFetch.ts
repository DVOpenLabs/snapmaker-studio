// Pure two-phase nozzle-status fetch (v1.2 round-3 F3).
//
// Phase 1 (`probe:false`) returns instantly from stored+profile data so a
// table never shows zero rows while the printer is being contacted; phase 2
// (`probe:true`) does the real live read, which can take several seconds on
// an unreachable printer, and replaces phase 1's data.
//
// `isCurrent()` is checked before every callback AND before phase 2 is even
// launched — the exact guard the round-3 review found missing (a cleanup
// setting `alive = false` used to only stop phase 1's callback, leaving
// phase 2 to run to completion and get silently discarded, or worse, applied
// after the component had moved to a different host). No revision or floor
// bookkeeping happens here; the caller (a per-component token) owns
// deciding what "current" means.
import type { NozzleStatus } from "@/api";

export interface NozzleFetchApi {
  nozzleStatus: (host: string, port: number, probe: boolean) => Promise<NozzleStatus>;
}

export interface NozzleFetchCallbacks {
  /** Phase-1 (stored+profile) succeeded. */
  quick: (status: NozzleStatus) => void;
  /** Phase-2 (live) succeeded — supersedes whatever `quick` reported. */
  live: (status: NozzleStatus) => void;
  /** Phase-1 succeeded but phase-2 failed: existing data stays, just stop
   *  showing "checking the printer" — this is not an error state. */
  liveFailed: () => void;
  /** Both phases failed: nothing to show. */
  allFailed: () => void;
}

function defaultWait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export interface RunNozzleFetchParams {
  host: string;
  port: number;
  /** Re-checked before every callback and before phase 2 is launched. */
  isCurrent: () => boolean;
  api: NozzleFetchApi;
  on: NozzleFetchCallbacks;
  /** Debounce (R4-D6): phase-1 is never delayed, but phase-2 (the real live
   *  probe) waits this long before it's even requested — so retyping a host
   *  character by character doesn't fire a live probe per keystroke, only
   *  once the host has been unchanged for the whole window. 0 (default) is
   *  immediate, for a manual "Refresh" or a read-only, non-keystroke-driven
   *  consumer. `isCurrent()` is re-checked after the wait, same as always. */
  liveDelayMs?: number;
  /** Injectable for tests; defaults to a real `setTimeout`-based wait. */
  wait?: (ms: number) => Promise<void>;
}

export interface GenerationGuard {
  /** Starts a new generation, invalidating every one issued before it.
   *  Returns the new generation's id, to capture in an `isCurrent` closure. */
  next: () => number;
  isCurrent: (generation: number) => boolean;
  /** Invalidates the latest generation without starting a new one — the
   *  unmount / !connected / effect-cleanup case (R4-D2): there is no new
   *  fetch to own the next generation, but whatever is in flight must stop
   *  mattering all the same. */
  invalidate: () => void;
}

/** A tiny, reusable freshness primitive: one monotonic counter, an
 *  `isCurrent` check, and an explicit `invalidate` for "nothing in flight is
 *  current anymore, and I'm not starting anything new either" — exactly what
 *  an effect's cleanup function needs on unmount or when its trigger
 *  dependencies change out from under an in-flight two-phase fetch (R4-D2). */
export function createGenerationGuard(): GenerationGuard {
  let generation = 0;
  return {
    next: () => { generation += 1; return generation; },
    isCurrent: (g: number) => g === generation,
    invalidate: () => { generation += 1; },
  };
}

export async function runNozzleFetch(params: RunNozzleFetchParams): Promise<void> {
  const { host, port, isCurrent, api, on, liveDelayMs = 0, wait = defaultWait } = params;

  let quickSucceeded = false;
  try {
    const quick = await api.nozzleStatus(host, port, false);
    if (!isCurrent()) return;
    quickSucceeded = true;
    on.quick(quick);
  } catch {
    // Phase-1 failing is not itself reported; phase-2 gets its own chance,
    // and only a phase-2 failure on top of this one is a real error.
  }

  if (!isCurrent()) return;

  if (liveDelayMs > 0) {
    await wait(liveDelayMs);
    if (!isCurrent()) return;
  }

  try {
    const live = await api.nozzleStatus(host, port, true);
    if (!isCurrent()) return;
    on.live(live);
  } catch {
    if (!isCurrent()) return;
    if (quickSucceeded) on.liveFailed();
    else on.allFailed();
  }
}
