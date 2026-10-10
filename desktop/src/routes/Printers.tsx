import { printerBadge } from "@/lib/printerBadge";
import { useState, useEffect, useCallback, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Printer, Loader2, RotateCw, Thermometer, AlertTriangle, CheckCircle2,
  ShieldCheck, Wifi, Activity, History, HeartPulse, Layers, TrendingUp, Cpu, Sparkles,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { Link } from "react-router-dom";
import {
  printerDiscover, printerStatus, printerHistory, printerDiagnostics, printerFileMetadata,
  printerFailureInsights, printerHealth, printerFirmware, nozzleStatus, type NozzleStatus,
} from "@/api";
import { usePrinter } from "@/store/printer";
import { useFilament } from "@/store/filament";
import { useNozzleNotesVersion } from "@/store/nozzleRevision";
import { PrinterControls } from "@/components/PrinterControls";
import { toPrintState } from "@/lib/printerControl";
import { nozzleSummaryLine } from "@/lib/nozzleRows";
import { createGenerationGuard, nozzleDataStale, runNozzleFetch } from "@/lib/nozzleFetch";
import { printerHubNozzleFetchTrigger } from "@/lib/nozzleFetchTriggers";

const NOZZLE_PORT = 7125;

function fmtDur(s: number | null | undefined): string {
  if (s == null) return "—";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}
const FAILED = new Set(["error", "cancelled", "klippy_shutdown", "klippy_disconnect", "interrupted"]);


// How each printer Studio ships a profile for may be described, and no more.
// The U1 is the only machine this project has connected to; every other entry
// keeps the qualifier, because "profile verified" and "verified" are different
// claims and only one of them is true here.
const PRINTER_LABELS: Record<string, { name: string; level: string }> = {
  snapmaker_u1: { name: "Snapmaker U1", level: "hardware verified" },
  voron_2_4_250: {
    name: "VORON 2.4 250",
    level: "profile verified — hardware not tested by this project",
  },
};

// U1 Printer Hub: discover + read-only live status over the U1's open Moonraker,
// plus user-confirmed controls (send/pause/resume/cancel) — never auto-started.
// Monitor + send files + controls — all dangerous actions confirmed.
export default function Printers() {
  const savedHost = usePrinter((s) => s.host);
  const setSavedHost = usePrinter((s) => s.setHost);
  const filamentPrice = useFilament((s) => s.pricePerKg);
  const filamentCurrency = useFilament((s) => s.currency);
  const [host, setHost] = useState(savedHost);
  const [connected, setConnected] = useState<string | null>(null);

  const connect = (h: string) => { const v = h.trim(); if (!v) return; setSavedHost(v); setConnected(v); };

  // Auto-connect a previously-saved printer when the Hub opens, so returning
  // users land on live status instead of an empty input box.
  useEffect(() => {
    if (savedHost && !connected) connect(savedHost);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const discover = useQuery({ queryKey: ["discover"], queryFn: () => printerDiscover(), enabled: false });
  const status = useQuery({
    queryKey: ["printer-status", connected],
    queryFn: () => printerStatus(connected as string),
    enabled: !!connected,
    refetchInterval: connected ? 3000 : false,  // live, read-only polling
  });
  const diag = useQuery({
    queryKey: ["printer-diag", connected],
    queryFn: () => printerDiagnostics(connected as string),
    enabled: !!connected, refetchInterval: connected ? 10000 : false,
  });
  const hist = useQuery({
    queryKey: ["printer-history", connected],
    queryFn: () => printerHistory(connected as string),
    enabled: !!connected, refetchInterval: connected ? 30000 : false,
  });
  // Failure-Pattern Learning: insight derived from the printer's own history.
  const failInsights = useQuery({
    queryKey: ["printer-failures", connected],
    queryFn: () => printerFailureInsights(connected as string),
    enabled: !!connected, refetchInterval: connected ? 60000 : false, retry: false,
  });
  // Printer health: firmware state and history failures, as the printer reports them.
  const health = useQuery({
    queryKey: ["printer-health", connected],
    queryFn: () => printerHealth(connected as string),
    enabled: !!connected, refetchInterval: connected ? 60000 : false, retry: false,
  });
  // The state chip follows the same driver list as the health card below it (never "Healthy" beside listed concerns).
  const badge = printerBadge({ diag: diag.data, drivers: health.data?.drivers });
  // Firmware Capability Intelligence: what this U1's firmware actually exposes.
  const firmware = useQuery({
    queryKey: ["printer-firmware", connected],
    queryFn: () => printerFirmware(connected as string),
    enabled: !!connected, staleTime: 300000, retry: false,
  });
  // One-line nozzle summary: fetched on mount, host change, and manual refresh
  // only (v1.2 A1.13 — never polled). Not react-query, deliberately: it uses
  // the same plain two-phase runner (lib/nozzleFetch.ts) as the Settings
  // table, guarded by a single monotonic request token — no shared floor, no
  // self-trigger guard to get wrong (that whole machinery was deleted in the
  // round-3 re-diagnosis). It DOES subscribe to the global nozzleNotesVersion
  // counter (F5): unlike the Settings table, this is a read-only view with no
  // mutations of its own, so it needs something else's mutation to tell it
  // to refetch.
  const [nozzleData, setNozzleData] = useState<NozzleStatus | null>(null);
  const [nozzleChecking, setNozzleChecking] = useState(false);
  const [nozzleFetching, setNozzleFetching] = useState(false);
  const nozzleGeneration = useRef(createGenerationGuard()).current;
  // Tracks which host `nozzleData` was actually fetched for, so a fetch that
  // starts for a different host clears it immediately — otherwise printer
  // A's sizes stay on screen under printer B's line until B's own fetch
  // lands (or forever, if both of B's phases then fail) (CodeRabbit PR #41
  // #5). A same-host manual Refresh does NOT clear first, so it doesn't
  // flash empty.
  const nozzleDataHost = useRef<string | null>(null);
  const nozzleNotesVersion = useNozzleNotesVersion((s) => s.version);

  const fetchNozzle = useCallback(() => {
    if (!connected) {
      nozzleGeneration.invalidate(); // R4-D2: !connected also stops anything in flight
      nozzleDataHost.current = null;
      setNozzleData(null);
      return;
    }
    if (nozzleDataStale(nozzleDataHost.current, connected)) {
      setNozzleData(null);
    }
    nozzleDataHost.current = connected;
    const gen = nozzleGeneration.next();
    const host = connected;
    setNozzleFetching(true);
    void runNozzleFetch({
      host, port: NOZZLE_PORT,
      isCurrent: () => nozzleGeneration.isCurrent(gen),
      api: { nozzleStatus },
      on: {
        quick: (s) => { setNozzleData(s); setNozzleChecking(true); },
        live: (s) => { setNozzleData(s); setNozzleChecking(false); },
        liveFailed: () => setNozzleChecking(false),
        // Both phases failed: nothing was confirmed for this host — never
        // leave a previous (possibly different) host's data on screen.
        allFailed: () => { setNozzleChecking(false); setNozzleData(null); },
      },
    }).finally(() => { if (nozzleGeneration.isCurrent(gen)) setNozzleFetching(false); });
  }, [connected, nozzleGeneration]);

  useEffect(() => {
    fetchNozzle();
    // R4-D2: bump the generation on unmount AND on every trigger change (the
    // cleanup React runs right before re-invoking this effect for a new
    // dependency value) — an in-flight phase-1/phase-2 from the previous
    // trigger must never apply after either.
    return () => nozzleGeneration.invalidate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...printerHubNozzleFetchTrigger(connected, nozzleNotesVersion), fetchNozzle, nozzleGeneration]);

  const filename = status.data?.filename ?? null;
  const meta = useQuery({
    queryKey: ["printer-meta", connected, filename],
    queryFn: () => printerFileMetadata(connected as string, filename as string),
    enabled: !!connected && !!filename, staleTime: 60000, retry: false,
  });
  const state = status.data?.print_state;
  const isPrinting = state === "printing";

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <PageHeader
        icon={Printer}
        title="Printer Hub"
        subtitle="Monitor your U1 and send files — every action is confirmed."
        badge={
          <span className="inline-flex items-center gap-1 rounded-full border border-ready/40 bg-ready/10 px-2 py-0.5 text-xs font-medium text-ready">
            <ShieldCheck className="h-3.5 w-3.5" /> Monitor + confirmed controls
          </span>
        }
      />

      <Card>
        <CardContent className="space-y-3 p-5">
          <p className="text-sm font-medium">Connect to your U1</p>
          <p className="text-xs text-muted-foreground">
            Type <code className="rounded bg-muted px-1">U1.local</code> or its IP, or tap <b>Auto-detect my U1</b>. Studio shows live status and runs send, pause, resume and cancel only when you confirm — it never auto-starts a print.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex h-9 min-w-[200px] flex-1 items-center gap-2 rounded-md border border-border bg-card px-3">
              <Wifi className="h-4 w-4 text-muted-foreground" />
              <input value={host} onChange={(e) => setHost(e.target.value)} onKeyDown={(e) => e.key === "Enter" && connect(host)} placeholder="U1.local"
                className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground" />
            </div>
            <Button variant="secondary" onClick={() => connect(host)} disabled={!host.trim()}>Connect</Button>
            <Button onClick={() => discover.refetch()} disabled={discover.isFetching}>
              {discover.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />} Auto-detect my U1
            </Button>
          </div>
          {discover.data && (
            <ul className="space-y-1 text-sm">
              {discover.data.map((p) => (
                <li key={p.host} className="flex items-center gap-2 py-1">
                  {p.reachable ? <CheckCircle2 className="h-4 w-4 text-ready" /> : <AlertTriangle className="h-4 w-4 text-muted-foreground" />}
                  <span className="font-medium">{p.host}</span>
                  {/* What answered is a Moonraker printer. Naming it as a specific
                      model was a claim about hardware Studio had not identified, and
                      saying a silent host was not that model described a machine that
                      had said nothing at all. */}
                  <span className="text-xs text-muted-foreground">{p.reachable ? "printer found — ready" : "no answer"}</span>
                  {p.reachable && (
                    <Button size="sm" className="ml-auto" onClick={() => { setHost(p.host); connect(p.host); }}>Use this printer</Button>
                  )}
                </li>
              ))}
              {discover.data.every((p) => !p.reachable) && (
                <li className="pt-1 text-xs text-muted-foreground">No printer answered. Make sure it’s powered on and on the same Wi-Fi, then try typing its IP address above.</li>
              )}
            </ul>
          )}
        </CardContent>
      </Card>

      {!connected && !discover.data && (
        <p className="text-center text-xs text-muted-foreground">Tip: leave this open while you print — it refreshes every few seconds.</p>
      )}

      {connected && (
        <Card>
          <CardContent className="space-y-4 p-5">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-sm font-semibold"><Activity className="h-4 w-4 text-primary" /> {connected}</span>
              <span className="flex items-center gap-2">
                {badge && (
                  <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${badge.ok ? "bg-ready/10 text-ready" : "bg-repairable/10 text-repairable"}`}>
                    <HeartPulse className="h-3 w-3" /> {badge.label}
                  </span>
                )}
                {status.isFetching && <span className="flex items-center gap-1 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> live</span>}
              </span>
            </div>
            {diag.data && !diag.data.healthy && (diag.data.state_message || diag.data.warnings.length > 0) && (
              <p className="flex items-start gap-1.5 rounded-md bg-repairable/5 px-3 py-2 text-xs text-repairable">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {diag.data.state_message || diag.data.warnings[0]}
              </p>
            )}
            {status.status === "error" && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground"><AlertTriangle className="h-4 w-4" /> Couldn’t reach this printer. Check it’s powered on and on the same network.</p>
            )}
            {status.data && (
              <>
                <div className="flex items-center gap-2 text-sm">
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium uppercase tracking-wide ${isPrinting ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"}`}>{state ?? "idle"}</span>
                  {status.data.filename && <span className="truncate text-muted-foreground">{status.data.filename}</span>}
                  {status.data.progress != null && <span className="ml-auto font-medium">{Math.round(status.data.progress * 100)}%</span>}
                </div>
                {(status.data.current_layer != null || status.data.message || status.data.print_duration_s != null) && (
                  <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    {status.data.current_layer != null && status.data.total_layer != null && (
                      <span className="inline-flex items-center gap-1"><Layers className="h-3 w-3" /> Layer {status.data.current_layer} / {status.data.total_layer}</span>
                    )}
                    {status.data.print_duration_s != null && <span>Elapsed {fmtDur(status.data.print_duration_s)}</span>}
                    {status.data.message && <span className="truncate">{status.data.message}</span>}
                  </p>
                )}
                {meta.data?.available && (
                  <p className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                    {meta.data.estimated_time_s != null && <span>Est total {fmtDur(meta.data.estimated_time_s)}</span>}
                    {meta.data.filament_weight_g != null && <span>~{Math.round(meta.data.filament_weight_g)} g filament</span>}
                    {meta.data.filament_weight_g != null && <span>~{filamentCurrency}{((meta.data.filament_weight_g / 1000) * filamentPrice).toFixed(2)} material</span>}
                    {meta.data.layer_count != null && <span>{meta.data.layer_count} layers</span>}
                    {meta.data.slicer && <span>sliced by {meta.data.slicer}</span>}
                    <span className="opacity-70">(from the file's own slicer data)</span>
                  </p>
                )}
                {status.data.progress != null && (
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${Math.round((status.data.progress ?? 0) * 100)}%` }} />
                  </div>
                )}
                <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
                  <div className="rounded-md border border-border p-2"><p className="flex items-center gap-1 text-xs text-muted-foreground"><Thermometer className="h-3 w-3" /> Bed</p><p>{status.data.bed.temperature ?? "—"}° / {status.data.bed.target ?? "—"}°</p></div>
                  {status.data.toolheads.map((t) => (
                    <div key={t.index} className="rounded-md border border-border p-2"><p className="flex items-center gap-1 text-xs text-muted-foreground"><Thermometer className="h-3 w-3" /> Tool {t.index + 1}</p><p>{t.temperature ?? "—"}° / {t.target ?? "—"}°</p></div>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">Live status — updates automatically.</p>
              </>
            )}
            {connected && (
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                {nozzleSummaryLine(nozzleData)}
                {nozzleChecking && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
                {" · "}
                <Link to="/settings" className="text-primary underline">Settings</Link>
                <Button
                  size="sm" variant="ghost" className="h-6 px-1.5 text-[11px]"
                  onClick={() => fetchNozzle()} disabled={nozzleFetching}
                >
                  <RotateCw className="h-3 w-3" /> Refresh
                </Button>
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {connected && (
        <PrinterControls
          host={connected}
          printState={toPrintState(state)}
          online={!!status.data && !status.isError}
          onChanged={() => { status.refetch(); hist.refetch(); }}
        />
      )}

      {connected && health.data?.available && health.data.score != null && (
        <Card>
          <CardContent className="space-y-3 p-5">
            <span className="flex items-center gap-2 text-sm font-semibold"><HeartPulse className="h-4 w-4 text-primary" /> What the printer reported</span>
            {health.data.verdict && <p className="text-sm text-muted-foreground">{health.data.verdict}</p>}
            {health.data.drivers && health.data.drivers.length > 0 && (
              <ul className="space-y-1 text-xs text-muted-foreground">
                {health.data.drivers.map((d, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-current opacity-60" /> {d}
                  </li>
                ))}
              </ul>
            )}
            {health.data.basis && <p className="text-[11px] text-muted-foreground opacity-70">From {health.data.basis} — read-only.</p>}
          </CardContent>
        </Card>
      )}

      {connected && firmware.data?.available && (firmware.data.features?.length ?? 0) > 0 && (
        <Card>
          <CardContent className="space-y-3 p-5">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-sm font-semibold"><Cpu className="h-4 w-4 text-primary" /> What this printer can do</span>
              {firmware.data.extended_firmware ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary"
                      title={firmware.data.extended_firmware_evidence ?? undefined}>
                  <Sparkles className="h-3 w-3" /> Community firmware
                </span>
              ) : firmware.data.many_custom_macros ? (
                // Somebody has added macros to this printer. That is a fact about
                // the printer; concluding "extended firmware" from it was not, and
                // the badge saying so was shown to people running stock.
                <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
                  <Sparkles className="h-3 w-3" /> {firmware.data.macro_count} custom macros
                </span>
              ) : null}
            </div>
            <ul className="grid gap-2 sm:grid-cols-2">
              {firmware.data.features!.map((f, i) => (
                <li key={i} className="flex items-start gap-2 rounded-md border border-border p-2 text-xs">
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ready" />
                  <span><span className="font-medium text-foreground">{f.name}</span>{f.detail ? <span className="text-muted-foreground"> — {f.detail}</span> : null}</span>
                </li>
              ))}
            </ul>
            {/* Which machine this is, and on what evidence. Shown only when the
                printer actually identified itself: an unnamed printer is checked
                just as thoroughly, and inventing a model to fill the space would
                be the assumption this card exists to avoid. */}
            {firmware.data.identity?.matched && firmware.data.identity.printer_id && (
              <p className="text-[11px] text-muted-foreground">
                Identified as <span className="font-medium text-foreground">{PRINTER_LABELS[firmware.data.identity.printer_id]?.name ?? firmware.data.identity.printer_id}</span>
                {" — "}{PRINTER_LABELS[firmware.data.identity.printer_id]?.level ?? "verification not established"}.
                {firmware.data.identity.evidence ? <span className="opacity-70"> {firmware.data.identity.evidence}.</span> : null}
              </p>
            )}
            {firmware.data.summary && <p className="text-[11px] text-muted-foreground opacity-70">{firmware.data.summary} Read-only.</p>}
          </CardContent>
        </Card>
      )}

      {connected && failInsights.data?.available && (failInsights.data.failed ?? 0) > 0 && (
        <Card>
          <CardContent className="space-y-3 p-5">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-sm font-semibold"><TrendingUp className="h-4 w-4 text-primary" /> What your history is telling you</span>
              <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                failInsights.data.overall_level === "ok" ? "bg-ready/10 text-ready" : failInsights.data.overall_level === "warn" ? "bg-repairable/10 text-repairable" : "bg-risk/10 text-risk"}`}>
                {failInsights.data.failed}/{failInsights.data.total} failed
              </span>
            </div>
            <p className="text-xs text-muted-foreground">{failInsights.data.overall_text}</p>
            <ul className="space-y-1.5 text-sm">
              {failInsights.data.findings?.map((f, i) => (
                <li key={i} className="flex items-start gap-2">
                  {f.level === "ok"
                    ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ready" />
                    : <AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${f.level === "risk" ? "text-risk" : "text-repairable"}`} />}
                  <span className="text-muted-foreground">{f.text}</span>
                </li>
              ))}
            </ul>
            <p className="text-[11px] text-muted-foreground">Learned from your printer's own print history — read-only.</p>
          </CardContent>
        </Card>
      )}

      {connected && hist.data && hist.data.jobs.length > 0 && (
        <Card>
          <CardContent className="space-y-3 p-5">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-sm font-semibold"><History className="h-4 w-4 text-primary" /> Recent prints</span>
              {hist.data.failures.length > 0 && (
                <span className="inline-flex items-center gap-1 rounded-full bg-risk/10 px-2 py-0.5 text-[11px] font-semibold text-risk">
                  <AlertTriangle className="h-3 w-3" /> {hist.data.failures.length} failed
                </span>
              )}
            </div>
            <ul className="divide-y divide-border text-sm">
              {hist.data.jobs.slice(0, 8).map((j, i) => {
                const failed = j.status ? FAILED.has(j.status) : false;
                return (
                  <li key={i} className="flex items-center gap-2 py-1.5">
                    {failed ? <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-risk" /> : <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-ready" />}
                    <span className="min-w-0 flex-1 truncate" title={j.filename ?? ""}>{j.filename ?? "—"}</span>
                    <span className={`text-xs ${failed ? "text-risk" : "text-muted-foreground"}`}>{j.status}</span>
                    <span className="w-14 text-right text-xs text-muted-foreground">{fmtDur(j.print_duration_s)}</span>
                  </li>
                );
              })}
            </ul>
            {hist.data.totals.total_jobs != null && (
              <p className="text-xs text-muted-foreground">
                {hist.data.totals.total_jobs} prints all-time · {fmtDur(hist.data.totals.total_print_time_s)} printing · longest {fmtDur(hist.data.totals.longest_print_s)}
              </p>
            )}
            <p className="text-[11px] text-muted-foreground">Observed from your printer's own history — read-only.</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
