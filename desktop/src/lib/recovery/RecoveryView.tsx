import { useEffect, useState, useSyncExternalStore } from "react";
import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { legacyJobSnapshot, readMonitoring, saveCheckpoint, type MonitoringRead } from "@/lib/recovery/api";
import { MonitorSummary, RestorePreview } from "@/lib/recovery/RecoveryPanel";
import { getPreview, refreshPreview, registerRecoverySubscriber, subscribePreview } from "@/lib/recovery/subscriber";

const sample = { project: "Synthetic demo", stage: "review" };

export function RecoveryView() {
  const preview = useSyncExternalStore(subscribePreview, getPreview, getPreview);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [host, setHost] = useState("");
  const [monitor, setMonitor] = useState<MonitoringRead | null>(null);

  // Registered through the lifecycle seam (extLifecycle), not App.tsx; app start only reads the checkpoint.
  useEffect(() => registerRecoverySubscriber(), []);

  const checkpoint = async () => {
    setBusy(true); setMessage("");
    try {
      if (!preview.data) throw new Error("Read the saved checkpoint first, then save.");
      // The revision this page last read, including 0 for "no checkpoint yet", so a second window cannot be overwritten.
      const saved = await saveCheckpoint({ workspace: sample, observations: [], files: [], jobs: legacyJobSnapshot(),
        expected_revision: preview.data.revision });
      setMessage(`Checkpoint saved · revision ${saved.revision}`);
      await refreshPreview();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Checkpoint failed"); }
    finally { setBusy(false); }
  };
  const monitorRead = async () => {
    setBusy(true); setMessage("");
    try { setMonitor(await readMonitoring(host, "7125")); }
    catch (error) { setMonitor(null); setMessage(error instanceof Error ? error.message : "Monitoring read failed"); }
    finally { setBusy(false); }
  };
  return <div className="space-y-5 p-6">
    <PageHeader icon={RotateCcw} title="Workspace recovery" subtitle="Preview: saves a sample checkpoint (not your open workspace yet) and shows what may need a fresh read." />
    <section className="space-y-3 rounded-lg border border-border bg-card p-4">
      <h2 className="font-semibold">Checkpoint</h2>
      <p className="text-sm text-muted-foreground">Synthetic example workspace: Synthetic demo · review.</p>
      <div className="flex gap-2">
        <Button disabled={busy || !preview.data} onClick={() => void checkpoint()}>Save sample checkpoint</Button>
        <Button variant="secondary" disabled={busy} onClick={() => void refreshPreview()}>Refresh restore preview</Button>
      </div>
      <RestorePreview data={preview.data} />
      {preview.error && <p role="status" className="text-sm">{preview.error}</p>}
      {message && <p role="status" className="text-sm">{message}</p>}
    </section>
    <section className="space-y-3 rounded-lg border border-border bg-card p-4">
      <h2 className="font-semibold">Read monitoring context</h2>
      <p className="text-sm text-muted-foreground">One bounded, read-only request to your configured printer host. A filename match stays unverified.</p>
      <div className="flex gap-2">
        <input aria-label="Configured printer host" className="h-9 w-64 rounded-md border border-border bg-background px-3 text-sm" placeholder="printer.local" value={host} onChange={(e) => setHost(e.target.value)} />
        <Button variant="secondary" disabled={busy || !host.trim()} onClick={() => void monitorRead()}>Read status</Button>
      </div>
      <MonitorSummary read={monitor} />
    </section>
  </div>;
}
