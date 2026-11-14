import { useEffect, useRef, useState } from "react";
import { Palette } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import {
  fetchCreativeFormats, inspectCreative, prepareCreative,
  type CreativeFormat, type CreativeFormatInfo, type CreativeInspectResponse, type CreativePrepareResponse,
} from "@/lib/creativeApi";
import CreativeFormatChooser from "./CreativeFormatChooser";
import CreativePreparePanel from "./CreativePreparePanel";
import CreativeReportView from "./CreativeReportView";

/** Inspect one local creative project file, then optionally write a prepared copy. The path is sent to the local
 *  Studio service only. Inspecting never writes anything; Prepare writes one new file and never the original. */
export default function CreativeView({ initialFormats = [] }: { initialFormats?: CreativeFormatInfo[] }) {
  const [path, setPath] = useState("");
  const [format, setFormat] = useState<CreativeFormat>("auto");
  const [outDir, setOutDir] = useState("");
  const [formats, setFormats] = useState<CreativeFormatInfo[]>(initialFormats);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<CreativeInspectResponse | null>(null);
  const [prepared, setPrepared] = useState<CreativePrepareResponse | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    fetchCreativeFormats().then((r) => { if (alive.current) setFormats(r.formats); }).catch(() => undefined);
    return () => { alive.current = false; };
  }, []);

  const run = async () => {
    // A failed inspection must not leave the previous file's report under the new path.
    setBusy(true); setError(null); setReport(null); setPrepared(null);
    try {
      const res = await inspectCreative(path, format);
      if (alive.current) setReport(res);
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : "The inspection failed.");
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const prepare = async () => {
    setBusy(true); setError(null); setPrepared(null);
    try {
      const res = await prepareCreative(path, format, outDir);
      if (alive.current) setPrepared(res);
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : "Prepare failed.");
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const field = "h-9 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50";
  const undecided = report !== null && (report.origin.status === "unknown" || report.origin.status === "ambiguous");
  return (
    <div className="space-y-5 p-6">
      <PageHeader icon={Palette} title="Creative project inspection" subtitle="Open a 3MF project made by a colour or multi-nozzle tool and see what Studio understood, what it kept untouched and what it could not interpret. Inspecting only reads the file. Studio does not slice." />
      <div className="flex flex-wrap items-end gap-2">
        <input className={`${field} min-w-[22rem] flex-1`} aria-label="Project file path" placeholder="Path of a .3mf project file" value={path}
               onChange={(e) => setPath(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !busy && path.trim() !== "") void run(); }} />
        <Button size="sm" disabled={busy || path.trim() === ""} onClick={() => void run()}>{busy ? "Reading..." : "Inspect project"}</Button>
      </div>
      <CreativeFormatChooser value={format} onChange={setFormat} formats={formats} needsChoice={undecided} />
      {error && <p className="text-sm text-risk" role="alert">{error}</p>}
      {report && <CreativeReportView report={report} />}
      {report && (
        <section className="space-y-2 rounded-lg border border-border bg-card p-4" aria-label="Prepare a U1 copy">
          <h3 className="text-sm font-semibold tracking-tight">Prepare a U1 copy</h3>
          <p className="text-xs text-muted-foreground">Writes a new file with Studio's Prepare and never touches the original. The copy is then compared with the original part by part. Studio refuses a file whose tool it cannot identify.</p>
          <div className="flex flex-wrap items-end gap-2">
            <input className={`${field} min-w-[18rem] flex-1`} aria-label="Output folder (optional)" placeholder="Output folder (optional; Studio's own folder when empty)" value={outDir}
                   onChange={(e) => setOutDir(e.target.value)} />
            <Button size="sm" disabled={busy || path.trim() === ""} onClick={() => void prepare()}>{busy ? "Working..." : "Prepare a U1 copy"}</Button>
          </div>
        </section>
      )}
      {prepared && <CreativePreparePanel result={prepared} />}
    </div>
  );
}
