import { useEffect, useRef, useState } from "react";
import { Layers } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import {
  buildGenerateBody, checkLuminaService, fetchLuminaFormats, generateWithLumina,
  type LuminaForm, type LuminaFormat, type LuminaGenerateResponse, type LuminaStatusResponse,
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
  const chosen = formats.find((f) => f.kind === form.format);
  const complete = form.serviceUrl.trim() !== "" && form.imagePath.trim() !== "" && form.lutName.trim() !== "" && chosen !== undefined;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <input className={`${field} w-72`} aria-label="Service address" placeholder="http://192.168.1.20:8000" value={form.serviceUrl} onChange={(e) => onChange({ ...form, serviceUrl: e.target.value })} />
        <input className={`${field} w-72`} aria-label="Image file path" placeholder="Path of an image on this computer" value={form.imagePath} onChange={(e) => onChange({ ...form, imagePath: e.target.value })} />
        <input className={`${field} w-48`} aria-label="LUT name" placeholder="LUT name" value={form.lutName} onChange={(e) => onChange({ ...form, lutName: e.target.value })} />
        <select className={field} aria-label="Output format" value={form.format} onChange={(e) => onChange({ ...form, format: e.target.value })} disabled={formats.length === 0}>
          <option value="">Choose a format</option>
          {formats.map((f) => <option key={f.kind} value={f.kind}>{f.kind}</option>)}
        </select>
        <Button size="sm" variant="secondary" disabled={busy || form.serviceUrl.trim() === ""} onClick={onCheck}>Check service</Button>
        <Button size="sm" disabled={busy || !complete} onClick={onGenerate}>{busy ? "Working..." : "Generate"}</Button>
      </div>
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
  const [form, setForm] = useState<LuminaForm>({ serviceUrl: "", imagePath: "", lutName: "", format: "" });
  const [formats, setFormats] = useState<LuminaFormat[]>([]);
  const [formatsError, setFormatsError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<LuminaStatusResponse | null>(null);
  const [result, setResult] = useState<LuminaGenerateResponse | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    fetchLuminaFormats()
      .then((res) => { if (alive.current) setFormats(res.formats); })
      .catch((e) => { if (alive.current) setFormatsError(e instanceof Error ? e.message : "The format list could not be loaded."); });
    return () => { alive.current = false; };
  }, []);

  const run = async (task: () => Promise<void>) => {
    setBusy(true); setError(null); setStatus(null); setResult(null);
    try { await task(); }
    catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "The request failed."); }
    finally { if (alive.current) setBusy(false); }
  };

  const check = () => run(async () => {
    const res = await checkLuminaService(form.serviceUrl);
    if (alive.current) setStatus(res);
  });
  const generate = () => run(async () => {
    const res = await generateWithLumina(buildGenerateBody(form, formats));
    if (alive.current) setResult(res);
  });

  return (
    <div className="space-y-5 p-6">
      <PageHeader icon={Layers} title="Lumina service" subtitle="Send one image to a Lumina-compatible service running on your own network and save what it returns as a new file. Studio does not slice and never starts anything." />
      <p className="text-xs text-muted-foreground">Tested only against a synthetic stand-in service. No real Lumina installation has been exercised, and Studio has not verified the service you point it at.</p>
      <LuminaFields form={form} formats={formats} formatsError={formatsError} busy={busy} onChange={setForm}
        onCheck={() => void check()} onGenerate={() => void generate()} />
      {error && <p className="text-sm text-risk" role="alert">{error}</p>}
      {status && <LuminaStatusNote status={status} />}
      {result && <LuminaResultCard result={result} />}
    </div>
  );
}
