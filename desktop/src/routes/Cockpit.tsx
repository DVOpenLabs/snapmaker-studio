import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, FileCheck2, FolderOpen, Loader2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FlatCards } from "@/components/ui/card";
import { ColorPlanCard } from "@/components/ColorPlanCard";
import { JobWorkspaceCard } from "@/components/JobWorkspaceCard";
import { usePlacement } from "@/components/PlacementCard";
import { PreflightCard } from "@/components/PreflightCard";
import { PrepareModeChooser } from "@/components/PrepareModeChooser";
import { PrepareSettingsSummary } from "@/components/PrepareSettingsSummary";
import { ProjectMaterialsCard } from "@/components/ProjectMaterialsCard";
import { CopyResult } from "@/components/job/CopyResult";
import { JobBar } from "@/components/job/JobBar";
import { PaneTabs, type PaneTab } from "@/components/job/PaneTabs";
import { ModelPane } from "@/components/job/ModelPane";
import { SliceCompare } from "@/components/job/SliceCompare";
import { useOpenFile } from "@/hooks/useOpenFile";
import { useEligibility } from "@/hooks/useEligibility";
import { usePrepare } from "@/hooks/usePrepare";
import { usePreviewFetcher } from "@/hooks/usePreviewFetcher";
import { GATE_COPY } from "@/lib/compatibility";
import { deriveJourney, type StageId } from "@/lib/journey";
import type { PrepareMode } from "@/api";
import type { MaterialSelection } from "@/lib/projectMaterials";
import { useSession, type FileRef } from "@/store/session";
import { useSliced } from "@/store/sliced";

type View = "model" | "copy" | "slice";
type TabId = "target" | "materials" | "settings";

/**
 * One job, from the file you opened to the slice that came back.
 *
 * The model and its plate are in the middle. Beside them, three tabs hold what you decide: the
 * target printer, the materials, and the copy's settings. One button in the bar does the next
 * thing; the result of each stage replaces the middle in place rather than stacking below it.
 *
 * The screen is keyed to the open project, so opening another project, or the same path again,
 * starts it over: choices, previews and results made for the earlier one never carry across.
 */
export default function Cockpit() {
  const file = useSession((s) => s.file);
  const identity = useIdentity(file);
  if (!file) return <NoJob />;
  return <JobScreen key={identity} file={file} />;
}

/** A number that changes whenever a different project is opened, including the same path opened again. */
function useIdentity(file: FileRef | null): number {
  const last = useRef<{ file: FileRef | null; n: number }>({ file, n: 0 });
  if (last.current.file !== file) last.current = { file, n: last.current.n + 1 };
  return last.current.n;
}

function NoJob() {
  const open = useOpenFile();
  return (
    <div className="mx-auto flex max-w-xl flex-col gap-5 pt-6">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <FileCheck2 className="h-5 w-5 text-primary" aria-hidden="true" /> This job
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Open a model. Studio reads it on this computer, helps you choose materials, makes a U1 copy and, when you bring the
          slice back, compares it.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => void open()}><FolderOpen className="h-4 w-4" aria-hidden="true" /> Open project</Button>
        <span className="text-xs text-muted-foreground">or drop an <code>.stl</code> / <code>.3mf</code> on this window, or pick one from <Link className="underline" to="/projects">My designs</Link>.</span>
      </div>
      <JobWorkspaceCard />
    </div>
  );
}

const VIEW_OF: Record<StageId, View> = { open: "model", materials: "model", copy: "model", orca: "copy", compare: "slice" };

