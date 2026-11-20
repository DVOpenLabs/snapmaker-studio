import { useCreativeDraft, useCreativeDraftField } from "./draft";
import { useCallback, useEffect, useRef, useState } from "react";
import { Palette } from "lucide-react";
import { Button } from "@/components/ui/button";
import WorkspaceFileChoices from "@/components/WorkspaceFileChoices";
import { PageHeader } from "@/components/ui/layout";
import { ProjectMaterialsCard } from "@/components/ProjectMaterialsCard";
import { ConnectedPrepareSetupSelector } from "@/components/PrepareSetupSelector";
import { useSession } from "@/store/session";
import { prepareBlockedBy, topologyToSend } from "@/lib/prepareSetup";
import type { ConversionResult } from "@/api";
import type { MaterialSelection } from "@/lib/projectMaterials";
import { fetchCreativeFormats, inspectCreative, normalizedProjectPath, prepareCreative, type CreativeFormatInfo, type CreativeInspectResponse, type CreativePrepareResponse } from "@/lib/creativeApi";
import { beginPrepare, linkPreparedCopy, useUnlinkedCopies } from "@/store/job";
import CreativeFormatChooser from "./CreativeFormatChooser";
import CreativePreparePanel from "./CreativePreparePanel";
import CreativeReportView from "./CreativeReportView";

