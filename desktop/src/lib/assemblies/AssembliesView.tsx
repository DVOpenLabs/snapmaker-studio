import { useEffect, useRef, useState } from "react";
import { Boxes } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { evaluateAssembly, getAssembly, listAssemblies, parseJsonBox, saveAssembly } from "./api";
import AssemblyReportView from "./AssemblyReportView";
import { SAMPLE_ASSEMBLY, sampleSupply } from "./sample";
import type { AssemblyReport, SavedAssembly } from "./types";

/** Plan a multi-tile project against shared spools. The assembly and the spool readings are typed here;
 *  nothing is sent anywhere except the local Studio service, and the verdict is advisory. */
export default function AssembliesView() {
  const [assemblyText, setAssemblyText] = useState("");
  const [supplyText, setSupplyText] = useState("");
  const [report, setReport] = useState<AssemblyReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<SavedAssembly[]>([]);
  const [current, setCurrent] = useState<{ id: number; revision: number } | null>(null);
  const alive = useRef(true);

  const refresh = () => listAssemblies().then((r) => { if (alive.current) setSaved(r.assemblies); }).catch(() => undefined);
  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => { alive.current = false; };
  }, []);

  const loadSample = () => {
    setAssemblyText(JSON.stringify(SAMPLE_ASSEMBLY, null, 2));
    setSupplyText(JSON.stringify(sampleSupply(Math.floor(Date.now() / 1000)), null, 2));
    setReport(null); setError(null); setNotice(null); setCurrent(null);
  };

  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError(null); setNotice(null);
    try {
      await action();
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : "That did not work.");
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const evaluate = () => run(async () => {
    const assembly = parseJsonBox<unknown>(assemblyText, "The assembly");
    const supply = supplyText.trim() === "" ? [] : parseJsonBox<unknown>(supplyText, "The spool readings");
    setReport(null);
    const res = await evaluateAssembly(assembly, supply);
    if (alive.current) setReport(res.report);
  });

  const save = () => run(async () => {
    const assembly = parseJsonBox<unknown>(assemblyText, "The assembly");
    const res = current ? await saveAssembly(assembly, current.id, current.revision) : await saveAssembly(assembly);
    if (!alive.current) return;
    setCurrent({ id: res.id, revision: res.revision });
    setNotice("Saved. Spool readings are not saved; add them again when you check.");
    await refresh();
  });

  const open = (id: number) => run(async () => {
    const res = await getAssembly(id);
    if (!alive.current) return;
    setAssemblyText(JSON.stringify(res.assembly, null, 2));
    setCurrent({ id: res.id, revision: res.revision });
    setReport(null);
  });

  const box = "min-h-[16rem] w-full rounded-md border border-border bg-card p-3 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-primary/50";
  return (
    <div className="space-y-5 p-6">
      <PageHeader icon={Boxes} title="Assemblies" subtitle="Add up what a multi-tile project needs from spools shared across its plates. An advisory check on your own figures; Studio does not slice or start anything." />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" onClick={loadSample}>Load sample assembly</Button>
        <Button size="sm" disabled={busy || assemblyText.trim() === ""} onClick={() => void evaluate()}>{busy ? "Working..." : "Check spools"}</Button>
        <Button size="sm" variant="secondary" disabled={busy || assemblyText.trim() === ""} onClick={() => void save()}>Save assembly</Button>
        {saved.length > 0 && (
          <select className="h-9 rounded-md border border-border bg-card px-2 text-sm" aria-label="Saved assemblies" value=""
                  onChange={(e) => { if (e.target.value) void open(Number(e.target.value)); }}>
            <option value="">Open a saved assembly...</option>
            {saved.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.tiles} tiles)</option>)}
          </select>
        )}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <label className="space-y-1 text-sm font-medium">Assembly (JSON)
          <textarea className={box} aria-label="Assembly JSON" spellCheck={false} value={assemblyText} onChange={(e) => setAssemblyText(e.target.value)}
                    placeholder="Tiles, the roles they share, which spool serves each role, and the grams each tile states." />
        </label>
        <label className="space-y-1 text-sm font-medium">Spool readings (JSON)
          <textarea className={box} aria-label="Spool readings JSON" spellCheck={false} value={supplyText} onChange={(e) => setSupplyText(e.target.value)}
                    placeholder="Remaining grams per spool, when it was read and how long that reading holds." />
        </label>
      </div>
      <p className="text-xs text-muted-foreground">Grams you leave out stay unknown; they are never counted as zero. A reading with no date or an old one is reported as such, not as a shortage.</p>
      {notice && <p className="text-sm text-muted-foreground" role="status">{notice}</p>}
      {error && <p className="text-sm text-risk" role="alert">{error}</p>}
      {report && <AssemblyReportView report={report} />}
    </div>
  );
}
