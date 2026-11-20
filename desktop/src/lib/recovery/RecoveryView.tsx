import { useEffect, useState, useSyncExternalStore } from "react";
import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { legacyJobSnapshot, saveCheckpoint } from "@/lib/recovery/api";
import { RestorePreview } from "@/lib/recovery/RecoveryPanel";
import { getPreview, refreshPreview, registerRecoverySubscriber, subscribePreview } from "@/lib/recovery/subscriber";
import { planWorkspaceCheckpoint, roleLabel, workspaceCheckpointBody } from "@/lib/recovery/workspace";
import { useJob } from "@/store/job";

import MonitoringPanel from "./monitor/MonitoringPanel";

const sample = { project: "Synthetic demo", stage: "review" };
type Notice = { kind: "ok" | "error"; text: string } | null;

export function RecoveryView() {
  const preview = useSyncExternalStore(subscribePreview, getPreview, getPreview);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const record = useJob((state) => state.record);
  const verified = useJob((state) => state.verified);
  const plan = planWorkspaceCheckpoint(record, verified);

  // Registered through the lifecycle seam (extLifecycle), not App.tsx; app start only reads the checkpoint.
  useEffect(() => registerRecoverySubscriber(), []);

  const saveWorkspace = async () => {
    setBusy(true); setNotice(null);
    try {
      if (!record || !plan.canSave) throw new Error(plan.why ?? "No project is open.");
      if (preview.status !== "ready" || !preview.data) throw new Error("Read the saved checkpoint successfully before saving.");
      // The revision this page last read, including 0 for "no checkpoint yet", so a second window cannot be overwritten.
      const saved = await saveCheckpoint(workspaceCheckpointBody(plan, record, preview.data.revision, legacyJobSnapshot()));
      await refreshPreview();
      // A file that was missing or unreadable when saved has no fingerprint to compare against later: say so now.
      const fresh = getPreview();
      const confirmed = fresh.status === "ready" && fresh.data?.revision === saved.revision;
      const weak = !confirmed ? [] : (fresh.data?.files ?? []).filter((f) => f.state === "unverified" || f.state === "missing" || f.state === "unreadable");
      const caveat = weak.length ? ` Not verifiable later (missing, unreadable or no fingerprint when saved): ${weak.map((f) => f.name).join(", ")}.` : "";
      setNotice({ kind: "ok", text: `Workspace checkpoint saved for ${record.original.name} · revision ${saved.revision} · ${plan.tracked.length} file(s) tracked.${caveat}${confirmed ? "" : " The new restore preview was not confirmed. Refresh before relying on it."}` });
    } catch (error) { setNotice({ kind: "error", text: `Checkpoint NOT saved: ${error instanceof Error ? error.message : "it failed"}` }); }
    finally { setBusy(false); }
  };
  const saveSample = async () => {
    setBusy(true); setNotice(null);
    try {
      if (preview.status !== "ready" || !preview.data) throw new Error("Read the saved checkpoint successfully before saving.");
      const saved = await saveCheckpoint({ workspace: sample, observations: [], files: [], jobs: legacyJobSnapshot(),
        expected_revision: preview.data.revision });
      setNotice({ kind: "ok", text: `Sample checkpoint saved (demo data, no files tracked) · revision ${saved.revision}` });
      await refreshPreview();
    } catch (error) { setNotice({ kind: "error", text: `Sample checkpoint NOT saved: ${error instanceof Error ? error.message : "it failed"}` }); }
    finally { setBusy(false); }
  };
  return <div className="space-y-5 p-6">
    <PageHeader icon={RotateCcw} title="Workspace recovery" subtitle="Checkpoint the files of the project you have open, then see later which of them changed or went missing. Recovery only reads: it never re-sends, uploads, heats or moves anything." />
    <section className="space-y-3 rounded-lg border border-border bg-card p-4" aria-label="Workspace checkpoint">
      <h2 className="font-semibold">Checkpoint this workspace</h2>
      {plan.canSave ? <>
        <p className="text-sm text-muted-foreground">Project: {plan.project}. The checkpoint will track these files:</p>
        <ul className="list-disc pl-5 text-sm" data-testid="tracked-files">
          {plan.tracked.map((f) => <li key={f.role}>{roleLabel(f.role)}: {f.name}</li>)}
        </ul>
        {plan.unavailable.length > 0 && <ul className="list-disc pl-5 text-sm text-muted-foreground" data-testid="unavailable-files">
          {plan.unavailable.map((f) => <li key={f.role}>{roleLabel(f.role)} not tracked: {f.reason}</li>)}
        </ul>}
      </> : <p className="text-sm text-muted-foreground" data-testid="no-workspace">{plan.why}</p>}
      <div className="flex gap-2">
        <Button disabled={busy || preview.status !== "ready" || !preview.data || !plan.canSave} onClick={() => void saveWorkspace()}>Checkpoint this workspace</Button>
        <Button variant="secondary" disabled={busy} onClick={() => void refreshPreview()}>Refresh restore preview</Button>
      </div>
      {notice && <p role={notice.kind === "error" ? "alert" : "status"} className={`text-sm ${notice.kind === "error" ? "text-destructive" : ""}`} data-testid="checkpoint-notice">{notice.text}</p>}
      {preview.status === "ready" ? <RestorePreview data={preview.data} /> : <>
        <p role="status" className="text-sm">{preview.status === "failed" ? "The latest checkpoint read failed. Refresh successfully before saving or relying on the preview." : "Reading the latest checkpoint. Saving is paused until the read succeeds."}</p>
        {preview.data && <details className="rounded border border-border p-3" aria-label="Earlier checkpoint preview">
          <summary>Earlier preview — not current</summary>
          <RestorePreview data={preview.data} />
        </details>}
      </>}
      {preview.error && <p role="status" className="text-sm">{preview.error}</p>}
    </section>
    <section className="space-y-3 rounded-lg border border-dashed border-border bg-card p-4" aria-label="Sample data">
      <h2 className="font-semibold">Sample data (not your workspace)</h2>
      <p className="text-sm text-muted-foreground">Saves a made-up checkpoint with no files, to try the preview. It replaces the saved checkpoint.</p>
      <Button variant="secondary" disabled={busy || preview.status !== "ready" || !preview.data} onClick={() => void saveSample()}>Save sample checkpoint</Button>
    </section>
    <MonitoringPanel />
  </div>;
}
