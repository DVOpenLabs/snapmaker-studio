import { Navigate, Link } from "react-router-dom";
import {
  Boxes, FileBox, Loader2, Sparkles, AlertTriangle, RotateCw, Wand2,
  CheckCircle2, Plus, Palette, Layers, ChevronDown,
  Ruler, Gauge, ShieldCheck, Copy, Printer, Box, Coins,
} from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useSession } from "@/store/session";
import { insights as apiInsights, report as apiReport, mesh as apiMesh, printerCapabilities, firstLayer as apiFirstLayer, toolheadFit as apiToolheadFit, costEstimate as apiCostEstimate, printFindings as apiPrintFindings, bedFit as apiBedFit, mmDoctor as apiMmDoctor } from "@/api";
import { usePrinter } from "@/store/printer";
import { useFilament } from "@/store/filament";
import { useOpenFile } from "@/hooks/useOpenFile";
import { useToast } from "@/store/toast";
import { OrcaHandoff } from "@/components/OrcaHandoff";
import { PrepareModeChooser } from "@/components/PrepareModeChooser";
import { PrepareSettingsSummary, STARTER_NOTICE } from "@/components/PrepareSettingsSummary";
import { StrategyPicker } from "@/components/StrategyPicker";
import { BusinessDoctors } from "@/components/BusinessDoctors";
import { IntelligenceReport } from "@/components/IntelligenceReport";
import { FixPlan } from "@/components/FixPlan";
import { PlacementCard } from "@/components/PlacementCard";
import { PreflightCard } from "@/components/PreflightCard";
import { ColorPlanCard } from "@/components/ColorPlanCard";
import { DesignHealth } from "@/components/DesignHealth";
import { HeartPulse } from "lucide-react";
import { PrintRiskSignals } from "@/components/PrintRiskSignals";
import {
  familyLabel, verdictStatus, colorsLabel, partsLabel,
} from "@/lib/simple";

