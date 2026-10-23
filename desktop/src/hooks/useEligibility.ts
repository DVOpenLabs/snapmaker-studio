import { useEffect, useState } from "react";
import { compatibilityCheck } from "@/api";
import { prepareGate, type PrepareGate } from "@/lib/compatibility";

export type Eligibility =
  | { status: "checking" }
  /** The check could not run; the engine still refuses at Prepare if the project cannot be prepared. */
  | { status: "unavailable" }
  | { status: "ready"; gate: PrepareGate };

/**
 * Whether Studio will prepare this project, from the engine's own eligibility record.
 * Read-only. A 3MF is asked; an STL is wrapped into a new U1 project, so there is nothing to ask.
 */
export function useEligibility(path: string, ext: string): Eligibility {
  const asks = ext === "3mf";
  const [answer, setAnswer] = useState<{ path: string; value: Eligibility } | null>(null);

  useEffect(() => {
    if (!asks) return;
    let alive = true;
    compatibilityCheck(path).then(
      (r) => { if (alive) setAnswer({ path, value: { status: "ready", gate: prepareGate(r.findings) } }); },
      () => { if (alive) setAnswer({ path, value: { status: "unavailable" } }); },
    );
    return () => { alive = false; };
  }, [path, asks]);

  if (!asks) return { status: "ready", gate: "open" };
  return answer && answer.path === path ? answer.value : { status: "checking" };
}
