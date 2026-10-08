import { useEffect, useRef, useState } from "react";
import { Play, Pause, X, Upload, OctagonAlert, Loader2, AlertTriangle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  printerPause, printerResume, printerCancel, printerStartPrint, printerEmergencyStop,
  printerUploadGcode, openGcodeDialog,
} from "@/api";
import {
  availableActions, needsConfirm, confirmCopy, confirmStillValid, actionName,
  type PrintState, type ControlAction, type PendingConfirm,
} from "@/lib/printerControl";

// Printer Hub Phase B — safe, user-controlled actions. Every start / cancel /
// emergency-stop is confirmed in-app before it reaches the printer. Studio does not
// auto-start anything. Pause/resume are reversible and are sent without a second prompt.
//
// A confirmation is about one printer, one action and (for Start) one file, fixed at the moment the
// prompt opens. It is withdrawn if the connected printer changes, stops answering, or can no longer
// take that action. Confirming sends exactly that request, once.
export function PrinterControls({
  host, printState, online, onChanged,
}: {
  host: string | null;
  printState: PrintState;
  online: boolean;
  onChanged: () => void;
}) {
  const [pending, setPending] = useState<PendingConfirm | null>(null);
  const [busy, setBusy] = useState<ControlAction | "upload" | null>(null);
  // Messages and the uploaded file are kept with the printer they belong to, and shown only for it.
  const [error, setError] = useState<{ host: string; message: string } | null>(null);
  const [notice, setNotice] = useState<{ host: string; message: string } | null>(null);
  const [uploaded, setUploaded] = useState<{ host: string; filename: string } | null>(null);
  const nextId = useRef(0);
  // Set before the first await so a second click in the same instant cannot send a second request.
  const inFlight = useRef(false);
  const opener = useRef<HTMLElement | null>(null);
  const heading = useRef<HTMLParagraphElement>(null);

  // Withdraw a confirmation the moment it stops being about the printer the user is looking at.
  useEffect(() => {
    if (!pending || confirmStillValid(pending, { host, online, printState })) return;
    setPending(null);
    if (inFlight.current) {
      setNotice({
        host: pending.host,
        message: `${actionName(pending.action)} was already sent to ${pending.host} before this changed. Check that printer's status.`,
      });
    }
  }, [pending, host, online, printState]);

  if (!host) return null;
  const actions = availableActions(printState, online);

  async function call(fn: () => Promise<unknown>, tag: ControlAction | "upload", forHost: string, confirmed?: PendingConfirm) {
    if (inFlight.current) return;
    inFlight.current = true;
    setError(null); setNotice(null); setBusy(tag);
    try { await fn(); onChanged(); }
    catch (e) {
      setError({ host: forHost, message: e instanceof Error ? e.message : "the printer didn't accept that — check it's on and reachable" });
    } finally {
      inFlight.current = false;
      setBusy(null);
      // Only close the prompt this request belongs to, never a newer one.
      if (confirmed) setPending((cur) => (cur?.id === confirmed.id ? null : cur));
    }
  }

  function run(action: ControlAction, filename?: string) {
    if (needsConfirm(action)) {
      opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setPending({ id: ++nextId.current, action, host: host!, filename });
      return;
    }
    const h = host!;
    if (action === "pause") return call(() => printerPause(h), "pause", h);
    if (action === "resume") return call(() => printerResume(h), "resume", h);
  }

  function doConfirmed() {
    const p = pending;
    if (!p || inFlight.current) return;
    // Checked again at the last moment, in case the state changed since the last render.
    if (!confirmStillValid(p, { host, online, printState })) { setPending(null); return; }
    if (p.action === "cancel") return call(() => printerCancel(p.host), "cancel", p.host, p);
    if (p.action === "emergency_stop") return call(() => printerEmergencyStop(p.host), "emergency_stop", p.host, p);
    if (p.action === "start") return call(() => printerStartPrint(p.host, p.filename ?? ""), "start", p.host, p);
  }

  async function pickAndUpload() {
    const h = host!;
    const path = await openGcodeDialog();
    if (!path || inFlight.current) return;
    inFlight.current = true;
    setError(null); setNotice(null); setBusy("upload");
    try {
      const r = await printerUploadGcode(h, path);
      // Remember which printer received it, so Start is only offered for that printer.
      setUploaded(r.filename ? { host: h, filename: r.filename } : null);
      onChanged();
    } catch (e) {
      setError({ host: h, message: e instanceof Error ? e.message : "upload failed — check the printer is reachable" });
    } finally { inFlight.current = false; setBusy(null); }
  }

  const spin = (t: ControlAction | "upload") => busy === t ? <Loader2 className="h-4 w-4 animate-spin" /> : null;
  const uploadedHere = uploaded && uploaded.host === host ? uploaded.filename : null;
  const errorHere = error && error.host === host ? error.message : null;
  const noticeHere = notice && notice.host === host ? notice.message : null;
  // Where focus goes when the prompt closes: the control that opened it, or the card heading if that control is gone.
  const returnFocusTo = () => {
    const o = opener.current;
    if (o && o.isConnected && !(o as HTMLButtonElement).disabled) return o;
    return heading.current;
  };

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <p ref={heading} tabIndex={-1} className="text-sm font-semibold outline-none">Printer controls</p>
        {!online ? (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <AlertTriangle className="h-4 w-4" /> Controls are off until the printer is connected and reachable.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              {actions.includes("pause") && (
                <Button size="sm" variant="secondary" disabled={!!busy} onClick={() => run("pause")}>
                  {spin("pause") ?? <Pause className="h-4 w-4" />} Pause
                </Button>
              )}
              {actions.includes("resume") && (
                <Button size="sm" disabled={!!busy} onClick={() => run("resume")}>
                  {spin("resume") ?? <Play className="h-4 w-4" />} Resume
                </Button>
              )}
              {actions.includes("cancel") && (
                <Button size="sm" variant="danger" disabled={!!busy} onClick={() => run("cancel")}>
                  <X className="h-4 w-4" /> Cancel print
                </Button>
              )}
              {actions.includes("start") && (
                <Button size="sm" variant="secondary" disabled={!!busy} onClick={pickAndUpload}>
                  {spin("upload") ?? <Upload className="h-4 w-4" />} Upload sliced gcode
                </Button>
              )}
            </div>

            {/* Close the loop: after uploading exported gcode, offer to start it (confirmed). */}
            {uploadedHere && actions.includes("start") && (
              <div className="flex flex-wrap items-center gap-2 rounded-md border border-border p-2 text-xs">
                <span className="text-muted-foreground">Uploaded <span className="font-medium text-foreground">{uploadedHere}</span>.</span>
                <Button size="sm" disabled={!!busy} onClick={() => run("start", uploadedHere)}>
                  <Play className="h-4 w-4" /> Start this print
                </Button>
              </div>
            )}

            <p className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              Only start if the bed is clear and loaded — Studio doesn't inspect it for you.
            </p>

            <div className="mt-2 rounded-md border border-risk/40 bg-risk/5 p-2">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-risk">Emergency stop</p>
              <p className="mb-2 text-[11px] text-muted-foreground">
                Halts motion/heaters and may require a firmware restart before printing again.
              </p>
              <Button size="sm" variant="danger" disabled={!!busy} onClick={() => run("emergency_stop")}>
                {spin("emergency_stop") ?? <OctagonAlert className="h-4 w-4" />} Emergency stop
              </Button>
            </div>
          </>
        )}

        {errorHere && (
          <p role="alert" className="flex items-start gap-1.5 text-xs text-risk">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {errorHere}
          </p>
        )}
        {noticeHere && (
          <p role="status" className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {noticeHere}
          </p>
        )}

        {pending && (
          <ConfirmDialog
            {...confirmCopy(pending.action, pending.filename)}
            details={[`Printer: ${pending.host}`, ...(pending.filename ? [`File: ${pending.filename}`] : [])]}
            busy={!!busy}
            onCancel={() => setPending(null)}
            onConfirm={doConfirmed}
            returnFocusTo={returnFocusTo}
          />
        )}
      </CardContent>
    </Card>
  );
}
