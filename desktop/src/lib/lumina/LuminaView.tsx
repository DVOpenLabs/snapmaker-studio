import { useEffect, useRef, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { useNavigate } from "react-router-dom";
import { useSession } from "@/store/session";
import { useLuminaSession } from "./session";
import { Layers } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import {
  fetchLuminaFormats,
  openGeneratedModel, type LuminaForm, type LuminaFormat, type LuminaGenerateResponse,
} from "./luminaApi";
import { LuminaResultCard, LuminaStatusNote } from "./LuminaResultCard";

const field = "h-9 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50";

/** The inputs. The format has no default: it is chosen from the list the service layer returns. */
export function LuminaFields({ form, formats, formatsError, busy, onChange, onCheck, onGenerate }: {
  form: LuminaForm;
  formats: readonly LuminaFormat[];
  formatsError: string | null;
  busy: boolean;
  onChange: (next: LuminaForm) => void;
  onCheck: () => void;
  onGenerate: () => void;
}) {
  const latestForm = useRef(form); latestForm.current = form;
  const chosen = formats.find((f) => f.kind === form.format);
  const complete = form.serviceUrl.trim() !== "" && form.imagePath.trim() !== "" && form.lutName.trim() !== "" && chosen !== undefined;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <input className={`${field} w-72`} aria-label="Service address" placeholder="http://192.168.1.20:8000" value={form.serviceUrl} onChange={(e) => onChange({ ...form, serviceUrl: e.target.value })} />
        <input className={`${field} w-72`} aria-label="Image file path" placeholder="Path of an image on this computer" value={form.imagePath} onChange={(e) => onChange({ ...form, imagePath: e.target.value })} />
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => { void openDialog({ multiple: false, filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp", "bmp"] }] }).then(p => { if (typeof p === "string" && latestForm.current === form) onChange({ ...form, imagePath: p }); }).catch(() => undefined); }}>Choose image</Button>
        <input className={`${field} w-72`} aria-label="Output folder" placeholder="Output folder (optional)" value={form.outDir ?? ""} onChange={e => onChange({ ...form, outDir: e.target.value })} />
        <input className={`${field} w-48`} aria-label="LUT name" placeholder="LUT name" value={form.lutName} onChange={(e) => onChange({ ...form, lutName: e.target.value })} />
        <select className={field} aria-label="Output format" value={form.format} onChange={(e) => onChange({ ...form, format: e.target.value })} disabled={formats.length === 0}>
          <option value="">Choose a format</option>
          {formats.map((f) => <option key={f.kind} value={f.kind}>{f.kind}</option>)}
        </select>
        {form.format === "3mf" && <label className="text-sm">Model width (mm)<input className={`${field} w-24`} aria-label="Model width in millimetres" type="number" min="10" max="270" value={form.widthMm ?? "60"} onChange={e => onChange({ ...form, widthMm: e.target.value })} /></label>}
        <Button size="sm" variant="secondary" disabled={busy || form.serviceUrl.trim() === ""} onClick={onCheck}>Check service</Button>
        <Button size="sm" disabled={busy || !complete} onClick={onGenerate}>{busy ? "Working..." : "Generate"}</Button>
      </div>
      {form.format === "3mf" && <p className="text-xs text-muted-foreground">3MF requests create a preview session, then request the final model. Width is explicit; other generation settings use the service defaults. Review the result before preparing or slicing.</p>}
      {formatsError && <p className="text-sm text-risk" role="alert">{formatsError}</p>}
      {chosen
        ? <p className="text-xs text-muted-foreground">{chosen.kind}: {chosen.meaning} Tested against: {chosen.evidence}.</p>
        : <p className="text-xs text-muted-foreground">Studio does not guess the format: pick one from the list ({formats.map((f) => f.kind).join(", ") || "loading"}).</p>}
    </div>
  );
}

/** Sends one image to a local Lumina-compatible service you run and saves what it returns as a new file.
 *  Studio does not slice and never controls a printer from here. */
export default function LuminaView() {
  const { form, busy, error, status, result, earlierFiles, resultDirectory, change, run, clear } = useLuminaSession();
  const [formats, setFormats] = useState<LuminaFormat[]>([]);
  const [formatsError, setFormatsError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetchLuminaFormats().then(res => { if (alive) setFormats(res.formats); })
      .catch(e => { if (alive) setFormatsError(e instanceof Error ? e.message : "The format list could not be loaded."); });
    return () => { alive = false; };
  }, []);

  return (
    <div className="space-y-5 p-6">
      <PageHeader icon={Layers} title="Lumina service" subtitle="Send one image to a Lumina-compatible service running on your own network and save what it returns as a new file. Studio does not slice and never starts anything." />
      <p className="text-xs text-muted-foreground">Tested only against a synthetic stand-in service. No real Lumina installation has been exercised, and Studio has not verified the service you point it at.</p>
      <LuminaFields form={form} formats={formats} formatsError={formatsError} busy={busy} onChange={change}
        onCheck={() => void run("check", formats)} onGenerate={() => void run("generate", formats)} />
      <p className="text-xs text-muted-foreground">Generation may take time (up to a four-minute network budget, two minutes per request). Progress is unknown. Navigation keeps this request and its result while Studio stays open. Editing does not cancel generation at the service; a result for earlier inputs appears separately. Restarting Studio loses this in-memory session. Studio never opens a result automatically.</p>
      {earlierFiles.length > 0 && <section aria-label="Earlier generated files"><p>Earlier requests saved files after inputs changed. Open an earlier result explicitly below (last 10 results in this session):</p><ul>{earlierFiles.map(({ id, result: earlier, outDir }) => <li className="space-y-2 rounded border border-border p-3" key={id}><p>{earlier.file_name} · {earlier.location_label}</p>{earlier.kind === "3mf" && <LuminaOpenModel result={earlier} outDir={outDir} earlier />}</li>)}</ul></section>}
      {error && <p className="text-sm text-risk" role="alert">{error}</p>}
      {status && <LuminaStatusNote status={status} />}
      {result && <><LuminaResultCard result={result} />{result.kind === "3mf" ? <LuminaOpenModel key={result.file_name + result.sha256} result={result} outDir={resultDirectory} /> : <p className="text-sm">This is a preview, not a printable 3MF. Choose 3mf and generate again if the service supports it.</p>}</>}
      <Button size="sm" variant="ghost" disabled={busy} onClick={clear}>Clear Lumina session</Button>
    </div>
  );
}


function LuminaOpenModel({ result, outDir, earlier = false }: { result: LuminaGenerateResponse; outDir?: string; earlier?: boolean }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, [result]);
  return <div className="space-y-2"><Button disabled={busy} onClick={() => {
    setBusy(true); setError(null);
    void openGeneratedModel(result, outDir).then(value => {
      if (!alive.current) return;
      useSession.getState().setFile(value.output.local_path);
      navigate("/this-print");
    }).catch(e => { if (alive.current) setError(e instanceof Error ? e.message : "The generated file could not be opened."); })
      .finally(() => { if (alive.current) setBusy(false); });
  }}>{busy ? "Checking generated file…" : earlier ? "Open earlier generated model in Studio" : "Open generated model in Studio"}</Button>
    <p className="text-xs text-muted-foreground">Checks the saved file identity and 3MF container, then opens the normal inspection and Prepare workflow. It does not prepare, slice or print automatically.</p>
    {error && <p role="alert">{error}</p>}</div>;
}
