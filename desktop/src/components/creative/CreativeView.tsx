import { useEffect, useRef, useState } from "react";
import { Palette } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { CREATIVE_FORMATS, inspectCreative, type CreativeFormat, type CreativeInspectResponse } from "@/lib/creativeApi";
import CreativeReportView from "./CreativeReportView";

/** Inspect one local creative project file. The path is sent to the local Studio service only, which
 *  opens the file for reading, never writes it, and never slices or contacts a printer. */
export default function CreativeView() {
  const [path, setPath] = useState("");
  const [format, setFormat] = useState<CreativeFormat>("auto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<CreativeInspectResponse | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const run = async () => {
    // A failed inspection must not leave the previous file's report under the new path.
    setBusy(true); setError(null); setReport(null);
    try {
      const res = await inspectCreative(path, format);
      if (alive.current) setReport(res);
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : "The inspection failed.");
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const field = "h-9 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50";
  return (
    <div className="space-y-5 p-6">
      <PageHeader icon={Palette} title="Creative project inspection" subtitle="Open a 3MF project made by a colour or multi-nozzle tool and see what Studio understood, what it kept untouched and what it could not interpret. Studio only reads the file; it does not slice or change it." />
      <div className="flex flex-wrap items-end gap-2">
        <input className={`${field} min-w-[22rem] flex-1`} aria-label="Project file path" placeholder="Path of a .3mf project file" value={path}
               onChange={(e) => setPath(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !busy && path.trim() !== "") void run(); }} />
        <select className={field} aria-label="Project format" value={format} onChange={(e) => setFormat(e.target.value as CreativeFormat)}>
          {CREATIVE_FORMATS.map((f) => <option key={f} value={f}>{f === "auto" ? "Detect from settings" : f}</option>)}
        </select>
        <Button size="sm" disabled={busy || path.trim() === ""} onClick={() => void run()}>{busy ? "Reading..." : "Inspect project"}</Button>
      </div>
      <p className="text-xs text-muted-foreground">Studio does not guess the generator: when the settings do not identify it, the origin is reported as unknown.</p>
      {error && <p className="text-sm text-risk" role="alert">{error}</p>}
      {report && <CreativeReportView report={report} />}
    </div>
  );
}
