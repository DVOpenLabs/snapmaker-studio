import { AlertTriangle } from "lucide-react";
import type { GeometryBasis } from "@/api";

/** True when the file's numbers are NOT established as the model's physical size. Missing = established. */
export function sizeNotEstablished(basis?: GeometryBasis | null): boolean {
  return !!basis && basis.established === false;
}

/** The one sentence every size-dependent surface shows when it withholds a verdict. */
export function NotCheckedReason({ reason, scope, className }: { reason?: string | null; scope?: string | null; className?: string }) {
  return (
    <p className={className ?? "flex items-start gap-1.5 text-xs text-muted-foreground"} data-testid="not-checked-reason">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-repairable" />
      <span>
        {scope ? <b>Not checked: {scope}. </b> : <b>Not checked. </b>}
        {reason}
      </span>
    </p>
  );
}

/** A short qualifier for a size shown from the raw file mesh. */
export function rawSizeQualifier(basis?: GeometryBasis | null): string | null {
  return sizeNotEstablished(basis) ? "as stored in the file — not a confirmed physical size" : null;
}
