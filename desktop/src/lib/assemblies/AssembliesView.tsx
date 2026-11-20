import { useAssemblyDraftField } from "./draft";
import { useEffect, useRef, useState } from "react";
import { open as pickFile } from "@tauri-apps/plugin-dialog";
import { Boxes } from "lucide-react";
import { Button } from "@/components/ui/button";
import WorkspaceFileChoices from "@/components/WorkspaceFileChoices";
import { PageHeader } from "@/components/ui/layout";
import { library, projectMaterialsInventory, type LibraryProject } from "@/api";
import type { MaterialCandidate } from "@/lib/projectMaterials";
import { evaluateAssembly, getAssembly, importAssemblyFile, listAssemblies, normalizeAssemblyInput, parseJsonBox, saveAssembly } from "./api";
import AssemblyReportView from "./AssemblyReportView";
import { SAMPLE_ASSEMBLY, sampleSupply } from "./sample";
import { appendTiles, decodeDocument, decodeSupply, slotRows, updateSlot, type AssemblyDocument } from "./editor";
import type { AssemblyReport, SavedAssembly } from "./types";

const field = "rounded-md border border-border bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50";
const empty = (): AssemblyDocument => ({ name: "New assembly", tiles: [], bindings: {} });

export default function AssembliesView() {
  const [document, setDocument] = useAssemblyDraftField("document");
  const [supply, setSupply] = useAssemblyDraftField("supply");
  const [report, setReport] = useState<AssemblyReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<SavedAssembly[]>([]);
  const [savedBusy, setSavedBusy] = useState(false);
  const [savedError, setSavedError] = useState<string | null>(null);
  const savedRequest = useRef(0);
  const [current, setCurrent] = useAssemblyDraftField("current");
  const [projects, setProjects] = useState<LibraryProject[]>([]);
  const [filePath, setFilePath] = useAssemblyDraftField("filePath");
  const [provider, setProvider] = useState("spoolman");
  const [providerUrl, setProviderUrl] = useState("");
  const [providerKey, setProviderKey] = useState("");
  const [instance, setInstance] = useState("");
  const [inventory, setInventory] = useState<MaterialCandidate[]>([]);
  const [sampleMode, setSampleMode] = useAssemblyDraftField("sampleMode");
  const [advanced, setAdvanced] = useState(false);
  const [assemblyText, setAssemblyText] = useState("");
  const [supplyText, setSupplyText] = useState("");
  const revision = useRef(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    void refreshSaved();
    return () => { alive.current = false; revision.current++; savedRequest.current++; };
  }, []);
  async function refreshSaved() {
    const token = ++savedRequest.current;
    const valid = () => alive.current && savedRequest.current === token;
    setSavedBusy(true); setSavedError(null);
    try { const rows = await listAssemblies(); if (valid()) setSaved(rows.assemblies); }
    catch { if (valid()) setSavedError("The saved assembly list could not be refreshed. Previously listed names may be out of date. Choose Refresh saved assemblies to retry; your editor is unchanged."); }
    finally { if (valid()) setSavedBusy(false); }
  }
  function invalidate() { revision.current++; setBusy(false); setReport(null); setError(null); setNotice(null); }
  function change(next: AssemblyDocument) { invalidate(); setDocument(next); }
  async function run(action: (valid: () => boolean) => Promise<void>) {
    const token = ++revision.current;
    const valid = () => alive.current && revision.current === token;
    setBusy(true); setError(null); setNotice(null); setReport(null);
    try { await action(valid); }
    catch (cause) { if (valid()) setError(cause instanceof Error ? cause.message : "That did not work."); }
    finally { if (valid()) setBusy(false); }
  }
  function editSlot(index: number, slot: string, values: { role?: string; grams?: string }) {
    try { change(updateSlot(document, index, slot, values)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Invalid slot edit."); }
  }
  function editScale(index: number, value: string) {
    change({ ...document, tiles: document.tiles.map((t, i) => i === index ? {
      ...t, scale: value === "" ? null : Number(value),
      usage: Object.fromEntries(Object.keys(t.usage).map(slot => [slot, null])),
      attribution: { ...t.attribution, usage_origin: "scale changed; reimport sliced usage" },
    } : t) });
    setSupply([]);
  }
  function importPath(path: string, project?: LibraryProject) {
    if (sampleMode) { setError("Start a new assembly before importing real files; sample figures must stay separate."); return; }
    void run(async valid => {
      const imported = await importAssemblyFile(path);
      if (!valid()) return;
      const tiles = imported.assembly.tiles.map(tile => project ? { ...tile, library: { project_id: project.id, sha256: imported.sha256 } } : tile);
      setDocument(appendTiles(document, tiles)); setSupply([]);
      setFilePath(path); setInventory([]); setNotice(imported.notes.join(" ") || "Slicer-reported usage imported. Check roles and choose spools.");
    });
  }
  const roles = [...new Set(document.tiles.flatMap(t => Object.keys(t.roles)))];
  return <main className="space-y-5 p-6">
    <PageHeader icon={Boxes} title="Assemblies" subtitle="Plan tiles and plates against shared spools. Import existing files; Studio does not slice or start anything." />
    <p className="text-xs text-muted-foreground">Unsaved tiles, roles and spool readings stay in memory when you use another tool. Readings keep their original timestamps and can expire. Check spools again after returning. Nothing is kept after restart unless you save the assembly; provider keys and inventory lists are not retained.</p>
    {sampleMode && <p role="status" data-testid="assembly-sample-disclosure" className="text-sm text-muted-foreground">Synthetic sample: all figures are invented. Start a new assembly before adding real files.</p>}
    <WorkspaceFileChoices extensions={["3mf", "gcode", "g", "gco", "stl", "obj"]} disabled={busy || sampleMode} onChoose={value => { invalidate(); setFilePath(value); setInventory([]); }} />
    <section className="space-y-3 rounded-lg border border-border bg-card p-4">
      <label className="block text-sm">Assembly name <input aria-label="Assembly name" className={field} value={document.name} maxLength={200} onChange={e => change({ ...document, name: e.target.value })} /></label>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => { invalidate(); setDocument(empty()); setSampleMode(false); setSupply([]); setInventory([]); setCurrent(null); setFilePath(""); }}>New assembly</Button>
        <Button variant="secondary" disabled={busy} onClick={() => void run(async valid => { const path = await pickFile({ multiple: false, filters: [{ name: "Projects and sliced outputs", extensions: ["3mf", "gcode", "g", "gco", "stl", "obj"] }] }); if (valid() && typeof path === "string") importPath(path); })}>Choose project or slice</Button>
        <input aria-label="Import file path" disabled={sampleMode} className={`${field} flex-1`} placeholder="Or enter a local file path" value={filePath} onChange={e => { invalidate(); setFilePath(e.target.value); setInventory([]); }} />
        <Button disabled={busy || sampleMode || !filePath.trim()} onClick={() => importPath(filePath)}>Import file</Button>
        <Button variant="secondary" disabled={busy} onClick={() => void run(async valid => { const rows = await library(); if (valid()) setProjects(rows); })}>Browse library</Button>
        {projects.length > 0 && <select aria-label="Library project" className={field} value="" onChange={e => { const project = projects.find(p => p.id === Number(e.target.value)); if (project) importPath(project.source_path, project); }}><option value="">Choose library project…</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}
      </div>
      <p className="text-xs text-muted-foreground">Each sliced 3MF plate becomes a tile. Unsliced models keep material usage unknown. Original files are not changed. Imported spool readings are cleared when files are added or an assembly is opened.</p>
      <Button variant="secondary" onClick={() => { invalidate(); setCurrent(null); setDocument(decodeDocument({ ...SAMPLE_ASSEMBLY, attribution: [...SAMPLE_ASSEMBLY.attribution, { data_origin: "synthetic-sample" }] })); setSampleMode(true); setFilePath(""); setInventory([]); setSupply(sampleSupply(Math.floor(Date.now() / 1000))); setNotice(null); }}>Load sample assembly</Button>
    </section>
    {document.tiles.map((tile, index) => <section key={tile.tile_id} className="space-y-3 rounded-lg border border-border bg-card p-4" aria-label={`Tile ${index + 1}`}>
      <div className="flex flex-wrap gap-2">
        <label className="text-sm">Tile name <input aria-label={`Tile ${index + 1} name`} className={field} value={tile.name} maxLength={200} onChange={e => change({ ...document, tiles: document.tiles.map((t, i) => i === index ? { ...t, name: e.target.value } : t) })} /></label>
        <label className="text-sm">Plate <input aria-label={`Tile ${index + 1} plate`} className={field} value={tile.plate ?? ""} maxLength={200} onChange={e => change({ ...document, tiles: document.tiles.map((t, i) => i === index ? { ...t, plate: e.target.value || null } : t) })} /></label>
        <label className="text-sm">Scale (%) <input aria-label={`Tile ${index + 1} scale`} className={field} type="number" min="0.01" max="1000" value={tile.scale ?? ""} onChange={e => editScale(index, e.target.value)} /></label>
        <Button variant="secondary" onClick={() => { change({ ...document, tiles: document.tiles.filter((_, i) => i !== index) }); setSupply([]); }}>Remove tile</Button>
      </div>
      <p className="text-xs text-muted-foreground">Usage origin: {tile.attribution?.usage_origin ?? tile.usage_source ?? "declared"}. Editing grams records your declared estimate; it does not reslice the file. Changing scale clears usage and spool readings because a previous slice no longer establishes the required grams.</p>
      {slotRows(tile).map(row => <div key={row.slot} className="flex flex-wrap items-end gap-2">
        <span className="text-sm">Filament {Number(row.slot.split(":")[1]) + 1}</span>
        <label className="text-sm">Role <input aria-label={`Tile ${index + 1} ${row.slot} role`} className={field} maxLength={40} value={row.role} onChange={e => editSlot(index, row.slot, { role: e.target.value })} /></label>
        <label className="text-sm">Required grams <input aria-label={`Tile ${index + 1} ${row.slot} grams`} className={field} type="number" min="0" max="1000000" step="0.1" placeholder="Unknown" value={row.grams ?? ""} onChange={e => editSlot(index, row.slot, { grams: e.target.value })} /></label>
      </div>)}
    </section>)}
    <section className="space-y-3 rounded-lg border border-border bg-card p-4">
      <h2 className="font-semibold">Shared spools and observations</h2>
      <p className="text-sm text-muted-foreground">The same provider instance and spool ID means one shared spool across tiles. Different providers are never silently combined.</p>
      <div className="flex flex-wrap gap-2">
        <select aria-label="Inventory provider" className={field} value={provider} onChange={e => { invalidate(); setProvider(e.target.value); setInventory([]); }}><option value="spoolman">Spoolman</option><option value="bambuddy">Bambuddy</option></select>
        <input aria-label="Provider address" placeholder="Provider address on your network" className={field} value={providerUrl} onChange={e => { invalidate(); setProviderUrl(e.target.value); setInventory([]); }} />
        <input aria-label="Provider key" placeholder="API key (optional)" type="password" autoComplete="off" className={field} value={providerKey} onChange={e => { invalidate(); setProviderKey(e.target.value); setInventory([]); }} />
        <input aria-label="Provider instance ID" placeholder="Unique provider instance ID" className={field} value={instance} onChange={e => { invalidate(); setInstance(e.target.value); setInventory([]); }} />
        <Button variant="secondary" disabled={busy || sampleMode || !filePath.trim() || !providerUrl.trim() || !instance.trim()} onClick={() => void run(async valid => { const result = await projectMaterialsInventory(filePath, 0, { provider, provider_url: providerUrl, ...(providerKey ? { provider_key: providerKey } : {}) }); if (valid()) {
          setInventory([]);
          if (result.supported === false) throw new Error(result.reason || "Inventory is not supported for this file. The assembly is unchanged.");
          if (result.provider && !result.provider.available) throw new Error("The inventory provider is unavailable. Check its address and credentials; no inventory was imported.");
          if (!Array.isArray(result.entries)) throw new Error("The inventory reply did not contain a readable spool list.");
          setInventory(result.entries); setNotice(result.reason || "Inventory read. Provider observation time is unavailable here; imported weights remain historical and cannot prove enough material.");
        } })}>Read inventory</Button>
      </div>
      {roles.map(role => {
        const binding = document.bindings[role];
        const reading = supply.find(s => binding && s.spool.provider_instance_id === binding.provider_instance_id && s.spool.provider_spool_id === binding.provider_spool_id);
        return <div key={role} className="flex flex-wrap items-end gap-2 rounded border border-border p-3">
          <span className="font-medium">{role}</span>
          <label className="text-sm">Provider instance <input aria-label={`${role} provider instance`} className={field} value={binding?.provider_instance_id ?? ""} onChange={e => change({ ...document, bindings: { ...document.bindings, [role]: { provider_instance_id: e.target.value, provider_spool_id: binding?.provider_spool_id ?? "" } } })} /></label>
          <label className="text-sm">Spool ID <input aria-label={`${role} spool ID`} className={field} value={binding?.provider_spool_id ?? ""} onChange={e => change({ ...document, bindings: { ...document.bindings, [role]: { provider_instance_id: binding?.provider_instance_id ?? "", provider_spool_id: e.target.value } } })} /></label>
          {inventory.length > 0 && <select aria-label={`${role} inventory spool`} className={field} value="" onChange={e => { if (e.target.value === "") return; const item = inventory[Number(e.target.value)]; if (!item) return; invalidate(); const spool = { provider_instance_id: instance, provider_spool_id: String(item.spool_id) }; setDocument({ ...document, bindings: { ...document.bindings, [role]: spool } }); setSupply(previous => [...previous.filter(s => s.spool.provider_instance_id !== spool.provider_instance_id || s.spool.provider_spool_id !== spool.provider_spool_id), { spool, remaining_g: item.remaining_g, observed_at: null, ttl_s: null, historical: true }]); }}><option value="">Choose inventory spool…</option>{inventory.map((item, i) => <option key={String(item.spool_id)} value={i}>{item.label}: {item.remaining_g ?? "unknown"} g ({item.remaining_quality ?? "unknown quality"})</option>)}</select>}
          <label className="text-sm">Remaining grams <input aria-label={`${role} remaining grams`} className={field} type="number" min="0" max="1000000" placeholder="Unknown" value={reading?.remaining_g ?? ""} onChange={e => { invalidate(); if (!binding) return; const grams = e.target.value === "" ? null : Number(e.target.value); setSupply([...supply.filter(s => s !== reading), { spool: binding, remaining_g: grams, observed_at: null, ttl_s: null }]); }} /></label>
          <Button variant="secondary" disabled={!binding?.provider_instance_id || !binding.provider_spool_id || reading?.remaining_g == null || reading.historical === true || reading.observed_at != null} onClick={() => { invalidate(); if (!reading) return; setSupply(supply.map(s => s === reading ? { ...s, observed_at: Date.now() / 1000, ttl_s: 300, historical: false } : s)); }}>Record my current measurement (5 min)</Button>
          <Button variant="ghost" disabled={!binding} onClick={() => { const bindings = { ...document.bindings }; delete bindings[role]; change({ ...document, bindings }); }}>Clear spool binding</Button>
          <span className="text-xs text-muted-foreground">Type a current measurement before recording. {reading?.historical ? "Historical weight; observation time unknown" : reading?.observed_at ? "Dated reading; evaluator checks its lifetime" : "No dated measurement"}</span>
        </div>;
      })}
    </section>
    <div className="flex flex-wrap gap-2">
      <Button disabled={busy || !document.tiles.length} onClick={() => void run(async valid => { const result = await evaluateAssembly(document, supply); if (valid()) setReport(result.report); })}>Check spools</Button>
      <Button variant="secondary" disabled={busy || !document.tiles.length} onClick={() => void run(async valid => { const result = await saveAssembly(document, current?.id, current?.revision); if (!valid()) return; setCurrent({ id: result.id, revision: result.revision }); setNotice("Saved. Spool observations are not saved with the assembly."); await refreshSaved(); })}>Save assembly</Button>
      <Button variant="secondary" disabled={savedBusy} onClick={() => void refreshSaved()}>{savedBusy ? "Refreshing saved assemblies…" : "Refresh saved assemblies"}</Button>
      <select aria-label="Saved assemblies" className={field} value="" onChange={e => { if (e.target.value) void run(async valid => { const result = await getAssembly(Number(e.target.value)); if (!valid()) return; const opened = decodeDocument(result.assembly); setDocument(opened); setSampleMode(Array.isArray(opened.attribution) && opened.attribution.some((a: Record<string, unknown>) => a.data_origin === "synthetic-sample")); setSupply([]); setInventory([]); setFilePath(""); setCurrent({ id: result.id, revision: result.revision }); setAdvanced(false); }); }}><option value="">Open a saved assembly…</option>{saved.map(a => <option key={a.id} value={a.id}>{a.name} ({a.tiles} tiles)</option>)}</select>
    </div>
    {savedError && <p role="alert" className="text-sm text-risk">{savedError}</p>}
    <details open={advanced} onToggle={e => setAdvanced(e.currentTarget.open)} className="rounded border border-border p-4"><summary>Advanced JSON import</summary>
      <p className="text-xs text-muted-foreground">Applying JSON replaces the current editor. Nothing is saved until you choose Save assembly.</p>
      <textarea aria-label="Assembly JSON" className={`${field} min-h-32 w-full font-mono`} value={assemblyText} onChange={e => { invalidate(); setAssemblyText(e.target.value); }} />
      <textarea aria-label="Spool readings JSON" className={`${field} min-h-24 w-full font-mono`} value={supplyText} onChange={e => { invalidate(); setSupplyText(e.target.value); }} />
      <Button variant="secondary" disabled={busy} onClick={() => void run(async valid => {
        const raw = parseJsonBox<unknown>(assemblyText, "The assembly");
        const readings = decodeSupply(supplyText.trim() ? parseJsonBox<unknown>(supplyText, "The spool readings") : []);
        const normalized = await normalizeAssemblyInput(raw, readings);
        if (!valid()) return;
        const doc = decodeDocument(normalized.assembly);
        setDocument(doc); setSampleMode(Array.isArray(doc.attribution) && doc.attribution.some((a: Record<string, unknown>) => a.data_origin === "synthetic-sample"));
        setSupply(readings); setCurrent(null); setFilePath(""); setInventory([]);
      })}>Apply JSON</Button>
    </details>
    {notice && <p role="status" className="text-sm text-muted-foreground">{notice}</p>}
    {error && <p role="alert" className="text-sm text-risk">{error}</p>}
    {report && <AssemblyReportView report={report} />}
  </main>;
}
