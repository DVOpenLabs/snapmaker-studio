// Pure fetch-trigger builders (R4-D5).
//
// Each consumer's `useEffect` dependency array IS its refetch policy, but a
// literal array in JSX isn't independently testable. Extracting the array
// itself as a pure function — and a `shouldRefetch` that mirrors React's own
// shallow dependency comparison — makes "does a nozzleNotesVersion bump
// actually cause a refetch here" a plain assertion instead of something only
// checkable by reading the component and trusting it's wired correctly.
export function shouldRefetch(prevDeps: readonly unknown[], nextDeps: readonly unknown[]): boolean {
  if (prevDeps.length !== nextDeps.length) return true;
  return prevDeps.some((v, i) => !Object.is(v, nextDeps[i]));
}

/** PreflightCard: refetches on path/host change AND on any nozzle mutation
 *  anywhere (cross-component invalidation, F5). */
export function preflightFetchTrigger(path: string, host: string, nozzleNotesVersion: number): readonly unknown[] {
  return [path, host, nozzleNotesVersion];
}

/** Printer Hub's nozzle line: a read-only view with no mutations of its own,
 *  so it needs the global signal to know something else changed (F5). */
export function printerHubNozzleFetchTrigger(connected: string | null, nozzleNotesVersion: number): readonly unknown[] {
  return [connected, nozzleNotesVersion];
}

/** The Settings nozzle table: deliberately does NOT take a
 *  `nozzleNotesVersion` parameter at all (A2) — it applies its own mutation
 *  responses directly and refetches on its own host change; nothing else
 *  needs to tell it to. */
export function settingsNozzleFetchTrigger(host: string): readonly unknown[] {
  return [host];
}
