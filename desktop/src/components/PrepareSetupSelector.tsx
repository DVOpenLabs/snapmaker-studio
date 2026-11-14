import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { outcomeIsGood, setupFor, setupStatusLine, topologyOutcome, topologyOutcomeLine, type PrepareSetupSelection, type TopologyOutcome } from "@/lib/prepareSetup";
import { useSession } from "@/store/session";

export interface ReadInput { host: string; port?: string; key?: string }

interface Props {
  selection: PrepareSetupSelection;
  /** Read the host. The key is passed once and this component forgets it straight after. */
  onRead: (input: ReadInput) => Promise<void> | void;
  onClear: () => void;
  /** Prepare with no setup at all. Absent while Prepare is not available. */
  onPrepareWithoutSetup?: () => void;
  disabled?: boolean;
  /** What the engine said about the setup in the copy or review now shown. Absent when none is shown. */
  outcome?: TopologyOutcome;
}

const tone = (s: PrepareSetupSelection["status"]) =>
  s === "ready" ? "border-primary/40 bg-primary/5" : s === "none" || s === "reading" ? "" : "border-risk/40 bg-risk/5";

/**
 * Choose the printer setup Prepare should use. Optional: with no setup chosen Prepare is exactly what it always was.
 * It reads a host (GET-only, through the local service), shows what the host reported without adding to it, and offers
 * "Prepare without a setup" as its own action. The key is held in this component only while the person types it.
 */
export function PrepareSetupSelector({ selection, onRead, onClear, onPrepareWithoutSetup, disabled = false, outcome }: Props) {
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [key, setKey] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  useEffect(() => () => setKey(""), []);

  const reading = selection.status === "reading";
  const read = async () => {
    setFormError(null);
    const sentKey = key;
    setKey("");
    try {
      await onRead({ host, port, key: sentKey });
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Check the host and port.");
    }
  };

  const field = "h-9 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50";
  const outcomeLine = outcome ? topologyOutcomeLine(outcome) : null;
  const problem = selection.status === "unknown" || selection.status === "invalid" || selection.status === "failed";
  return (
    <Card data-testid="prepare-setup">
      <CardContent className="space-y-3 p-4">
        <div>
          <h3 className="text-sm font-semibold">Printer setup (optional)</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Studio can read your printer host (read only) and use the setup it reports when it maps tools for the copy.
            It does not guess a setup the host did not report.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <input className={`${field} w-48`} aria-label="Setup host address" placeholder="192.168.1.50 or u1.local" value={host} onChange={(e) => setHost(e.target.value)} disabled={disabled || reading} />
          <input className={`${field} w-24`} aria-label="Setup port" placeholder="7125" value={port} onChange={(e) => setPort(e.target.value)} disabled={disabled || reading} />
          <input className={`${field} w-48`} aria-label="Setup OctoPrint API key" type="password" autoComplete="off" placeholder="API key (optional)" value={key} onChange={(e) => setKey(e.target.value)} disabled={disabled || reading} />
          <Button size="sm" variant="secondary" onClick={() => void read()} disabled={disabled || reading || host.trim() === ""} data-testid="setup-read">
            {reading ? "Reading..." : selection.status === "none" ? "Read setup" : "Read again"}
          </Button>
          {selection.status !== "none" && (
            <Button size="sm" variant="ghost" onClick={onClear} disabled={disabled} data-testid="setup-clear">Clear setup</Button>
          )}
        </div>
        {formError && <p className="text-sm text-risk" role="alert" data-testid="setup-form-error">{formError}</p>}
        <p className={`rounded-md border p-2 text-sm ${tone(selection.status)}`} role={problem ? "alert" : "status"} data-testid="setup-status" data-state={selection.status}>
          {setupStatusLine(selection)}
        </p>
        {outcomeLine && (
          <p className={`rounded-md border p-2 text-sm ${outcomeIsGood(outcome!) ? "border-primary/40 bg-primary/5" : "border-risk/40 bg-risk/5"}`}
            role={outcomeIsGood(outcome!) ? "status" : "alert"} data-testid="setup-outcome" data-state={outcome!.state}>
            {outcomeLine}
          </p>
        )}
        {problem && (
          <p className="text-xs text-muted-foreground" data-testid="setup-paused">
            Prepare and Review settings are paused while this setup can&apos;t be used. Nothing is guessed in its place.
          </p>
        )}
        {selection.status !== "none" && onPrepareWithoutSetup && (
          <div className="flex items-center justify-between rounded-md border p-3">
            <span>
              <span className="block text-sm font-medium">Prepare without a setup</span>
              <span className="block text-xs text-muted-foreground">Clears this setup and prepares the stock four-toolhead U1 copy.</span>
            </span>
            <Button size="sm" variant="secondary" onClick={onPrepareWithoutSetup} disabled={disabled || reading} data-testid="prepare-without-setup">Prepare without a setup</Button>
          </div>
        )}
        <p className="text-xs text-muted-foreground">The key is sent once with the read and is not saved. This is advisory; it does not promise a print.</p>
      </CardContent>
    </Card>
  );
}

/** The selector bound to the shared Prepare state for `projectPath`. Renders nothing without a project. */
export function ConnectedPrepareSetupSelector({ projectPath, onPrepareWithoutSetup, disabled, result }: {
  projectPath: string | null; onPrepareWithoutSetup?: () => void; disabled?: boolean;
  /** The review or prepared copy on screen; its engine report decides what is said about the setup. */
  result?: Parameters<typeof topologyOutcome>[1];
}) {
  const selection = useSession((s) => s.prepareSetup);
  const read = useSession((s) => s.readPrepareSetup);
  const clear = useSession((s) => s.clearPrepareSetup);
  if (!projectPath) return null;
  // A setup chosen for another project is not shown here and is not sent for this one.
  const shown = setupFor(selection, projectPath);
  const outcome = result ? topologyOutcome(shown.status === "ready", result, shown.status === "ready" ? { heads: shown.summary.heads, slots: shown.summary.slots } : undefined) : undefined;
  return <PrepareSetupSelector selection={shown} outcome={outcome} onRead={(input) => read(input, projectPath)} onClear={clear} onPrepareWithoutSetup={onPrepareWithoutSetup} disabled={disabled} />;
}