export default function CreativeView({ initialFormats = [] }: { initialFormats?: CreativeFormatInfo[] }) {
  const [path, setPath] = useCreativeDraftField("path");
  const [format, setFormat] = useCreativeDraftField("format");
  const [outDir, setOutDir] = useCreativeDraftField("outDir");
  const [formats, setFormats] = useState<CreativeFormatInfo[]>(initialFormats);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<CreativeInspectResponse | null>(null);
  const [prepared, setPrepared] = useState<CreativePrepareResponse | null>(null);
  const [linkNote, setLinkNote] = useState<string | null>(null);
  const [materialActive, setMaterialActive] = useState(false);
  const unlinked = useUnlinkedCopies(s => s.items);
  const setupToken = useSession(s => s.prepareSetup.token);
  const activeSetupToken = useRef(setupToken);
  const generation = useRef(0);
  const inspectionGeneration = useRef(0);
  const pendingPrepare = useRef(false);
  const alive = useRef(true);
  const materials = useRef<MaterialSelection[]>([]);
  function invalidate(sourceChanged = false) {
    useCreativeDraft.getState().invalidate();
    generation.current++; setBusy(false); setError(null); setPrepared(null); setLinkNote(null);
    if (sourceChanged) { inspectionGeneration.current++; setReport(null); materials.current = []; setMaterialActive(false); }
  }
  useEffect(() => {
    alive.current = true;
    fetchCreativeFormats().then(r => { if (alive.current) setFormats(r.formats); }).catch(() => undefined);
    return () => { alive.current = false; inspectionGeneration.current++; };
  }, []);
  useEffect(() => { if (activeSetupToken.current !== setupToken) { activeSetupToken.current = setupToken; invalidate(); } }, [setupToken]);
  const changedMaterials = useCallback((choices: MaterialSelection[]) => {
    if (!alive.current) return; // The material card sends [] during unmount; it is not a user edit.
    if (JSON.stringify(materials.current) === JSON.stringify(choices)) return;
    useCreativeDraft.getState().invalidate();
    materials.current = choices;
    generation.current++; setPrepared(null); if (pendingPrepare.current) { pendingPrepare.current = false; setBusy(false); } setLinkNote(null);
  }, []);
  const changedActive = useCallback((active: boolean) => setMaterialActive(active), []);
  const run = async () => {
    const token = ++inspectionGeneration.current;
    pendingPrepare.current = false;
    setBusy(true); setError(null); setReport(null); setPrepared(null);
    try { const response = await inspectCreative(path, format); if (alive.current && token === inspectionGeneration.current) setReport(response); }
    catch (cause) { if (alive.current && token === inspectionGeneration.current) setError(cause instanceof Error ? cause.message : "The inspection failed."); }
    finally { if (alive.current && token === inspectionGeneration.current) setBusy(false); }
  };
  async function prepare(choices = materials.current, withoutSetup = false): Promise<ConversionResult | void> {
    let project: string;
    try { project = normalizedProjectPath(path); } catch (cause) { setError(cause instanceof Error ? cause.message : "Choose a project."); return; }
    if (withoutSetup) useSession.getState().clearPrepareSetup();
    const selection = useSession.getState().prepareSetup;
    const reason = prepareBlockedBy(selection, project);
    if (reason) { setError(reason); return; }
    const topology = topologyToSend(selection, project);
    const mine = ++generation.current;
    const draftRevision = useCreativeDraft.getState().revision;
    pendingPrepare.current = true;
    activeSetupToken.current = selection.token;
    const contextCurrent = () => mine === generation.current && useCreativeDraft.getState().revision === draftRevision && useSession.getState().prepareSetup.token === selection.token;
    const valid = () => alive.current && contextCurrent();
    setBusy(true); setError(null); setPrepared(null); setLinkNote(null);
    const started = beginPrepare();
    try {
      const result = await prepareCreative(project, format, outDir, { topology, materials: choices });
      let note: string | null = null;
      if (result.prepared && result.output.local_path) {
        if (!contextCurrent()) note = "This copy was written, but the inputs, materials or printer setup changed. It was not linked to the current job.";
        else if (!result.prepare.validated_ok) note = "This copy did not pass Studio's validation, so it was not linked to the job: Recovery and Passport will not track it.";
        else if (!linkPreparedCopy(project, result.output.local_path, result.prepare.mode || "creative", started)) note = "This copy was written, but a newer Prepare or project change took over. It was not linked to the current job.";
      }
      if (note && result.prepared) useUnlinkedCopies.getState().add(`${result.output.name}: ${note}`);
      if (!valid()) return;
      setPrepared(result); setLinkNote(note);
      if (result.prepared && result.prepare.validated_ok && !note && result.prepare.settings_summary && result.prepare.schema_version && ["preserve", "recommended", "starter"].includes(result.prepare.mode)) {
        return { schema_version: result.prepare.schema_version, prepare_mode: result.prepare.mode as ConversionResult["prepare_mode"], settings_summary: result.prepare.settings_summary, output_path: result.output.local_path, output_name: result.output.name, validated_ok: true };
      }
    } catch (cause) { if (valid()) setError(cause instanceof Error ? cause.message : "Prepare failed."); }
    finally { if (valid()) { pendingPrepare.current = false; setBusy(false); } }
  }
  let project: string | null = null;
  try { project = path.trim() ? normalizedProjectPath(path) : null; } catch { /* invalid path stays unselected */ }
  const selection = useSession(s => s.prepareSetup);
  const blocked = project ? prepareBlockedBy(selection, project) : null;
  const outcome = prepared ? prepared.prepared ? { settings_summary: prepared.prepare.settings_summary } : { blocked: true, settings_summary: { setup: prepared.setup } } : undefined;
  const field = "h-9 rounded-md border border-border bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50";
  return <div className="space-y-5 p-6">
    <PageHeader icon={Palette} title="Creative project inspection" subtitle="Inspect a creative 3MF and prepare a separate U1 copy. Studio does not slice or modify the original." />
    <p className="text-xs text-muted-foreground">Source, format and output-folder inputs stay in memory while Studio is open. After returning, inspect again and review materials before preparing. No read or preparation starts automatically.</p>
    <Button variant="ghost" onClick={() => { invalidate(true); useCreativeDraft.getState().reset(); }}>Clear creative inputs</Button>
    <WorkspaceFileChoices extensions={["3mf"]} disabled={busy} onChoose={value => { invalidate(true); setPath(value); }} />
    <div className="flex flex-wrap items-end gap-2">
      <input aria-label="Project file path" className={`${field} min-w-[18rem] flex-1`} placeholder="Path of a .3mf project file" value={path} onChange={e => { invalidate(true); setPath(e.target.value); }} onKeyDown={e => { if (e.key === "Enter" && !busy && path.trim()) void run(); }} />
      <Button disabled={busy || !path.trim()} onClick={() => void run()}>{busy ? "Reading..." : "Inspect project"}</Button>
    </div>
    <CreativeFormatChooser value={format} onChange={next => { invalidate(true); setFormat(next); }} formats={formats} needsChoice={report !== null && ["unknown", "ambiguous"].includes(report.origin.status)} />
    {error && <p role="alert" className="text-sm text-risk">{error}</p>}
    {report && <>
      <CreativeReportView report={report} />
      <ConnectedPrepareSetupSelector projectPath={project} disabled={busy} result={outcome} onPrepareWithoutSetup={!materialActive ? () => void prepare([], true) : undefined} />
      <section className="space-y-3 rounded-lg border border-border bg-card p-4" aria-label="Prepare a U1 copy">
        <h3 className="font-semibold">Prepare a U1 copy</h3>
        <input aria-label="Output folder (optional)" className={`${field} w-full`} placeholder="Output folder (optional; Studio's own folder when empty)" value={outDir} onChange={e => { invalidate(); setOutDir(e.target.value); }} />
        {blocked && <p role="alert">{blocked}</p>}
        {!materialActive && <Button disabled={busy || !!blocked} onClick={() => void prepare()}>{busy ? "Working…" : "Prepare a U1 copy"}</Button>}
        <p className="text-xs text-muted-foreground">The setup and explicit material choices shown here are sent together. A changed or invalid setup pauses Prepare; choosing no setup is a separate action.</p>
        {project && <ProjectMaterialsCard key={project + format} path={project} mode="preserve" onPrepare={choices => prepare(choices)} onSelectionsChange={changedMaterials} onActiveChange={changedActive} busy={busy || !!blocked} />}
      </section>
    </>}
    {unlinked.length > 0 && <div role="status" data-testid="creative-unlinked"><p>Written earlier but not linked to the job:</p><ul>{unlinked.map((text, i) => <li key={i}>{text}</li>)}</ul><button onClick={() => useUnlinkedCopies.getState().clear()}>Dismiss</button></div>}
    {linkNote && <p role="status" data-testid="creative-link-note">{linkNote}</p>}
    {prepared && <CreativePreparePanel result={prepared} />}
  </div>;
}
