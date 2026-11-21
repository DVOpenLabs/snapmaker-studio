import AccessorySetupFields, { EMPTY_ACCESSORY, accessoryBody } from "./AccessorySetupFields";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useJob } from "@/store/job";
import { useSession } from "@/store/session";
import { saveSetupDraft } from "@/lib/setupDraft";
import { Server } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { buildEvaluateBody, evaluateSetup } from "@/lib/setupsApi";
import type { EvaluateResponse } from "@/lib/setupsTypes";
import SetupReportView from "./SetupReportView";

/** Reads one host on the local network and shows what it says. The OctoPrint key lives in this
 *  component's state only: it is cleared when the view is left and never stored anywhere. */
export default function SetupsView() {
  const navigate = useNavigate();
  const record = useJob(state => state.record);
  const verified = useJob(state => state.verified);
  const projectPath = verified && record && /\.3mf$/i.test(record.original.path) ? record.original.path : null;
  const [accessory, setAccessory] = useState(EMPTY_ACCESSORY);
  const revision = useRef(0);
  const invalidate = () => { revision.current++; setResult(null); setError(null); setBusy(false); };
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [key, setKey] = useState("");
  const [materials, setMaterials] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EvaluateResponse | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; setKey(""); };
  }, []);

  const run = async () => {
    // A failed read must not leave the previous host's report under the new inputs.
    const token = ++revision.current;
    setBusy(true); setError(null); setResult(null);
    try {
      const res = await evaluateSetup(buildEvaluateBody({ host, port, key, materials: materials.split(","), accessory: accessoryBody(accessory) }));
      if (alive.current && revision.current === token) setResult(res);
    } catch (e) {
      if (alive.current && revision.current === token) setError(e instanceof Error ? e.message : "The check failed.");
    } finally {
      if (alive.current && revision.current === token) setBusy(false);
    }
  };

  function continueToPrepare() {
    const now = useJob.getState();
    if (!result || busy || !projectPath || !now.verified || now.record?.original.path !== projectPath) return;
    if (!saveSetupDraft(projectPath, { host, port, accessory })) { setError("Setup inputs are too large to transfer. Shorten them and read again."); return; }
    useSession.getState().setFile(projectPath);
    useSession.getState().invalidatePrepareSetup(projectPath);
    navigate("/this-print", { state: { prepareSetup: true } });
  }

  const field = "h-9 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50";
  return (
    <div className="space-y-5 p-6">
      <PageHeader icon={Server} title="Setups" subtitle="Read a printer host on your network and see what it reports. Studio only reads; it never starts, moves or heats anything." />
      <div className="flex flex-wrap items-end gap-2">
        <input className={`${field} w-48`} aria-label="Host address" placeholder="192.168.1.50 or u1.local" value={host} onChange={(e) => { invalidate(); setHost(e.target.value); }} />
        <input className={`${field} w-24`} aria-label="Port" placeholder="7125" value={port} onChange={(e) => { invalidate(); setPort(e.target.value); }} />
        <input className={`${field} w-56`} aria-label="OctoPrint API key" type="password" autoComplete="off" placeholder="OctoPrint API key (optional)" value={key} onChange={(e) => { invalidate(); setKey(e.target.value); }} />
        <input className={`${field} w-64`} aria-label="Project materials" placeholder="Project materials, comma separated (optional)" value={materials} onChange={(e) => { invalidate(); setMaterials(e.target.value); }} />
        <Button size="sm" disabled={busy || (host.trim() === "" && !accessory.adapter)} onClick={() => void run()}>{busy ? "Reading..." : "Read setup"}</Button>
      </div>
      <p className="text-xs text-muted-foreground">The key is sent once with this request and is not saved.</p>
      <AccessorySetupFields value={accessory} onChange={value => { invalidate(); setAccessory(value); }} disabled={busy} topology={result?.topology} />
      <section className="space-y-2 rounded-md border border-border p-3" aria-label="Continue with this setup">
        <Button size="sm" variant="secondary" disabled={busy || !result || !projectPath} onClick={continueToPrepare}>Continue in Prepare</Button>
        <p className="text-xs text-muted-foreground">{projectPath ? `For ${record!.original.name}. ` : "Open or reopen a checked 3MF project first. "}Transfers the inputs, not this report. Prepare stays paused until you read again. The API key is not transferred; enter it again if required. No read or preparation starts automatically.</p>
      </section>
      {error && <p className="text-sm text-risk" role="alert">{error}</p>}
      {result && <SetupReportView report={result.report} />}
    </div>
  );
}
