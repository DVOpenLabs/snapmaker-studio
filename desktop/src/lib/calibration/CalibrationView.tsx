import { useState } from "react";
import { Palette } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { evaluateCalibration } from "@/lib/calibrationApi";
import type { CalibrationResponse } from "@/lib/calibrationApi";

const field = "rounded-md border border-border bg-card px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50";

export default function CalibrationView() {
  const [source, setSource] = useState<"ditherforge_txt" | "kromacut_json">("ditherforge_txt");
  const [content, setContent] = useState("#E94B35 td=0.8 Vermilion\n#2878B8 td Blue\n#F2C14E td=1.1 Ochre");
  const [family, setFamily] = useState<"frontlit" | "backlit">("frontlit");
  const [layerHeight, setLayerHeight] = useState("0.20");
  const [measurementText, setMeasurementText] = useState("#DA4D3C\n\n#2D70A8");
  const [ownedText, setOwnedText] = useState("PLA Red #D94335\nPLA Blue #236FAE\nPLA Yellow #E8BB43");
  const [response, setResponse] = useState<CalibrationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true); setError(null); setResponse(null);
    try {
      const physical_colors: Record<string, string> = {};
      measurementText.split(/\r?\n/).forEach((row, index) => { const color = row.trim(); if (color) physical_colors[String(index)] = color; });
      const owned_filaments = ownedText.split(/\r?\n/).map((row) => row.trim()).filter(Boolean).map((row) => {
        const match = row.match(/^(.*?)\s+(#[0-9a-fA-F]{6})$/);
        if (!match) throw new Error("Owned filaments use one per line: label #RRGGBB");
        return { label: match[1], color: match[2] };
      });
      const result = await evaluateCalibration({ source, content, family, layer_height_mm: Number(layerHeight), nozzle_mm: 0.4,
        material: "PLA", physical_colors, owned_filaments });
      setResponse(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Calibration could not be evaluated.");
    } finally { setBusy(false); }
  };

  return <main className="space-y-5 p-6">
    <PageHeader icon={Palette} title="Palette calibration" subtitle="Compare palette targets with your physical readings and owned filament colours. This is an advisory check." />
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(20rem,0.8fr)]">
      <section className="space-y-3 rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold">Palette input</h2>
        <div className="flex flex-wrap gap-2">
          <select className={field} aria-label="Palette format" value={source} onChange={(e) => setSource(e.target.value as typeof source)}>
            <option value="ditherforge_txt">DitherForge TXT</option><option value="kromacut_json">Kromacut palette JSON</option>
          </select>
          <select className={field} aria-label="Palette family" value={family} onChange={(e) => setFamily(e.target.value as typeof family)}>
            <option value="frontlit">Frontlit</option><option value="backlit">Backlit</option>
          </select>
          <label className="flex items-center gap-2 text-sm">Layer height (mm)
            <input className={`${field} w-24`} aria-label="Layer height" type="number" min="0.01" step="0.01" value={layerHeight} onChange={(e) => setLayerHeight(e.target.value)} />
          </label>
          <label className={`${field} cursor-pointer`}>Load palette<input className="sr-only" aria-label="Load palette file" type="file" accept=".txt,.json,text/plain,application/json" onChange={async (e) => { const file = e.target.files?.[0]; if (file) setContent(await file.text()); }} /></label>
        </div>
        <textarea className={`${field} min-h-40 w-full font-mono`} aria-label="Palette content" value={content} onChange={(e) => setContent(e.target.value)} />
        <p className="text-xs text-muted-foreground">DitherForge rows accept #RRGGBB td label or td=…; missing TD uses 1.0, nominal, not measured.</p>
      </section>
      <section className="space-y-3 rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold">Physical readings and owned filaments</h2>
        <label className="block space-y-1 text-sm">Physical colors, one #RRGGBB per palette row<textarea className={`${field} mt-1 min-h-24 w-full font-mono`} aria-label="Physical colors" value={measurementText} onChange={(e) => setMeasurementText(e.target.value)} /></label>
        <label className="block space-y-1 text-sm">Owned filament alternatives, one label #RRGGBB per line<textarea className={`${field} mt-1 min-h-24 w-full font-mono`} aria-label="Owned filaments" value={ownedText} onChange={(e) => setOwnedText(e.target.value)} /></label>
        <Button size="sm" disabled={busy || !content.trim()} onClick={() => void run()}>{busy ? "Comparing…" : "Compare palette"}</Button>
        {error && <p role="alert" className="text-sm text-risk">{error}</p>}
      </section>
    </div>
    {response?.status === "unknown" && <section className="rounded-lg border border-border bg-card p-4" role="status">
      <h2 className="font-semibold">Palette version not evaluated</h2><p className="mt-1 text-sm text-muted-foreground">{response.decoded.diagnostics.map((d) => d.code).join(", ")}. The input is preserved as unknown.</p>
    </section>}
    {response?.result && <section className="space-y-4 rounded-lg border border-border bg-card p-4">
      <div><h2 className="font-semibold">Comparison</h2><p className="text-sm text-muted-foreground">Basis {response.result.calibration_basis.family} · {response.result.calibration_basis.layer_height_mm.toFixed(2)} mm · {response.result.calibration_basis.material}</p><code className="break-all text-xs text-muted-foreground">{response.result.calibration_basis.calibration_basis_id}</code></div>
      <div className="space-y-2">{response.result.entries.map((entry, index) => <article className="grid gap-3 rounded-md border border-border p-3 md:grid-cols-[minmax(8rem,1fr)_5rem_5rem_minmax(12rem,1fr)] md:items-center" key={`${entry.label}-${index}`}>
        <div><h3 className="font-medium">{entry.label}</h3><p className="text-xs text-muted-foreground">TD {entry.td} · {entry.td_provenance === "derived" ? "nominal, not measured" : "palette value"}</p></div>
        <div className="flex items-center gap-2 text-xs"><span className="h-6 w-6 rounded border border-border" style={{ backgroundColor: entry.simulated_color }} />Simulated</div>
        <div className="flex items-center gap-2 text-xs"><span className="h-6 w-6 rounded border border-border" style={{ backgroundColor: entry.physical_color ?? "transparent" }} />{entry.physical_color ? "Physical" : "No reading"}</div>
        <div className="text-xs text-muted-foreground">{entry.alternatives.length ? <>Owned alternatives (advisory): {entry.alternatives.map((alt) => `${alt.label} · distance ${alt.distance}`).join("; ")}</> : "No owned color alternatives"}</div>
      </article>)}</div>
      <p className="text-sm text-muted-foreground">{response.result.advisory}</p>
      <p className="text-xs text-muted-foreground">Saved locally · input revision {response.result.inputs_revision.revision}</p>
    </section>}
  </main>;
}