export default function DesignInsights() {
  const file = useSession((s) => s.file);
  const doctor = useSession((s) => s.doctor);
  const convert = useSession((s) => s.convert);
  const runDoctor = useSession((s) => s.runDoctor);
  const runConvert = useSession((s) => s.runConvert);
  const prepareMode = useSession((s) => s.prepareMode);
  const setPrepareMode = useSession((s) => s.setPrepareMode);
  const preview = useSession((s) => s.preview);
  const previewConvert = useSession((s) => s.previewConvert);
  const openFile = useOpenFile();
  const showToast = useToast((s) => s.show);
  const [showDetails, setShowDetails] = useState(false);
  const [showMore, setShowMore] = useState(false);       // advanced "what's in this" detail
  const [showStrategy, setShowStrategy] = useState(false); // strategy is optional for novices
  const [strategy, setStrategy] = useState("balanced");  // default Balanced (recommended)

  if (!file) return <Navigate to="/" replace />;

  const copyPath = (p: string) => {
    navigator.clipboard?.writeText(p).then(
      () => showToast("Path copied — paste it in your printer’s app"),
      () => showToast("Couldn’t copy the path"),
    );
  };

  const d = doctor.data;
  const TypeIcon = file.name.toLowerCase().endsWith(".stl") ? FileBox : Boxes;
  const status = d ? verdictStatus(d.verdict) : null;
  // Rich Project Intelligence (real geometry + materials), fetched read-only.
  const { data: ins } = useQuery({
    queryKey: ["insights", file.path],
    queryFn: () => apiInsights(file.path),
    enabled: doctor.status === "done",
  });
  const dims = ins?.dimensions_mm;
  // Validation Center: readiness + preservation report (read-only).
  const { data: rep } = useQuery({
    queryKey: ["report", file.path],
    queryFn: () => apiReport(file.path),
    enabled: doctor.status === "done",
  });
  // Real geometry diagnostics (volume / material estimate), read-only.
  const { data: meshData } = useQuery({
    queryKey: ["mesh", file.path],
    queryFn: () => apiMesh(file.path),
    enabled: doctor.status === "done",
  });
  // If a printer is connected, bed-fit uses its REAL bed; offline -> falls back to U1 270.
  const u1Host = usePrinter((s) => s.host);
  const { data: caps } = useQuery({
    queryKey: ["capabilities", u1Host],
    queryFn: () => printerCapabilities(u1Host),
    enabled: doctor.status === "done", retry: false, staleTime: 60000,
  });
  // First-Layer Intelligence: design footprint/stability fused with the printer's
  // REAL measured bed (when reachable); design-only otherwise. Read-only.
  const { data: firstLayer } = useQuery({
    queryKey: ["first-layer", file.path, u1Host],
    queryFn: () => apiFirstLayer(file.path, u1Host),
    enabled: doctor.status === "done", retry: false, staleTime: 30000,
  });
  // Toolhead-Fit: does this design's colour count fit the U1's toolheads?
  // Uses the connected printer's REAL toolhead count when reachable; else U1's 4.
  const { data: toolFit } = useQuery({
    queryKey: ["toolhead-fit", file.path, u1Host],
    queryFn: () => apiToolheadFit(file.path, u1Host),
    enabled: doctor.status === "done", retry: false, staleTime: 30000,
  });
  // Material cost: real geometry weight estimate x the user's filament price.
  const filamentPrice = useFilament((s) => s.pricePerKg);
  const filamentCurrency = useFilament((s) => s.currency);
  const { data: cost } = useQuery({
    queryKey: ["cost", file.path, filamentPrice, filamentCurrency],
    queryFn: () => apiCostEstimate(file.path, filamentPrice, filamentCurrency),
    enabled: doctor.status === "done", retry: false, staleTime: 30000,
  });
  // Multi-Material Doctor: one verdict for a multicolour U1 print.
  const { data: mm } = useQuery({
    queryKey: ["mmdoctor", file.path, u1Host],
    queryFn: () => apiMmDoctor(file.path, u1Host),
    enabled: doctor.status === "done", retry: false, staleTime: 30000,
  });
  // Bed-Fit / Out-of-Bounds Doctor: catch Orca's cryptic "out of bounds" pre-slice.
  const { data: bed } = useQuery({
    queryKey: ["bedfit", file.path, u1Host],
    queryFn: () => apiBedFit(file.path, u1Host),
    enabled: doctor.status === "done", retry: false, staleTime: 30000,
  });
  // Print risk signals from design + printer + history (no percentage; see #92).
  const { data: findings } = useQuery({
    queryKey: ["print-findings", file.path, u1Host],
    queryFn: () => apiPrintFindings(file.path, u1Host),
    enabled: doctor.status === "done", retry: false, staleTime: 30000,
  });
  const issues = [...(d?.validation_issues ?? []), ...(d?.compatibility_issues ?? [])];

  // Honest headline: a green "ready" verdict must not survive real print-setup risks
  // (e.g. more colours than toolheads). Demote the badge to match the warnings below.
  const setupRisk = !!(mm?.available && mm.multi_material && mm.overall_level && mm.overall_level !== "ok")
    || !!(bed?.available && bed.overall_level && bed.overall_level !== "ok")
    || !!(rep && !rep.ready);
  const headlineStatus = setupRisk && d && status?.tone === "ready" ? verdictStatus("HIGH_RISK") : status;

  // ---- Done: it's ready ------------------------------------------------------
  if (convert.status === "done" && convert.data) {
    return (
      <div className="mx-auto max-w-xl space-y-4">
        <Card>
          <CardContent className="flex flex-col items-center gap-4 p-8 text-center">
            <div className={cn("flex h-16 w-16 items-center justify-center rounded-full",
              setupRisk ? "bg-repairable/15 text-repairable" : "bg-ready/15 text-ready")}>
              <CheckCircle2 className="h-9 w-9" />
            </div>
            <div>
              <h2 className="text-xl font-semibold">{setupRisk ? "U1 copy created — review setup before slicing" : "U1 copy created"}</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                We made a U1 copy of <b>{file.name}</b>. Your original file is not modified.
                {setupRisk
                  ? " Print-setup risks remain (see the checks) — open in Snapmaker Orca, arrange plates and review supports/colours before slicing."
                  : " This is an advisory check, not a guarantee — slice in Snapmaker Orca to confirm."}
              </p>
            </div>
            <div className="w-full rounded-lg border border-border bg-muted/30 p-3 text-left text-sm">
              <p className="font-medium">{convert.data.output_name}</p>
              <p className="text-xs text-muted-foreground">New file saved next to your original — use “Copy path” below.</p>
            </div>
            <div className="text-left text-sm text-muted-foreground">
              <p className="mb-1 font-medium text-foreground">What now?</p>
              <p>1. Open it in Snapmaker Orca to slice and print (one click below)</p>
              <p>2. Or copy the file path and open it in Snapmaker Orca yourself</p>
            </div>
            <OrcaHandoff outputPath={convert.data.output_path} originalPath={file?.path} />
            <div className="flex flex-wrap justify-center gap-2">
              <Button variant="secondary" onClick={() => copyPath(convert.data!.output_path)}>
                <Copy className="h-4 w-4" /> Copy path
              </Button>
              <Button variant="secondary" asChild>
                <Link to="/printers"><Printer className="h-4 w-4" /> Check printer status</Link>
              </Button>
              <Button onClick={openFile}>
                <Plus className="h-4 w-4" /> Open another model
              </Button>
            </div>
          </CardContent>
        </Card>
        {convert.data.settings_summary && <PrepareSettingsSummary summary={convert.data.settings_summary} mode={convert.data.prepare_mode} isStl={file.ext === "stl"} onPrepareRecommended={() => runConvert("recommended")} />}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl space-y-4">
      {/* heading */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          <TypeIcon className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <h2 className="truncate text-xl font-semibold tracking-tight">{file.name}</h2>
          <p className="text-xs text-muted-foreground">
            {doctor.status === "loading"
              ? "Looking at your design…"
              : doctor.status === "done"
                ? "Checked — here's what we found. Press Prepare U1 copy when you're set."
                : "Let's see what's in your design."}
          </p>
        </div>
      </div>

      {file.ext !== "stl" && <PrepareModeChooser mode={prepareMode} onModeChange={setPrepareMode} onCustom={previewConvert} previewing={preview.status === "loading"} />}
      {file.ext === "stl" && <p className="rounded-md border border-border p-3 text-sm text-muted-foreground">{STARTER_NOTICE}</p>}
      {preview.status === "done" && preview.data?.settings_summary && <PrepareSettingsSummary summary={preview.data.settings_summary} mode={preview.data.prepare_mode} isStl={file.ext === "stl"} preview onPreparePreserve={() => runConvert("preserve")} onPrepareRecommended={() => runConvert("recommended")} />}
      {preview.status === "error" && <p className="text-sm text-risk">{preview.error}</p>}

      {/* At-a-glance summary + primary action, visible without scrolling */}
      {doctor.status === "done" && d && headlineStatus && (
        <Card className="surface-raised">
          <CardContent className="flex flex-wrap items-center gap-4 p-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className={cn("text-sm font-semibold",
                  headlineStatus.tone === "ready" ? "text-ready" : headlineStatus.tone === "risk" ? "text-risk" : "text-repairable")}>
                  {headlineStatus.label}
                </span>
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">We make a U1 profile copy — your original is never changed.</p>
            </div>
            <Button onClick={() => runConvert()} disabled={convert.status === "loading" || preview.status === "loading"} className="shrink-0">
              {convert.status === "loading" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
              {convert.status === "loading" ? "Preparing…" : "Prepare U1 copy"}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* looking at it */}
      {doctor.status === "loading" && (
        <Card><CardContent className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Looking at your design…
        </CardContent></Card>
      )}

      {doctor.status === "error" && (
        <Card><CardContent className="space-y-3 p-6">
          <p className="flex items-center gap-2 text-sm text-risk"><AlertTriangle className="h-4 w-4" /> We couldn't open this design.</p>
          <p className="text-sm text-muted-foreground">{doctor.error}</p>
          <Button variant="secondary" size="sm" onClick={runDoctor}><RotateCw className="h-4 w-4" /> Try again</Button>
        </CardContent></Card>
      )}

      {doctor.status === "done" && d && status && (
        <>
          {/* Beginner Fix Plan — the one prioritized "what do I do next" list */}
          <FixPlan
            doctor={d}
            isStl={file.name.toLowerCase().endsWith(".stl")}
            report={rep}
            bed={bed}
            mm={mm}
            mesh={meshData}
          />

          {/* These three used to live only under "More tools", which meant the
              beginner path — Check my model — never showed the checks a beginner
              most needs. A project's objects can be off the plate, its colours
              can outnumber the toolheads, and neither is visible from a mesh
              report. 3MF only: an STL carries none of this. */}
          {file.ext !== "stl" && (
            <>
              <PlacementCard path={file.path} />
              <ColorPlanCard path={file.path} />
              <PreflightCard path={file.path} />
            </>
          )}

          {/* Studio Intelligence Report — the one-screen synthesis (the product) */}
          <IntelligenceReport filePath={file.path} host={u1Host} />

          {/* risk signals Studio found: specific findings and limits, no percentage (#92) */}
          {findings && <PrintRiskSignals findings={findings} />}

          {/* out-of-bounds doctor — only when there's something to warn about */}
          {bed?.available && bed.overall_level && bed.overall_level !== "ok" && (
            <Card>
              <CardContent className="space-y-2 p-5">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-sm font-semibold"><Ruler className="h-4 w-4 text-primary" /> Will it fit your U1?</span>
                  <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${
                    bed.overall_level === "warn" ? "bg-repairable/10 text-repairable" : "bg-risk/10 text-risk"}`}>
                    {bed.overall_level === "warn" ? "Tight fit" : "Out of bounds"}
                  </span>
                </div>
                {bed.overall_text && <p className="text-sm text-muted-foreground">{bed.overall_text}</p>}
                {bed.findings && bed.findings.map((f, i) => (
                  <p key={i} className={`flex items-start gap-1.5 text-xs ${f.level === "risk" ? "text-risk" : f.level === "warn" ? "text-repairable" : "text-muted-foreground"}`}>
                    {f.level === "ok"
                      ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-60" />
                      : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />} {f.text}
                  </p>
                ))}
                {bed.fixes && bed.fixes.length > 0 && (
                  <div className="rounded-md bg-ready/5 p-2">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-ready">How to fix it</p>
                    <ul className="mt-1 space-y-1 text-xs text-muted-foreground">
                      {bed.fixes.map((fx, i) => (
                        <li key={i} className={`flex items-start gap-1.5 ${i === 0 ? "font-medium text-foreground" : ""}`}><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ready" /> {fx}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <p className="text-[11px] text-muted-foreground opacity-70">Checked against {bed.bed_source} ({bed.bed_mm?.x}×{bed.bed_mm?.y}×{bed.bed_mm?.z} mm) — before Orca even opens.</p>
              </CardContent>
            </Card>
          )}

          {/* multi-material doctor — only for multicolour designs */}
          {mm?.available && mm.multi_material && (
            <Card>
              <CardContent className="space-y-2 p-5">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-sm font-semibold"><Palette className="h-4 w-4 text-primary" /> Multi-material check</span>
                  <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${
                    mm.overall_level === "ok" ? "bg-ready/10 text-ready" : mm.overall_level === "warn" ? "bg-repairable/10 text-repairable" : "bg-risk/10 text-risk"}`}>
                    {mm.colors} colours · {mm.heads} toolheads
                  </span>
                </div>
                {mm.overall_text && <p className="text-sm text-muted-foreground">{mm.overall_text}</p>}
                {mm.findings && mm.findings.map((f, i) => (
                  <p key={i} className={`flex items-start gap-1.5 text-xs ${f.level === "risk" ? "text-risk" : f.level === "warn" ? "text-repairable" : "text-muted-foreground"}`}>
                    {f.level === "ok"
                      ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-60" />
                      : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />} {f.text}
                  </p>
                ))}
                {mm.fixes && mm.fixes.length > 0 && (
                  <div className="rounded-md bg-ready/5 p-2">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-ready">How to fix it</p>
                    <ul className="mt-1 space-y-1 text-xs text-muted-foreground">
                      {mm.fixes.map((fx, i) => (
                        <li key={i} className="flex items-start gap-1.5"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ready" /> {fx}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* what's in this design */}
          <Card>
            <CardContent className="space-y-4 p-5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Step 1 · Understand</p>
              <div className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4 text-primary" /> What's in this design</div>
              <ul className="space-y-2 text-sm">
                <li className="flex items-center gap-2"><FileBox className="h-4 w-4 text-muted-foreground" /> {familyLabel(d.family)}</li>
                {dims && <li className="flex items-center gap-2"><Ruler className="h-4 w-4 text-muted-foreground" /> {dims.x} × {dims.y} × {dims.z} mm</li>}
                {colorsLabel(d.filament_count) && <li className="flex items-center gap-2"><Palette className="h-4 w-4 text-muted-foreground" /> {colorsLabel(d.filament_count)}</li>}
                {partsLabel(d.object_count) && <li className="flex items-center gap-2"><Layers className="h-4 w-4 text-muted-foreground" /> {partsLabel(d.object_count)}{(ins?.plates ?? 0) > 1 ? ` · ${ins!.plates} plates` : ""}</li>}
                {d.painted && <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-ready" /> painted areas kept</li>}
                {cost?.available && (
                  <li className="flex items-center gap-2">
                    <Coins className="h-4 w-4 text-muted-foreground" />
                    ~{cost.currency}{cost.cost} in filament
                    <span className="text-xs text-muted-foreground">({cost.grams} g at {cost.currency}{cost.price_per_kg}/kg)</span>
                  </li>
                )}
                {/* Pricing intentionally lives only in the dedicated Cost / Pricing / Profit
                    section below — not as a hero line on the readiness summary. */}
                {/* Advanced detail kept available but out of the novice's first glance */}
                {showMore && (
                  <>
                    {ins?.complexity && <li className="flex items-center gap-2"><Gauge className="h-4 w-4 text-muted-foreground" /> {ins.complexity} complexity{ins.triangles ? ` · ${ins.triangles.toLocaleString()} triangles` : ""}</li>}
                    {meshData?.available && meshData.volume_cm3 != null && meshData.volume_cm3 > 0 && (
                      <li className="flex items-center gap-2"><Box className="h-4 w-4 text-muted-foreground" /> {meshData.volume_cm3} cm³{meshData.material_estimate_g != null ? ` · ~${meshData.material_estimate_g} g PLA (estimate)` : ""}</li>
                    )}
                  </>
                )}
              </ul>
              {(ins?.complexity || (meshData?.available && (meshData.volume_cm3 ?? 0) > 0)) && (
                <button onClick={() => setShowMore((v) => !v)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                  <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", showMore && "rotate-180")} /> {showMore ? "Less detail" : "More detail"}
                </button>
              )}
              {ins?.materials && ins.materials.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 pt-1">
                  {ins.materials.map((m, i) => (
                    <span key={i} className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-xs">
                      <span className="h-3 w-3 rounded-full border border-border" style={{ backgroundColor: m.color }} />
                      {m.type ?? "filament"}
                    </span>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Design Health — real geometry verdicts in plain language */}
          {meshData?.available && (
            <Card>
              <CardContent className="space-y-3 p-5">
                <div className="flex items-center gap-2 text-sm font-semibold"><HeartPulse className="h-4 w-4 text-primary" /> Design Health</div>
                <DesignHealth mesh={meshData} dims={dims} bed={caps?.bed_mm} mode="simple" />
              </CardContent>
            </Card>
          )}

          {/* Business Intelligence Layer — Cost / Pricing / Profit Doctors */}
          <BusinessDoctors filePath={file.path} host={u1Host} />

          {/* First-Layer Intelligence — design footprint × the printer's real bed */}
          {firstLayer?.available && firstLayer.findings && (
            <Card>
              <CardContent className="space-y-3 p-5">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-sm font-semibold"><Layers className="h-4 w-4 text-primary" /> First-layer check</span>
                  <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
                    firstLayer.overall_level === "ok" ? "bg-ready/10 text-ready" : firstLayer.overall_level === "warn" ? "bg-repairable/10 text-repairable" : "bg-risk/10 text-risk")}>
                    {firstLayer.bed_aware ? "Your bed" : "Design"}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">{firstLayer.overall_text}</p>
                <ul className="space-y-1.5 text-sm">
                  {firstLayer.findings.map((f, i) => (
                    <li key={i} className="flex items-start gap-2">
                      {f.level === "ok"
                        ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ready" />
                        : <AlertTriangle className={cn("mt-0.5 h-4 w-4 shrink-0", f.level === "risk" ? "text-risk" : "text-repairable")} />}
                      <span className="text-muted-foreground">{f.text}</span>
                    </li>
                  ))}
                </ul>
                <p className="text-[11px] text-muted-foreground">
                  {firstLayer.bed_aware
                    ? "Uses your U1's actual measured bed — read-only."
                    : "Connect your U1 in the Printer Hub to check against your real bed surface."}
                </p>
              </CardContent>
            </Card>
          )}

          {/* Colors & toolheads — does this design's colour count fit the U1? */}
          {toolFit?.available && (toolFit.color_count ?? 0) > 1 && (
            <Card>
              <CardContent className="space-y-3 p-5">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-sm font-semibold"><Palette className="h-4 w-4 text-primary" /> Colors &amp; toolheads</span>
                  <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
                    toolFit.overall_level === "ok" ? "bg-ready/10 text-ready" : toolFit.overall_level === "warn" ? "bg-repairable/10 text-repairable" : "bg-risk/10 text-risk")}>
                    {toolFit.color_count} colors / {toolFit.toolhead_count} heads
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">{toolFit.overall_text}</p>
                <ul className="space-y-1.5 text-sm">
                  {toolFit.findings?.map((f, i) => (
                    <li key={i} className="flex items-start gap-2">
                      {f.level === "ok"
                        ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ready" />
                        : <AlertTriangle className={cn("mt-0.5 h-4 w-4 shrink-0", f.level === "risk" ? "text-risk" : "text-repairable")} />}
                      <span className="text-muted-foreground">{f.text}</span>
                    </li>
                  ))}
                </ul>
                <p className="text-[11px] text-muted-foreground">
                  {toolFit.printer_aware
                    ? "Based on your connected U1's actual toolheads — read-only."
                    : "Based on the U1's 4 toolheads. Connect your U1 in the Printer Hub to confirm."}
                </p>
              </CardContent>
            </Card>
          )}

          {/* Validation Center — what Studio checked + what's preserved/changes/at-risk */}
          {rep && (
            <Card>
              <CardContent className="space-y-4 p-5">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Step 2 · Validate</p>
                <div className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck className="h-4 w-4 text-primary" /> Validation Center</div>
                <p className="-mt-2 text-xs text-muted-foreground">What Studio checked for your U1 — and what we keep, change, or can’t carry over.</p>
                <ul className="space-y-1.5 text-sm">
                  {rep.checks.map((c, i) => (
                    <li key={i} className="flex items-start gap-2">
                      {c.status === "pass"
                        ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ready" />
                        : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-repairable" />}
                      <span><span className="font-medium">{c.name}</span> — <span className="text-muted-foreground">{c.detail}</span></span>
                    </li>
                  ))}
                </ul>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 text-xs">
                  <div>
                    <p className="mb-1 font-medium text-ready">Kept</p>
                    <ul className="space-y-1 text-muted-foreground">{rep.preserved.map((x, i) => <li key={i}>• {x}</li>)}</ul>
                  </div>
                  <div>
                    <p className="mb-1 font-medium">Changes</p>
                    <ul className="space-y-1 text-muted-foreground">{rep.changes.length ? rep.changes.map((x, i) => <li key={i}>• {x}</li>) : <li>• none</li>}</ul>
                  </div>
                  <div>
                    <p className="mb-1 font-medium text-repairable">At risk</p>
                    <ul className="space-y-1 text-muted-foreground">{rep.at_risk.length ? rep.at_risk.map((x, i) => <li key={i}>• {x}</li>) : <li>• nothing</li>}</ul>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* readiness */}
          <Card>
            <CardContent className="space-y-3 p-5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Step 3 · Prepare</p>
              <span className="text-sm font-medium">Before you prepare</span>
              <p className={cn("flex items-center gap-2 text-sm",
                headlineStatus?.tone === "ready" ? "text-ready" : headlineStatus?.tone === "risk" ? "text-risk" : "text-repairable")}>
                <span>{headlineStatus?.icon}</span> {headlineStatus?.label}
              </p>

              {issues.length > 0 && (
                <div>
                  <button onClick={() => setShowDetails((v) => !v)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                    <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", (showDetails || status.tone === "risk") && "rotate-180")} /> What needs fixing?
                  </button>
                  {(showDetails || status.tone === "risk") && (
                    <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                      {issues.map((it: string, i: number) => (
                        <li key={i} className="flex items-start gap-2"><span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-repairable" />{it}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <div className="border-t border-border pt-3">
                <button onClick={() => setShowStrategy((v) => !v)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                  <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", showStrategy && "rotate-180")} /> Change how it's prepared <span className="opacity-70">(optional)</span>
                </button>
                {showStrategy
                  ? <div className="pt-3"><StrategyPicker filePath={file.path} mode="simple" value={strategy} onChange={setStrategy} /></div>
                  : <p className="pt-1 text-xs text-muted-foreground">We'll use the recommended setup. No need to choose unless you want to.</p>}
              </div>

              <Button className="w-full" onClick={() => runConvert()} disabled={convert.status === "loading" || preview.status === "loading"}>
                {convert.status === "loading" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                {convert.status === "loading" ? "Preparing…" : "Prepare U1 copy"}
              </Button>
              <p className="text-center text-xs text-muted-foreground">We never change your original file.</p>

              {convert.status === "error" && (
                <p className="flex items-center justify-center gap-2 text-xs text-risk"><AlertTriangle className="h-3.5 w-3.5" /> {convert.error}</p>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
