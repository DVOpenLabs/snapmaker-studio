import { AlertTriangle, Gauge } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { evidenceKindLabel } from "@/lib/evidenceKind";
import type { PrintFindings } from "@/api";

// What Studio found worth settling before slicing, plus what it did and did not
// check. Deliberately no percentage, band or verdict: nothing here is calibrated
// against real print outcomes (#92).
export function PrintRiskSignals({ findings }: { findings: PrintFindings }) {
  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <span className="flex items-center gap-2 text-sm font-semibold"><Gauge className="h-4 w-4 text-primary" /> Print risk signals</span>
        {findings.available ? (
          <>
            {findings.summary && <p className="text-sm text-muted-foreground">{findings.summary}</p>}
            {findings.signals && findings.signals.length > 0 && (
              <ul className="space-y-2">
                {findings.signals.map((sig) => (
                  <li key={sig.id} className="space-y-0.5 rounded-md border border-border p-2.5 text-xs">
                    <p className={`flex flex-wrap items-center gap-1.5 text-sm font-medium ${sig.level === "risk" ? "text-risk" : "text-repairable"}`}>
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                      <span>{sig.level === "risk" ? "Risk" : "Heads up"}: {sig.title}</span>
                      {evidenceKindLabel(sig.kind) && <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground">{evidenceKindLabel(sig.kind)}</span>}
                    </p>
                    <p className="text-muted-foreground">{sig.meaning}</p>
                    <p><span className="font-semibold">What to do:</span> {sig.action}</p>
                    {sig.details && sig.details.length > 0 && (
                      <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
                        {sig.details.map((d, i) => <li key={i}>{d}</li>)}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {findings.checked && findings.checked.length > 0 && (
              <p className="text-xs text-muted-foreground"><span className="font-semibold">Studio checked:</span> {findings.checked.join(", ")}.</p>
            )}
            {findings.not_checked && findings.not_checked.length > 0 && (
              <p className="text-xs text-muted-foreground"><span className="font-semibold">Studio did not check:</span> {findings.not_checked.join(", ")}.</p>
            )}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">Studio has nothing to check yet: {findings.reason ?? "no information was available"}.</p>
        )}
        {findings.limitations && findings.limitations.map((l, i) => (
          <p key={i} className="text-[11px] text-muted-foreground">{l}</p>
        ))}
      </CardContent>
    </Card>
  );
}