function JobScreen({ file }: { file: FileRef }) {
  const doctor = useSession((s) => s.doctor);
  const convert = useSession((s) => s.convert);
  const runDoctor = useSession((s) => s.runDoctor);
  const sliced = useSliced((s) => s.path);

  // Studio will not prepare this project: the project check says so, or the engine's eligibility record does (unreadable, or readable but refused).
  const eligibility = useEligibility(file.path, file.ext);
  const gate = eligibility.status === "ready" ? eligibility.gate : "open";
  const closed = !!doctor.data?.prepare_blocked || gate !== "open";
  // The file cannot be read at all (the engine's own verdict). Nothing built from its contents is offered for it.
  const unreadable = !closed && doctor.data?.verdict === "HIGH_RISK" && typeof doctor.data.recommended_action === "string";
  const ctl = usePrepare(closed);
  const placement = usePlacement(file.path);
  const fetchPreview = usePreviewFetcher(file.path);
  const [mode, setMode] = useState<PrepareMode>("preserve");
  const [holding, setHolding] = useState(false);
  const [selections, setSelections] = useState<MaterialSelection[]>([]);
  const [tab, setTab] = useState<TabId>("materials");

  // A copy Studio wrote and validated for this project in this session (the shared store only accepts those).
  const data = convert.status === "done" ? convert.data : null;
  const preparedPath: string | null = data && !data.blocked && data.validated_ok ? (data.output_path || data.output || null) : null;
  // Either the shared session holds an unvalidated copy, or this screen's own Prepare wrote one the store refused to publish.
  const r = ctl.result;
  const unvalidatedPath: string | null = data && !data.blocked && !data.validated_ok ? (data.output_path || data.output || null)
    : !preparedPath && r && !r.blocked && r.output_path && !r.validated_ok ? r.output_path : null;
  const prepared = preparedPath ? { path: preparedPath, name: data.output_name || preparedPath.split(/[\\/]/).pop() || preparedPath, summary: data.settings_summary, mode: (data.prepare_mode ?? "preserve") as PrepareMode } : null;

  const prepareFailed = !!ctl.error || !!ctl.result?.blocked || (!!ctl.result && !ctl.result.blocked && !ctl.result.output_path);
  const journey = deriveJourney({
    hasProject: true,
    check: { status: doctor.status !== "done" ? doctor.status : eligibility.status === "checking" ? "loading" : "done", prepareBlocked: closed },
    materialsHolding: holding,
    preparing: ctl.pending || convert.status === "loading",
    prepareFailed,
    prepared: !!prepared,
    unvalidated: !!unvalidatedPath,
    hasSliced: !!sliced,
  });

  // The middle follows the journey: what the current stage produced is what is shown, until the person picks another.
  const showsOutcome = !!prepared || !!unvalidatedPath || prepareFailed;
  const auto: View = journey.current === "compare" ? "slice" : showsOutcome ? "copy" : "model";
  const [view, setView] = useState<View>(auto);
  useEffect(() => { setView(auto); }, [auto]);

  const create = () => {
    setView("copy");
    ctl.start(file.path, mode).catch(() => { /* shown by the result area */ });
  };
  const reviewMaterials = () => {
    setTab("materials"); setView("model");
    requestAnimationFrame(() => document.getElementById("materials-review")?.focus());
  };
  const goStage = (id: StageId) => {
    setView(VIEW_OF[id]);
    if (id === "materials") setTab("materials");
    if (id === "copy" && !prepared) setTab("settings");
  };

  const plateCount = placement.check?.available ? placement.check.plate_count ?? 1 : null;
  const plates = plateCount ? `${plateCount} ${plateCount === 1 ? "plate" : "plates"}` : null;

  const tabs: PaneTab[] = [
    {
      id: "target", label: "Target", lazy: true,
      el: <FlatCards><div className="space-y-5"><PreflightCard path={file.path} /><ColorPlanCard path={file.path} /></div></FlatCards>,
    },
    {
      id: "materials", label: "Materials", badge: holding ? "chosen" : null,
      el: (
        <FlatCards>
          <div className="peer empty:hidden">
            {!closed && !unreadable && eligibility.status !== "checking" && (
              <ProjectMaterialsCard bare path={file.path} mode={mode} busy={ctl.pending} onActiveChange={setHolding} onSelectionsChange={setSelections}
                onPrepare={(materials) => ctl.start(file.path, mode, materials)} />
            )}
          </div>
          <p className="hidden text-sm text-muted-foreground peer-empty:block" data-testid="no-materials">
            {closed || unreadable ? "Materials are not offered because Studio cannot prepare this project."
              : eligibility.status === "checking" ? "Checking the project…" : "This file has no filament slots to choose materials for."}
          </p>
        </FlatCards>
      ),
    },
    {
      id: "settings", label: "Copy settings",
      el: (
        <FlatCards>
          <div className="space-y-4">
            <PrepareModeChooser mode={mode} onModeChange={setMode} blocked={closed}
              onCustom={() => ctl.startPreview(file.path)} previewing={ctl.previewing || ctl.pending} />
            {ctl.previewError ? <p className="text-sm text-risk" role="alert">Couldn&apos;t review settings: {(ctl.previewError as Error).message}</p> : null}
            {ctl.preview && (
              <PrepareSettingsSummary summary={ctl.preview.settings_summary} mode={ctl.preview.prepare_mode} isStl={false} preview
                onPreparePreserve={holding ? undefined : () => { setMode("preserve"); ctl.start(file.path, "preserve").catch(() => {}); setView("copy"); }}
                onPrepareRecommended={holding ? undefined : () => { setMode("recommended"); ctl.start(file.path, "recommended").catch(() => {}); setView("copy"); }} />
            )}
            {holding && <p className="text-xs text-muted-foreground">You have material choices. Use Review materials so they are applied to the copy.</p>}
            <p className="text-xs text-muted-foreground">Creating a copy writes a new file. Your original is never modified.</p>
          </div>
        </FlatCards>
      ),
    },
  ];

  return (
    <div className="flex min-h-0 flex-col gap-4" data-testid="job-screen">
      <JobBar name={file.name} path={file.path} ext={file.ext} plates={plates}
        // The comparison is already on screen: its button would only press itself.
        journey={view === "slice" && journey.primary.kind === "compare" ? { ...journey, primary: { kind: "none", label: "" } } : journey}
        onView={goStage} preparedPath={preparedPath} busy={ctl.pending}
        actions={{ create, reviewMaterials, compare: () => setView("slice"), recheck: () => void runDoctor() }} />

      {doctor.status === "error" && (
        <p className="flex items-start gap-2 rounded-md border border-risk/40 bg-risk/5 p-3 text-sm" role="alert">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-risk" aria-hidden="true" />
          Studio could not read this project: {doctor.error ?? "the check failed"}. Try Check again, or open it again.
        </p>
      )}
      {!closed && doctor.data?.verdict === "HIGH_RISK" && typeof doctor.data.recommended_action === "string" && (
        <p className="flex items-start gap-2 rounded-md border border-risk/40 bg-risk/5 p-3 text-sm" role="alert" data-testid="job-high-risk">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-risk" aria-hidden="true" />
          <span>{doctor.data.recommended_action}</span>
        </p>
      )}
      {closed && (
        <p className="flex items-start gap-2 rounded-md border border-risk/40 bg-risk/5 p-3 text-sm" role="alert" data-testid="job-blocked">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-risk" aria-hidden="true" />
          <span>{doctor.data?.prepare_blocked_summary || (gate === "unreadable" ? GATE_COPY.unreadable : "Studio can read this project but cannot prepare a U1 copy of it yet. Open the original in Snapmaker Orca to review it.")}{" "}
            <Link className="underline" to="/compatibility">See the full checks</Link>.</span>
        </p>
      )}

      <div className="grid min-h-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(340px,420px)]">
        <section aria-label={view === "model" ? "Model" : view === "copy" ? "U1 copy" : "Slice comparison"} className="min-w-0">
          {view === "model" && <ModelPane path={file.path} selections={selections} preparedPath={preparedPath} placement={placement} fetcher={fetchPreview} fileUnreadable={unreadable || gate === "unreadable"} />}
          {view === "copy" && (
            ctl.pending ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Creating the U1 copy…
              </p>
            ) : (
              <>
                <CopyResult projectPath={file.path} prepared={prepared} unvalidatedPath={unvalidatedPath} ctl={ctl}
                  onCreateAnother={holding ? undefined : create}
                  onPrepareRecommended={holding ? undefined : () => { setMode("recommended"); ctl.start(file.path, "recommended").catch(() => {}); }} />
                {!prepared && !unvalidatedPath && !prepareFailed && (
                  <p className="text-sm text-muted-foreground" data-testid="no-copy-yet">
                    No U1 copy yet. Create U1 copy writes a new file and never touches your original.
                  </p>
                )}
              </>
            )
          )}
          {view === "slice" && <SliceCompare projectPath={file.path} preparedPath={preparedPath} />}
        </section>

        <aside aria-label="Job settings" className="flex min-h-0 min-w-0 flex-col rounded-lg border border-border bg-card px-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-15rem)] lg:self-start">
          <PaneTabs label="Job settings" tabs={tabs} active={tab} onChange={(id) => setTab(id as TabId)} />
        </aside>
      </div>
    </div>
  );
}
