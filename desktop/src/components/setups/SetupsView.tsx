import { useEffect, useRef, useState } from "react";
import { Server } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { buildEvaluateBody, evaluateSetup } from "@/lib/setupsApi";
import type { EvaluateResponse } from "@/lib/setupsTypes";
import SetupReportView from "./SetupReportView";
import { runRead } from "./runRead";

/** Reads one host on the local network and shows what it says. The OctoPrint key lives in this
 *  component's state only: it is cleared when the view is left and never stored anywhere. */
export default function SetupsView() {
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

  const latest = useRef(0);
  const run = () => {
    const mine = ++latest.current;
    return runRead(
      () => evaluateSetup(buildEvaluateBody({ host, port, key, materials: materials.split(",") })),
      (patch) => {
        if ("busy" in patch) setBusy(Boolean(patch.busy));
        if ("error" in patch) setError(patch.error ?? null);
        if ("result" in patch) setResult(patch.result ?? null);
      },
      () => alive.current && latest.current === mine,
    );
  };

  const field = "h-9 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50";
  return (
    <div className="space-y-5 p-6">
      <PageHeader icon={Server} title="Setups" subtitle="Read a printer host on your network and see what it reports. Studio only reads; it never starts, moves or heats anything." />
      <div className="flex flex-wrap items-end gap-2">
        <input className={`${field} w-48`} aria-label="Host address" placeholder="192.168.1.50 or u1.local" value={host} onChange={(e) => setHost(e.target.value)} />
        <input className={`${field} w-24`} aria-label="Port" placeholder="7125" value={port} onChange={(e) => setPort(e.target.value)} />
        <input className={`${field} w-56`} aria-label="OctoPrint API key" type="password" autoComplete="off" placeholder="OctoPrint API key (optional)" value={key} onChange={(e) => setKey(e.target.value)} />
        <input className={`${field} w-64`} aria-label="Project materials" placeholder="Project materials, comma separated (optional)" value={materials} onChange={(e) => setMaterials(e.target.value)} />
        <Button size="sm" disabled={busy || host.trim() === ""} onClick={() => void run()}>{busy ? "Reading..." : "Read setup"}</Button>
      </div>
      <p className="text-xs text-muted-foreground">The key is sent once with this request and is not saved.</p>
      {error && <p className="text-sm text-risk" role="alert">{error}</p>}
      {result && <SetupReportView report={result.report} />}
    </div>
  );
}
