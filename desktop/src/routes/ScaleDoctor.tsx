import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Maximize2, FilePlus, Loader2, AlertTriangle, CheckCircle2, Info, Copy, Stethoscope } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { OrcaHandoff } from "@/components/OrcaHandoff";
import { openModelDialog, scalePreview, scaleOptions, prepareScaled, type ScaleResult, type ScaleOptionsResult, type ScaledCopyResult } from "@/api";
import { SCALE_LADDER_COPY, recommendBlurb, isRecommended, isCaution, riskLabel, fmtDims, partLabel } from "@/lib/scaleOptions";
import { useModelPath } from "@/hooks/useModelPath";
import { NotCheckedReason } from "@/components/GeometryNotice";

export function recTone(rec?: string): { token: string; label: string } {
  if (rec === "not checked") return { token: "--doctor-cost", label: "Fit not checked" };
  if (rec === "not recommended") return { token: "--stage-input", label: "Not recommended" };
  if (rec === "caution") return { token: "--doctor-cost", label: "Caution" };
  return { token: "--stage-validate", label: "Recommended" };
}

function dims(d?: { x: number; y: number; z: number }) {
  return d ? `${d.x.toFixed(1)} × ${d.y.toFixed(1)} × ${d.z.toFixed(1)} mm` : "—";
}

