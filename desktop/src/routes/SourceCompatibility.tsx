import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate, Link } from "react-router-dom";
import { FileSearch, FilePlus, Loader2, AlertTriangle, CheckCircle2, ArrowRight, Stethoscope } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { openModelDialog, sourceCompatibility, type SourceCompatibilityReport } from "@/api";
import { useSession } from "@/store/session";
import { readiness, summaryLine, wizardSteps } from "@/lib/sourceWizard";
import { JOB_ROUTE } from "@/lib/routes";

// Source Check: tell a beginner what kind of file/project they have, what Studio can
// read, what it can't convert yet, and the safe next step for your U1. Read-only + advisory.
export default function SourceCompatibility() {
  const nav = useNavigate();
  const setFile = useSession((s) => s.setFile);
  const [path, setPath] = useState<string | null>(null);
  const [report, setReport] = useState<SourceCompatibilityReport | null>(null);

  const m = useMutation({
    mutationFn: (p: string) => sourceCompatibility(p),
    onSuccess: (d) => setReport(d),
  });

  async function pick() {
    const p = await openModelDialog();
    if (!p) return;
    setPath(p); setReport(null); m.mutate(p);
  }
  function openInStudio() {
    if (!path) return;
    setFile(path);
    nav(JOB_ROUTE);
  }

  const ready = report ? readiness(report) : null;

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <PageHeader icon={FileSearch} title="Source Check"
        subtitle="See which slicer made this file, and the safe next step for your U1." />

      <Card><CardContent className="space-y-2 p-5">
        <Button size="sm" onClick={pick} disabled={m.isPending}>
          {m.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FilePlus className="h-4 w-4" />} Choose a file to check
        </Button>
        {path && <p className="text-xs text-muted-foreground">Checking your file — read-only.</p>}
      </CardContent></Card>

      {m.isError && <p className="text-sm text-risk">{(m.error as Error).message}</p>}

      {report && (
        <Card><CardContent className="space-y-4 p-5">
          <div className="flex items-center gap-2">
            {ready === "ready" ? <CheckCircle2 className="h-5 w-5 text-ready" />
              : ready === "unknown" ? <AlertTriangle className="h-5 w-5 text-risk" />
              : <FileSearch className="h-5 w-5 text-primary" />}
            <p className="text-sm font-semibold">{summaryLine(report)}</p>
          </div>

          {wizardSteps(report).map((s) => (
            <div key={s.phase}>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{s.title}</p>
              <ul className="space-y-0.5 text-sm text-muted-foreground">
                {s.items.map((t, i) => <li key={i} className="flex gap-1.5"><span>•</span><span>{t}</span></li>)}
              </ul>
            </div>
          ))}

          {report.risks.length > 0 && (
            <div className="rounded-md border border-border bg-muted/30 p-2 text-xs">
              {report.risks.map((rk, i) => (
                <p key={i} className="flex items-start gap-1.5 text-muted-foreground"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {rk}</p>
              ))}
            </div>
          )}

          <div className="flex flex-wrap gap-2 border-t border-border pt-3">
            <Button size="sm" onClick={openInStudio}><ArrowRight className="h-4 w-4" /> Open in Studio &amp; run Project Doctor</Button>
            <Button size="sm" variant="secondary" asChild><Link to="/doctor/project"><Stethoscope className="h-4 w-4" /> Project Doctor</Link></Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Read-only. Studio prepares a U1 profile copy; you slice in Snapmaker Orca.
          </p>
        </CardContent></Card>
      )}
    </div>
  );
}
