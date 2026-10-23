import { useCallback, useEffect, useState } from "react";
import { detectOrca, openInOrca } from "@/api";
import { orcaErrorMessage } from "@/lib/orca";
import { useToast } from "@/store/toast";

export type OrcaState = "detecting" | "installed" | "missing";

/**
 * Whether Snapmaker Orca is installed here, and the one-way "open this file in it" action.
 * Studio never slices and never controls Orca; this only hands over a file the person chose.
 */
export function useOrca(outputPath: string) {
  const showToast = useToast((s) => s.show);
  // undefined = still detecting, string = installed, null = not installed
  const [orca, setOrca] = useState<string | null | undefined>(undefined);
  const [opening, setOpening] = useState(false);

  useEffect(() => {
    let alive = true;
    detectOrca().then(
      (p) => { if (alive) setOrca(p); },
      () => { if (alive) setOrca(null); }, // not in Tauri / detection failed -> offer install
    );
    return () => { alive = false; };
  }, []);

  const open = useCallback(async () => {
    setOpening(true);
    try {
      await openInOrca(outputPath);
      showToast("Opening your prepared file in Snapmaker Orca…");
    } catch (e) {
      if (String((e as Error)?.message ?? e).includes("orca-not-found")) setOrca(null);
      showToast(orcaErrorMessage(e));
    } finally {
      setOpening(false);
    }
  }, [outputPath, showToast]);

  const state: OrcaState = orca === undefined ? "detecting" : orca ? "installed" : "missing";
  return { state, opening, open };
}
