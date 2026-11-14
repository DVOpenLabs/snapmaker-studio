import { Link } from "react-router-dom";
import { Rocket, Download, Loader2, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useOrca } from "@/hooks/useOrca";
import { ORCA_RELEASES_URL, ORCA_HANDOFF_LINE } from "@/lib/orca";
import { EcosystemPanel } from "@/components/EcosystemPanel";
import { FidelityCard } from "@/components/FidelityCard";
import { FixLedgerCard } from "@/components/FixLedgerCard";

/**
 * One-way Snapmaker Orca handoff. Shows "Open in Snapmaker Orca" when an install
 * is detected, otherwise "Install Snapmaker Orca" (official releases). Only ever
 * appears when a prepared/safe-copy file exists. Studio never slices and never
 * controls Orca; the install path is never displayed in the UI.
 */
export function OrcaHandoff({ outputPath, originalPath }:
  { outputPath: string; originalPath?: string }) {
  const { state, opening, open } = useOrca(outputPath);

  return (
    <div className="flex flex-col items-center gap-1.5">
      {state === "detecting" ? (
        <Button disabled>
          <Loader2 className="h-4 w-4 animate-spin" /> Checking for Snapmaker Orca…
        </Button>
      ) : state === "installed" ? (
        <Button onClick={open} disabled={opening}>
          {opening ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
          {opening ? "Opening…" : "Open in Snapmaker Orca"}
        </Button>
      ) : (
        <Button variant="secondary" asChild>
          <a href={ORCA_RELEASES_URL} target="_blank" rel="noreferrer">
            <Download className="h-4 w-4" /> Install Snapmaker Orca
          </a>
        </Button>
      )}
      {/* The exact file the button opens, so the handoff never targets something unnamed. */}
      <p className="max-w-full text-xs">
        <span className="text-muted-foreground">Opens the prepared copy </span>
        <span className="break-all font-medium" title={outputPath} data-testid="orca-target">{outputPath.split(/[\\/]/).pop() || outputPath}</span>
      </p>
      <p className="text-xs text-muted-foreground">{ORCA_HANDOFF_LINE}</p>
      <div className="mt-1 rounded-md border border-border bg-muted/20 p-2 text-xs text-muted-foreground">
        <p>
          <span className="font-medium text-foreground">Next:</span> slice in Snapmaker Orca, export the{" "}
          <span title="The .gcode file is the printer-ready file Snapmaker Orca creates after slicing."
            className="cursor-help underline decoration-dotted">.gcode</span>{" "}
          file, then open it in{" "}
          <Link to="/after-slicing" className="inline-flex items-center gap-0.5 text-foreground underline underline-offset-2">
            After slicing <ArrowRight className="h-3 w-3" />
          </Link>{" "}
          so Studio can check it. Sending to your printer is a separate step you confirm in{" "}
          <Link to="/printers" className="inline-flex items-center gap-0.5 text-foreground underline underline-offset-2">
            Printer Hub <ArrowRight className="h-3 w-3" />
          </Link>
          . (Studio doesn't slice — Snapmaker Orca does.)
        </p>
      </div>
      {/* Proof rather than a promise: what actually survived the preparation,
          including anything Studio could not check. Only rendered when the
          original is known, because there is nothing to compare against
          otherwise. */}
      {originalPath && originalPath !== outputPath && (
        <div className="mt-1 w-full space-y-3">
          <FidelityCard original={originalPath} prepared={outputPath} />
          {/* What Studio did, and the way back to the untouched original. */}
          <FixLedgerCard source={originalPath} output={outputPath} />
        </div>
      )}
      {/* What this specific project might also want. Reads the prepared file and
          names the community tool that fits, with the reason from the file. */}
      <div className="mt-1 w-full">
        <EcosystemPanel path={outputPath} />
      </div>
    </div>
  );
}
