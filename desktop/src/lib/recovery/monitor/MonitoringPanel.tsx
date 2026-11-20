import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { usePrinter } from "@/store/printer";
import { isValidPort, type MonitoringRead, type HistoryRead } from "../api";
import { MonitorSummary } from "../RecoveryPanel";
import { requestMonitoring } from "./transport";

export const REFRESH_MS = 5000;
export const STALE_MS = 15000;
const field = "h-10 rounded-md border border-border bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50";

export default function MonitoringPanel() {
  const configuredHost = usePrinter(s => s.host);
  const [host, setHost] = useState("");
  const [port, setPort] = useState("7125");
  const [automatic, setAutomatic] = useState(false);
  const [active, setActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<MonitoringRead | null>(null);
  const [history, setHistory] = useState<HistoryRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyReceived, setHistoryReceived] = useState<number | null>(null);
  const [received, setReceived] = useState<number | null>(null);
  const [clock, setClock] = useState(Date.now());
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previous = useRef<string | undefined>(undefined);
  const alive = useRef(true);
  function cancel(clear = false) {
    generation.current++;
    controller.current?.abort(); controller.current = null;
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    setActive(false); setBusy(false);
    if (clear) { setStatus(null); setHistory(null); setError(null); setHistoryError(null); setReceived(null); setHistoryReceived(null); previous.current = undefined; }
  }
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; generation.current++; controller.current?.abort(); if (timer.current) clearTimeout(timer.current); };
  }, []);
  useEffect(() => {
    if (received === null && historyReceived === null) return;
    const tick = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [received, historyReceived]);
  async function read(repeat: boolean) {
    if (!host.trim() || !isValidPort(port)) return;
    controller.current?.abort();
    if (timer.current) clearTimeout(timer.current);
    const token = ++generation.current;
    const mine = new AbortController(); controller.current = mine;
    const valid = () => alive.current && generation.current === token && !mine.signal.aborted;
    setBusy(true); setActive(repeat); setError(null); setHistoryError(null);
    const body = { host: host.trim(), port: Number(port), ...(previous.current ? { previous_state: previous.current } : {}) };
    const [current, last] = await Promise.allSettled([
      requestMonitoring<MonitoringRead>("read", body, mine.signal),
      requestMonitoring<HistoryRead>("history", { host: body.host, port: body.port }, mine.signal),
    ]);
    if (!valid()) return;
    const now = Date.now(); setClock(now);
    if (current.status === "fulfilled") {
      setStatus(current.value); setReceived(now);
      previous.current = current.value.status === "ok" && current.value.print_state !== "unknown" ? current.value.print_state : undefined;
    } else {
      setStatus(null); setReceived(null); previous.current = undefined;
      setError(current.reason instanceof Error ? current.reason.message : "Status is unavailable.");
    }
    if (last.status === "fulfilled") { setHistory(last.value); setHistoryReceived(now); }
    else { setHistory(null); setHistoryReceived(null); setHistoryError("Last-job history is unavailable for this read."); }
    setBusy(false);
    if (repeat) timer.current = setTimeout(() => { if (valid()) void read(true); }, REFRESH_MS);
    else setActive(false);
  }
  const age = received === null ? null : Math.max(0, Math.floor((clock - received) / 1000));
  return <section className="space-y-3 rounded-lg border border-border bg-card p-4" aria-label="Read-only monitoring">
    <h2 className="font-semibold">Read monitoring context</h2>
    <p className="text-sm text-muted-foreground">Status and the last job from the host you choose. Refresh is opt-in and stops when you leave this page. No control, upload, print, heat or motion requests are sent.</p>
    <div className="flex flex-wrap items-end gap-2">
      <label className="text-sm">Host<input aria-label="Configured printer host" className={field} placeholder="printer.local" value={host} onChange={e => { cancel(true); setHost(e.target.value); }} /></label>
      <label className="text-sm">Port<input aria-label="Configured printer port" className={`${field} w-24`} type="number" min="1" max="65535" step="1" value={port} onChange={e => { cancel(true); setPort(e.target.value); }} /></label>
      <Button variant="secondary" disabled={!configuredHost} onClick={() => { cancel(true); setHost(configuredHost); }}>Use configured printer</Button>
      <Button disabled={busy || !host.trim() || !isValidPort(port)} onClick={() => void read(automatic)}>{busy ? "Reading…" : active ? "Refresh now" : automatic ? "Start monitoring" : "Read status"}</Button>
      <Button variant="secondary" disabled={!busy && !active} onClick={() => cancel()}>Stop monitoring</Button>
    </div>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={automatic} onChange={e => { cancel(); setAutomatic(e.target.checked); }} />Refresh every 5 seconds after each completed read</label>
    {!isValidPort(port) && <p role="alert">Enter a whole-number port from 1 to 65535.</p>}
    {error && <p role="alert" className="text-sm text-risk">{error}</p>}
    {received !== null && <p role="status" className="text-sm">Last response received {age} seconds ago{clock - received >= STALE_MS ? " — stale; read again before relying on it" : ""}. This is receipt time, not a verified printer observation timestamp.</p>}
    {status && status.status !== "ok" && <p role="status" className="text-sm">The printer status reply was unusable; no current printer state is confirmed.</p>}
    <MonitorSummary read={status} />
    {status?.reconciliation && <div className="text-sm" aria-label="Status transitions">
      {status.reconciliation.events.map((event, i) => <p key={i}>{event.from} → {event.to} (inferred from polling; intervening states unknown)</p>)}
    </div>}
    {historyError && <p role="status" className="text-sm">{historyError}</p>}
    {history && <div aria-label="Last job" className="text-sm"><h3 className="font-medium">Last job</h3>{historyReceived !== null && <p role="status" data-testid="history-age">History response received {Math.max(0, Math.floor((clock - historyReceived) / 1000))} seconds ago{clock - historyReceived >= STALE_MS ? " — stale; read history again before relying on it" : ""}. This is receipt time, not a verified job observation timestamp.</p>}<p>{history.status === "ok" ? history.last_job ? `${history.last_job.filename ?? "Unknown file"}: ${history.last_job.outcome}` : "No last job was returned." : "Last-job history is unavailable."}</p><p>{history.note ?? "A filename match does not verify the local artifact."}</p></div>}
    <p className="text-xs text-muted-foreground">Camera context remains unknown. Each status/history request has a 4-second UI timeout; reads do not overlap between refresh cycles.</p>
  </section>;
}
