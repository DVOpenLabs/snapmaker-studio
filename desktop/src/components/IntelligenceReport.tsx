import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { intelligenceReport, type IntelligenceReport as Report } from "@/api";
import { AlertTriangle, ArrowRight, ChevronDown, CheckCircle2, Stethoscope, Sparkles, GitCompareArrows, Users } from "lucide-react";

// The Studio Intelligence Report: one screen with the risks Studio found, what it
// costs, the biggest risk and the next action. The Doctors are the supporting
// evidence. It shows no headline score: nothing here is calibrated against print
// outcomes, so a number would read as a measure of print readiness (#92).

export function IntelligenceReport({ filePath, host, data, defaultOpen = false }: { filePath?: string; host?: string | null; data?: Report; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const { data: fetched, isLoading } = useQuery({
    queryKey: ["report", filePath, host],
    queryFn: () => intelligenceReport(filePath as string, host),
    enabled: !data && !!filePath, retry: false, staleTime: 30000,
  });
  const r = data ?? fetched;
  if ((!data && isLoading) || !r?.available) return null;
  const cur = r.currency ?? "$";
  const metric = (label: string, value: string, token?: string) => (
    <div className="rounded-lg border border-border p-2.5 text-center">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="text-base font-bold tabular-nums" style={token ? { color: `hsl(var(${token}))` } : undefined}>{value}</p>
    </div>
  );

  return (
    <Card className="overflow-hidden border-primary/30">
      <CardContent className="space-y-4 p-5">
        {/* header + headline metrics */}
        <div className="flex items-center gap-4">
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-sm font-semibold">
              <Stethoscope className="h-4 w-4 text-primary" /> Studio Intelligence Report
              {r.is_demo && <span className="inline-flex items-center gap-1 rounded-full bg-repairable/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-repairable"><Sparkles className="h-3 w-3" /> Sample data</span>}
            </p>
            {r.is_demo && <p className="text-[11px] font-medium text-repairable">Sample data — not a real analysis of your file. Open a model to run the real Doctors.</p>}
            <p className="text-sm text-muted-foreground">{r.verdict}</p>
            <p className="mt-1 text-[11px] text-muted-foreground opacity-70">Powered by Studio Intelligence · your Doctors, in one answer</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {(r.risks_found ?? 0) === 0 && (r.not_verified?.length ?? 0) > 0
            ? metric("Not verified", r.not_verified!.join(", ").replace(/^./, (c) => c.toUpperCase()), "--doctor-cost")
            : metric("Risks found", String(r.risks_found ?? 0), (r.risks_found ?? 0) > 0 ? "--doctor-cost" : undefined)}
          {metric("Material cost", r.cost != null ? `${cur}${r.cost}` : "—", "--doctor-cost")}
          {metric("Printer", r.printer_status ?? "Not checked")}
        </div>
        <p className="text-[11px] text-muted-foreground opacity-70">
          {(r.risks_found ?? 0) === 0 && (r.not_verified?.length ?? 0) > 0
            ? "Advisory: Studio could not verify everything listed as not verified, and this is not a measure of how likely the print is to succeed. Verify in Snapmaker Orca before printing."
            : "Advisory: a count of the risks Studio found, not a measure of how likely the print is to succeed. Verify in Snapmaker Orca before printing."}
        </p>
        {(r.not_verified?.length ?? 0) > 0 && (r.risks_found ?? 0) > 0 && (
          <p className="text-[11px] text-muted-foreground">Not verified by Studio: {r.not_verified!.join(", ")}. Check it in Snapmaker Orca.</p>
        )}

        {/* Pricing is a secondary, opt-in estimate — not the headline on a readiness screen. */}
        {(r.suggested_price != null || r.margin_pct != null) && (
          <details className="rounded-md border border-border px-3 py-2 text-xs">
            <summary className="cursor-pointer font-medium text-muted-foreground">Optional business estimate</summary>
            <p className="mt-1 text-muted-foreground">
              Estimated sell price {r.suggested_price != null ? `~${cur}${r.suggested_price}` : "—"}
              {r.margin_pct != null ? ` · margin ~${r.margin_pct}%` : ""}.{" "}
              <a href="/doctor/pricing" className="text-primary hover:underline">View pricing estimate</a>
            </p>
          </details>
        )}

        {/* biggest risk + the one next action */}
        {r.biggest_risk && (
          <div className="flex items-start gap-2 rounded-md bg-risk/5 px-3 py-2 text-sm text-risk">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span><span className="font-semibold">Biggest risk:</span> {r.biggest_risk.text} <span className="opacity-70">({r.biggest_risk.doctor})</span></span>
          </div>
        )}
        <div className="flex items-start gap-2 rounded-md bg-primary/5 px-3 py-2 text-sm">
          <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <span><span className="font-semibold">Next:</span> {r.next_action}</span>
        </div>

        {/* Before vs After — why not just use Orca? */}
        {r.comparison && (
          <div className="rounded-md border border-border p-3">
            <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold"><GitCompareArrows className="h-3.5 w-3.5 text-primary" /> Why not just use Orca?</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
                <p className="mb-0.5 font-semibold uppercase tracking-wide text-[10px]">Orca alone</p>
                {r.comparison.orca_line}
              </div>
              <div className="rounded-md p-2 text-xs" style={{ backgroundColor: "hsl(var(--stage-validate) / 0.08)" }}>
                <p className="mb-0.5 font-semibold uppercase tracking-wide text-[10px]" style={{ color: "hsl(var(--stage-validate))" }}>With Studio</p>
                {r.comparison.studio_line}
              </div>
            </div>
          </div>
        )}

        {/* progressive disclosure: risks, recommendations, evidence */}
        <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1 text-xs font-medium text-primary">
          <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
          {open ? "Hide the evidence" : "See risks, recommendations & Doctor findings"}
        </button>

        {open && (
          <div className="space-y-3 border-t border-border pt-3 text-xs">
            {r.risks && r.risks.length > 0 && (
              <div>
                <p className="mb-1 font-semibold">Risks</p>
                <ul className="space-y-1">
                  {r.risks.map((rk, i) => (
                    <li key={i} className="space-y-1">
                      <p className={`flex items-start gap-1.5 ${rk.level === "risk" ? "text-risk" : "text-repairable"}`}>
                        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {rk.text} <span className="opacity-60">({rk.doctor})</span>
                      </p>
                      {rk.community && (
                        <div className="ml-5 rounded-md bg-muted/40 px-2 py-1.5 text-muted-foreground">
                          <p className="flex items-center gap-1.5"><Users className="h-3 w-3 text-primary" />
                            <span className="font-medium text-foreground">Community fix</span>
                            <span className="rounded-full bg-ready/10 px-1.5 text-[9px] font-semibold text-ready">{rk.community.confidence} confidence</span>
                          </p>
                          <p className="mt-0.5">{rk.community.fix}</p>
                          <p className="mt-0.5 opacity-70">{rk.community.success_pattern} · {rk.community.sources.join(", ")}</p>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {r.recommendations && r.recommendations.length > 0 && (
              <div>
                <p className="mb-1 font-semibold">Recommendations</p>
                <ul className="space-y-1 text-muted-foreground">
                  {r.recommendations.map((rc, i) => (
                    <li key={i} className="flex items-start gap-1.5"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ready" /> {rc}</li>
                  ))}
                </ul>
              </div>
            )}
            {r.supporting && r.supporting.length > 0 && (
              <div>
                <p className="mb-1 font-semibold">Supporting Doctors</p>
                <ul className="grid grid-cols-1 gap-1 sm:grid-cols-2">
                  {r.supporting.map((d, i) => (
                    <li key={i} className="flex items-center justify-between rounded border border-border px-2 py-1">
                      <span className="font-medium">{d.doctor}</span>
                      <span className="text-muted-foreground">{d.status}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