export default function ScaleDoctor() {
  const { path, fromSession, override } = useModelPath();
  const [pct, setPct] = useState(100);
  const [res, setRes] = useState<ScaleResult | null>(null);
  const [opts, setOpts] = useState<ScaleOptionsResult | null>(null);

  const m = useMutation({
    mutationFn: () => scalePreview(path!, pct),
    onSuccess: (d) => setRes(d),
  });

  const om = useMutation({
    mutationFn: () => scaleOptions(path!),
    onSuccess: (d) => setOpts(d),
  });

  const [scaled, setScaled] = useState<ScaledCopyResult | null>(null);
  const ex = useMutation({
    mutationFn: (scalePct: number) => prepareScaled(path!, scalePct),
    onSuccess: (d) => setScaled(d),
  });

  async function pick() {
    const p = await openModelDialog();
    if (!p) return;
    override(p); setRes(null); setOpts(null); setScaled(null);
  }

  async function copyPath(p: string) {
    try { await navigator.clipboard.writeText(p); } catch { /* clipboard unavailable */ }
  }

  const tone = recTone(res?.recommendation);
  const isStl = !!path && path.toLowerCase().endsWith(".stl");

  return (
    <div className="space-y-6">
      <PageHeader icon={Maximize2} title="Scale Doctor"
        subtitle="Preview a uniform resize, then create a new scaled copy when you're ready. Your original is never changed." />

      <div className="flex items-start gap-2 rounded-md border border-border p-3 text-sm">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <span className="text-muted-foreground">Uniform scaling only. Preview first, then <b>Prepare scaled copy</b> writes a new file — STL input is supported now; for 3MF, preview here and resize in Snapmaker Orca.</span>
      </div>

      <Card><CardContent className="flex flex-wrap items-center gap-3 p-5">
        <Button variant="secondary" size="sm" onClick={pick}>
          <FilePlus className="h-4 w-4" /> {path ? (fromSession ? "Using your open model — choose another" : "Choose another model") : "Open an STL or 3MF"}
        </Button>
        {path && <span className="truncate text-xs text-muted-foreground" title={path}>{path.split(/[\\/]/).pop()}</span>}
        <div className="ml-auto flex items-center gap-2">
          <label className="text-xs text-muted-foreground">Scale %</label>
          <input type="number" min={1} value={pct}
            onChange={(e) => setPct(Number(e.target.value) || 0)}
            className="w-24 rounded-md border border-border bg-background px-2 py-1 text-sm outline-none focus:border-primary" />
          <Button size="sm" onClick={() => m.mutate()} disabled={!path || pct <= 0 || m.isPending}>
            {m.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Maximize2 className="h-4 w-4" />} Preview
          </Button>
        </div>
      </CardContent></Card>

      {path && !isStl && (
        <div className="flex items-start gap-2 rounded-md border border-doctor-cost/40 bg-doctor-cost/5 p-3 text-sm">
          <Info className="mt-0.5 h-4 w-4 shrink-0" style={{ color: "hsl(var(--doctor-cost))" }} />
          <span className="text-muted-foreground">
            <b>Scaled export is available for STL.</b> 3MF scaled export isn't supported —
            multi-part / colour preservation can't be verified yet, so Studio won't write a
            copy it can't stand behind. Preview the scale here, then resize in Snapmaker Orca.
          </span>
        </div>
      )}

      {m.isError && <p className="text-sm text-risk">Couldn't read that file: {(m.error as Error).message}</p>}
      {res && !res.available && (res.status === "not_checked"
        ? <NotCheckedReason reason={res.reason} scope={res.scope} />
        : <p className="text-sm text-risk">{res.reason}</p>)}
      {res?.available && res.status === "not_checked" && <NotCheckedReason reason={res.reason} scope={res.scope} />}

      {res?.available && (
        <Card><CardContent className="space-y-3 p-5">
          <p className="flex items-center gap-2 text-sm font-semibold"
             style={{ color: `hsl(var(${tone.token}))` }}>
            {res.recommendation === "not recommended" || res.recommendation === "not checked" ? <AlertTriangle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
            {tone.label}
          </p>
          <div className="grid gap-3 text-sm sm:grid-cols-2">
            <div><p className="text-xs text-muted-foreground">Original size</p><p>{dims(res.original_dimensions)}</p></div>
            <div><p className="text-xs text-muted-foreground">Scaled size ({res.scale_percent}%)</p><p>{dims(res.scaled_dimensions)}</p></div>
            <div><p className="text-xs text-muted-foreground">Fits U1 build volume</p>
              <p>{res.fits_build_volume == null ? "Not checked" : res.fits_build_volume ? "Yes" : "No — exceeds the 270 mm bed"}</p></div>
            <div><p className="text-xs text-muted-foreground">Material change</p>
              <p>{res.estimated_material_delta ? `${res.estimated_material_delta.grams >= 0 ? "+" : ""}${res.estimated_material_delta.grams} g` : "—"}
                {res.estimated_cost_delta?.amount != null ? ` · ${res.estimated_cost_delta.amount >= 0 ? "+" : ""}$${Math.abs(res.estimated_cost_delta.amount).toFixed(2)}` : ""}</p></div>
          </div>
          {res.scale_percent != null && (
            <p className="text-sm">
              {res.scale_percent >= 100 ? "Making it bigger" : "Making it smaller"}: about{" "}
              <b>{Math.pow(res.scale_percent / 100, 3).toFixed(res.scale_percent >= 100 ? 1 : 2)}×</b>{" "}
              the material at {res.scale_percent}% scale (volume estimate, not slicer-accurate).
            </p>
          )}
          {res.risks && res.risks.length > 0 && (
            <ul className="space-y-1 text-xs text-muted-foreground">
              {res.risks.map((r, i) => (
                <li key={i} className="flex items-start gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {r}</li>
              ))}
            </ul>
          )}
          <p className="text-xs text-muted-foreground">{res.explanation}</p>
          {isStl && (
            <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
              <Button size="sm" onClick={() => ex.mutate(res.scale_percent ?? pct)} disabled={ex.isPending}>
                {ex.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FilePlus className="h-4 w-4" />}
                Prepare scaled copy
              </Button>
              <span className="text-xs text-muted-foreground">
                Create a new scaled copy at {res.scale_percent ?? pct}%. Your original file will not be changed.
              </span>
            </div>
          )}
        </CardContent></Card>
      )}

      {/* Scaled-copy result (writes a real file) */}
      {scaled && (
        <Card><CardContent className="space-y-3 p-5">
          {scaled.blocked ? (
            <div className="flex items-start gap-2 text-sm">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <span className="text-muted-foreground">{scaled.errors?.[0]}</span>
            </div>
          ) : (
            <>
              <p className="flex items-center gap-2 text-sm font-semibold text-stage-validate">
                <CheckCircle2 className="h-4 w-4" /> Scaled copy created at {scaled.scale_percent}%
              </p>
              <div className="grid gap-3 text-sm sm:grid-cols-2">
                <div><p className="text-xs text-muted-foreground">Original size</p>
                  <p>{scaled.original_mm?.map((d) => d.toFixed(1)).join(" × ")} mm</p></div>
                <div><p className="text-xs text-muted-foreground">Scaled size</p>
                  <p>{scaled.scaled_mm?.map((d) => d.toFixed(1)).join(" × ")} mm</p></div>
                <div><p className="text-xs text-muted-foreground">Fits U1 build volume (by size)</p>
                  <p>{scaled.fits_u1 ? "Yes — verify placement in Orca" : "No — exceeds the bed"}</p></div>
                <div><p className="text-xs text-muted-foreground">Validation</p>
                  <p>{scaled.validated_ok && !(scaled.errors && scaled.errors.length > 0)
                    ? "Structure/profile validated" : "See notes below"}</p></div>
              </div>
              <p className="truncate text-xs text-muted-foreground" title={scaled.output_path}>
                Saved as <b>{scaled.output_name}</b> (new file — original untouched).
              </p>
              {scaled.errors && scaled.errors.length > 0 && (
                <ul className="space-y-1 text-xs text-muted-foreground">
                  {scaled.errors.map((e, i) => <li key={i}>• {e}</li>)}
                </ul>
              )}
              <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
                {scaled.output_path && <OrcaHandoff outputPath={scaled.output_path} />}
                <Button size="sm" variant="secondary" onClick={() => copyPath(scaled.output_path!)}>
                  <Copy className="h-4 w-4" /> Copy path
                </Button>
                <Button size="sm" variant="secondary" asChild>
                  <Link to="/doctor/project"><Stethoscope className="h-4 w-4" /> Run Project Doctor again</Link>
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">This is a readiness estimate, not a print-success guarantee.</p>
            </>
          )}
        </CardContent></Card>
      )}
      {ex.isError && <p className="text-sm text-risk">Couldn't create the scaled copy: {(ex.error as Error).message}</p>}

      {/* Size Options Ladder */}
      {path && (
        <Card><CardContent className="space-y-3 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold">Size options for Snapmaker U1</p>
            <Button className="ml-auto" size="sm" variant="secondary"
              onClick={() => om.mutate()} disabled={om.isPending}>
              {om.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Maximize2 className="h-4 w-4" />} Show size options
            </Button>
          </div>

          {om.isError && <p className="text-sm text-risk">Couldn't read that file: {(om.error as Error).message}</p>}
          {opts && !opts.available && (opts.status === "not_checked"
          ? <NotCheckedReason reason={opts.reason} scope={opts.scope} />
          : <p className="text-sm text-risk">{opts.reason}</p>)}

          {opts?.available && opts.options && (
            <>
              <p className="text-sm">{recommendBlurb(opts)}</p>
              {opts.group_scaling_recommended && (
                <div className="flex items-start gap-2 rounded-md border border-border p-2.5 text-xs text-muted-foreground">
                  <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                  <span>{SCALE_LADDER_COPY.groupSame} {SCALE_LADDER_COPY.groupSeparate}</span>
                </div>
              )}
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-muted-foreground">
                    <tr>
                      <th className="py-1 pr-3">Scale</th>
                      {opts.current_parts?.map((p, i) => (
                        <th key={i} className="py-1 pr-3">{partLabel(p as any)}</th>
                      ))}
                      <th className="py-1 pr-3">Fit</th>
                      <th className="py-1 pr-3">Recommendation</th>
                      <th className="py-1 pr-3">Risk</th>
                      <th className="py-1">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {opts.options.map((o) => {
                      const rec = isRecommended(o, opts);
                      const caution = isCaution(o);
                      return (
                        <tr key={o.label}
                          className={rec ? "bg-stage-validate/10 font-medium" : ""}
                          style={rec ? { boxShadow: "inset 2px 0 0 0 hsl(var(--stage-validate))" } : undefined}>
                          <td className="py-1.5 pr-3 align-top">
                            <span className="tabular-nums">{o.scale_percent}%</span>
                            {rec && <span className="ml-1 rounded bg-stage-validate/15 px-1 text-[10px] text-stage-validate">recommended</span>}
                          </td>
                          {o.dimensions_by_part.map((d, i) => (
                            <td key={i} className="py-1.5 pr-3 align-top">{fmtDims(d.dimensions)}</td>
                          ))}
                          <td className="py-1.5 pr-3 align-top">
                            {o.dimensions_by_part.every((d) => d.fits_build_volume) ? "Fits" : "Too big"}
                          </td>
                          <td className="py-1.5 pr-3 align-top">
                            {caution && <AlertTriangle className="mr-1 inline h-3 w-3 text-risk" />}{o.recommendation}
                          </td>
                          <td className="py-1.5 pr-3 align-top">{riskLabel(o.risk_level)}</td>
                          <td className="py-1.5 align-top">
                            {isStl ? (
                              <Button size="sm" variant={rec ? "primary" : "secondary"}
                                onClick={() => ex.mutate(o.scale_percent)} disabled={ex.isPending}>
                                {ex.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FilePlus className="h-3.5 w-3.5" />}
                                Prepare {o.scale_percent}% copy
                              </Button>
                            ) : (
                              <span className="text-[11px] text-muted-foreground">
                                Preview only — resize in Orca
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {!isStl && (
                <div className="space-y-2 rounded-md border border-doctor-cost/40 bg-doctor-cost/5 p-3 text-xs">
                  <p className="text-muted-foreground">
                    Studio can preview 3MF scale and U1 fit. Creating a scaled 3MF is disabled until
                    colour, plate, and multi-part preservation are verified — so the rows above are
                    preview-only.
                  </p>
                  <p className="font-medium text-foreground">To resize this 3MF, open it in Snapmaker Orca and scale there:</p>
                  {path && <OrcaHandoff outputPath={path} />}
                </div>
              )}
              <ul className="space-y-1 text-xs text-muted-foreground">
                {opts.options.map((o) => (
                  <li key={o.label}><b>{o.label}:</b> {o.explanation}</li>
                ))}
                <li>{SCALE_LADDER_COPY.theoretical}</li>
                <li>{SCALE_LADDER_COPY.notGuarantee}</li>
              </ul>
            </>
          )}
        </CardContent></Card>
      )}
    </div>
  );
}
