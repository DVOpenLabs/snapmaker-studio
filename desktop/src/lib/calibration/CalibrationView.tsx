import { useEffect, useRef, useState } from "react";
import { Palette } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { calibrationHistory, evaluateCalibration } from "@/lib/calibrationApi";
import type { CalibrationResponse, CalibrationRun } from "@/lib/calibrationApi";

const field = "rounded-md border border-border bg-card px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50";

export default function CalibrationView() {
  const generation = useRef(0);
  const importGeneration = useRef(0);
  useEffect(() => () => { generation.current += 1; importGeneration.current += 1; }, []);
  const [source, setSource] = useState<"ditherforge_txt" | "kromacut_json">("ditherforge_txt");
  const [content, setContent] = useState("#E94B35 td=0.8 Vermilion\n#2878B8 td Blue\n#F2C14E td=1.1 Ochre");
  const [family, setFamily] = useState<"frontlit" | "backlit">("frontlit");
  const [layerHeight, setLayerHeight] = useState("0.20");
  const [measurementText, setMeasurementText] = useState("");
  const [ownedText, setOwnedText] = useState("");
  const [nozzle, setNozzle] = useState("0.4");
  const [material, setMaterial] = useState("PLA");
  const [model, setModel] = useState("");
  const [firstLayer, setFirstLayer] = useState("0.20");
  const [history, setHistory] = useState<CalibrationRun[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const historyGeneration = useRef(0);
  useEffect(() => () => { historyGeneration.current += 1; }, []);
  const [response, setResponse] = useState<CalibrationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function invalidate(clearReadings = false) {
    generation.current += 1;
    importGeneration.current += 1;
    setResponse(null); setError(null); setBusy(false);
    if (clearReadings) setMeasurementText("");
  }
  async function loadHistory() {
    const request = ++historyGeneration.current;
    setHistoryBusy(true); setHistoryError(null);
    try {
      const saved = await calibrationHistory();
      if (request === historyGeneration.current) setHistory(saved.runs);
    } catch (cause) {
      if (request === historyGeneration.current) setHistoryError(cause instanceof Error ? cause.message : "History could not be loaded.");
    } finally { if (request === historyGeneration.current) setHistoryBusy(false); }
  }
  const run = async () => {
    const request = ++generation.current;
    setBusy(true); setError(null); setResponse(null);
    try {
      const physical_colors: Record<string, string> = {};
      measurementText.split(/\r?\n/).forEach((row, index) => { const color = row.trim(); if (color) physical_colors[String(index)] = color; });
      const owned_filaments = ownedText.split(/\r?\n/).map((row) => row.trim()).filter(Boolean).map((row) => {
        const match = row.match(/^(.*?)\s+(#[0-9a-fA-F]{6})$/);
        if (!match) throw new Error("Owned filaments use one per line: label #RRGGBB");
        return { label: match[1], color: match[2] };
      });
      const result = await evaluateCalibration({ source, content, family, layer_height_mm: Number(layerHeight), nozzle_mm: Number(nozzle),
        material, model, first_layer_height_mm: Number(firstLayer), physical_colors, owned_filaments });
      if (request === generation.current) setResponse(result);
    } catch (cause) {
      if (request === generation.current) setError(cause instanceof Error ? cause.message : "Calibration could not be evaluated.");
    } finally { if (request === generation.current) setBusy(false); }
  };

  return <main className="space-y-5 p-6">
    <PageHeader icon={Palette} title="Palette calibration" subtitle="Compare palette targets with your physical readings and owned filament colours. This is an advisory check." />
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(20rem,0.8fr)]">
      <section className="space-y-3 rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold">Palette input</h2>
        <div className="flex flex-wrap gap-2">
          <select className={field} aria-label="Palette format" value={source} onChange={(e) => { invalidate(true); setSource(e.target.value as typeof source); }}>
            <option value="ditherforge_txt">DitherForge TXT</option><option value="kromacut_json">Kromacut palette JSON</option>
          </select>
          <select className={field} aria-label="Palette family" value={family} onChange={(e) => { invalidate(true); setFamily(e.target.value as typeof family); }}>
            <option value="frontlit">Frontlit</option><option value="backlit">Backlit</option>
          </select>
          <label className="flex items-center gap-2 text-sm">Layer height (mm)
            <input className={`${field} w-24`} aria-label="Layer height" type="number" min="0.01" step="0.01" value={layerHeight} onChange={(e) => { invalidate(true); setLayerHeight(e.target.value); }} />
          </label>
          <label className={`${field} cursor-pointer`}>Load palette<input className="sr-only" aria-label="Load palette file" type="file" accept=".txt,.json,.kpal,text/plain,application/json" onChange={async (e) => {
            const file = e.target.files?.[0]; if (!file) return;
            invalidate(true); setContent("");
            const request = ++importGeneration.current;
            try {
              if (file.size > 512_000) throw new Error("Palette file must be at most 512 KB.");
              const text = await file.text();
              if (request !== importGeneration.current) return;
              setContent(text); setSource(/\.(kpal|json)$/i.test(file.name) ? "kromacut_json" : "ditherforge_txt");
            } catch (cause) { if (request === importGeneration.current) setError(cause instanceof Error ? cause.message : "Palette could not be loaded."); }
          }} /></label>
        </div>
        <textarea className={`${field} min-h-40 w-full font-mono`} aria-label="Palette content" value={content} onChange={(e) => { invalidate(true); setContent(e.target.value); }} />
        <p className="text-xs text-muted-foreground">DitherForge rows accept #RRGGBB 1.9 Label or td=…; lines starting with # and a space are comments; missing TD uses 1.0, nominal, not measured.</p>
        <div className="flex flex-wrap gap-3">
          <label className="text-sm">Nozzle (mm)<input className={field} aria-label="Nozzle diameter" type="number" min="0.01" step="0.01" value={nozzle} onChange={(e) => { invalidate(true); setNozzle(e.target.value); }} /></label>
          <label className="text-sm">First layer (mm)<input className={field} aria-label="First layer height" type="number" min="0.01" step="0.01" value={firstLayer} onChange={(e) => { invalidate(true); setFirstLayer(e.target.value); }} /></label>
          <label className="text-sm">Material<input className={field} aria-label="Material" maxLength={32} value={material} onChange={(e) => { invalidate(true); setMaterial(e.target.value); }} /></label>
          <label className="text-sm">Calibration model / revision (optional)<input className={field} aria-label="Calibration model" maxLength={128} value={model} onChange={(e) => { invalidate(true); setModel(e.target.value); }} /></label>
        </div>
      </section>
      <section className="space-y-3 rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold">Physical readings and owned filaments</h2><p className="text-xs text-muted-foreground">Readings start empty and are cleared when the palette or calibration basis changes. Enter your own observations; simulated targets are never physical measurements.</p>
        <label className="block space-y-1 text-sm">Physical colors, one #RRGGBB per palette row<textarea className={`${field} mt-1 min-h-24 w-full font-mono`} aria-label="Physical colors" value={measurementText} onChange={(e) => { invalidate(false); setMeasurementText(e.target.value); }} /></label>
        <label className="block space-y-1 text-sm">Owned filament alternatives, one label #RRGGBB per line<textarea className={`${field} mt-1 min-h-24 w-full font-mono`} aria-label="Owned filaments" value={ownedText} onChange={(e) => { invalidate(false); setOwnedText(e.target.value); }} /></label>
        <Button size="sm" disabled={busy || !content.trim() || !material.trim()} onClick={() => void run()}>{busy ? "Comparing…" : "Compare palette"}</Button>
        {error && <p role="alert" className="text-sm text-risk">{error}</p>}
      </section>
    </div>
    {response?.status === "unknown" && <section className="rounded-lg border border-border bg-card p-4" role="status">
      <h2 className="font-semibold">Palette version not evaluated</h2><p className="mt-1 text-sm text-muted-foreground">{response.decoded.diagnostics.map((d) => d.code).join(", ")}. The input is preserved as unknown.</p>
    </section>}
    {response?.result && <section className="space-y-4 rounded-lg border border-border bg-card p-4">
      <div><h2 className="font-semibold">Comparison</h2><p className="text-sm text-muted-foreground">Basis {response.result.calibration_basis.family} · {response.result.calibration_basis.layer_height_mm.toFixed(2)} mm · {response.result.calibration_basis.material} · nozzle {response.result.calibration_basis.nozzle_mm} mm · first layer {response.result.calibration_basis.first_layer_height_mm ?? "unknown"} mm · {response.result.calibration_basis.source ?? "unknown source"} · model {response.result.calibration_basis.model || "not recorded"}</p><code className="break-all text-xs text-muted-foreground">{response.result.calibration_basis.calibration_basis_id}</code></div>
      <div className="space-y-2">{response.result.entries.map((entry, index) => <article className="grid gap-3 rounded-md border border-border p-3 md:grid-cols-[minmax(8rem,1fr)_5rem_5rem_minmax(12rem,1fr)] md:items-center" key={`${entry.label}-${index}`}>
        <div><h3 className="font-medium">{entry.label}{entry.enabled === false ? " (disabled in palette)" : ""}</h3><p className="text-xs text-muted-foreground">TD {entry.td} · {entry.td_provenance === "derived" ? "nominal, not measured" : "palette value"}</p></div>
        <div className="flex items-center gap-2 text-xs"><span className="h-6 w-6 rounded border border-border" style={{ backgroundColor: entry.simulated_color }} />Simulated</div>
        <div className="flex items-center gap-2 text-xs"><span className="h-6 w-6 rounded border border-border" style={{ backgroundColor: entry.physical_color ?? "transparent" }} />{entry.physical_color ? "Physical" : "No reading"}</div>
        <div className="text-xs text-muted-foreground">{entry.alternatives.length ? <>Owned alternatives (advisory): {entry.alternatives.map((alt) => `${alt.label} · distance ${alt.distance}`).join("; ")}</> : "No owned color alternatives"}</div>
      </article>)}</div>
      <p className="text-sm text-muted-foreground">{response.result.advisory}</p>
      <p className="text-xs text-muted-foreground">Saved locally · input revision {response.result.inputs_revision.revision}</p>
    </section>}
    <section className="space-y-3 rounded-lg border border-border bg-card p-4">
      <h2 className="font-semibold">Saved calibration history</h2>
      <p className="text-sm text-muted-foreground">Previous comparisons, newest first (up to 50). Viewing a saved result does not apply its readings to the current palette.</p>
      <Button variant="secondary" disabled={historyBusy} onClick={() => void loadHistory()}>{historyBusy ? "Loading history…" : "Load saved comparisons"}</Button>
      {historyError && <p role="alert">{historyError}</p>}
      {history.map((run) => <details key={run.inputs_revision.revision} className="rounded border border-border p-3">
        <summary>{run.calibration_basis.family} · {run.calibration_basis.material} · {run.calibration_basis.layer_height_mm} mm · {run.entries.length} rows</summary>
        <p className="break-all text-xs">Basis {run.calibration_basis.calibration_basis_id} · {run.calibration_basis.source ?? "source not recorded"} · model {run.calibration_basis.model || "not recorded"} · nozzle {run.calibration_basis.nozzle_mm} mm · first layer {run.calibration_basis.first_layer_height_mm ?? "not recorded"}</p>
        <ul>{run.entries.map((entry, index) => <li key={index}>{entry.label}: target {entry.simulated_color}; physical {entry.physical_color ?? "not measured"}{entry.enabled === false ? "; disabled" : ""}</li>)}</ul>
      </details>)}
    </section>
  </main>;
}
