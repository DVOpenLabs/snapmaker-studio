import { useEffect, useState } from "react";
import {
  AlertOctagon, AlertTriangle, CheckCircle2, HelpCircle, ListOrdered, Loader2, Package, Upload,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { materialPlan, printerUploadGcode, printPlan, sendCheck } from "@/api";
import type { MaterialPlan, PrintPlan, SendCheck, SendItem, UploadResult } from "@/api";
import { ProvenanceNote } from "@/components/ProvenanceNote";
import ProviderStatusNote from "@/components/ProviderStatusNote";
import { usePrinter } from "@/store/printer";
import { providerArgs, useProvider } from "@/store/provider";
import {
  MATERIALS_SUBTITLE, MATERIALS_TITLE, PLAN_SUBTITLE, PLAN_TITLE, SEND_TITLE,
  changeCount, itemLabel, itemsOfKind, materialsHeadline, orderedSlots, planHeadline,
  planIsTruncated, planLines, readAt, sendHeadline, sendTone, shouldDiscourageSend, slotLabel,
  slotTone, uploadTitle, uploadTone,
} from "@/lib/sendPlan";

/**
 * "Ready to send?" — the last thing Studio says before a person presses a button.
 *
 * Three buckets kept apart on purpose. A blocker is a provable mismatch, a
 * warning is a real concern that is not proof, and an unknown is something
 * Studio cannot verify. Collapsing them would be the easiest way to make this
 * card feel decisive and be wrong.
 *
 * Nothing here sends anything.
 */
export function SendReadyCard({ path, projectPath }: { path: string; projectPath?: string }) {
  const host = usePrinter((s) => s.host);
  // Whatever tracks the user's filament, if anything. Without it every question
  // about how much is left comes back unknown, which is the honest answer and
  // exactly what happened before this was wired up.
  const provider = useProvider();
  const args = providerArgs(provider);
  const argsKey = JSON.stringify(args);
  const [check, setCheck] = useState<SendCheck | null>(null);

  useEffect(() => {
    let alive = true;
    setCheck(null);
    sendCheck(path, host, 7125, true, projectPath, args).then(
      (r) => { if (alive) setCheck(r); },
      () => { /* the post-slice card already reports an unreadable file */ },
    );
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, host, projectPath, argsKey]);

  const tone = sendTone(check?.verdict);
  const Icon = tone === "ready" ? CheckCircle2
    : tone === "risk" ? AlertOctagon
    : tone === "warn" ? AlertTriangle : HelpCircle;
  const iconClass = tone === "ready" ? "text-ready"
    : tone === "risk" ? "text-risk"
    : tone === "warn" ? "text-risk" : "text-muted-foreground";

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          {check ? <Icon className={`h-4 w-4 ${iconClass}`} aria-hidden="true" />
                 : <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
          {SEND_TITLE}
        </h3>

        <p className="text-sm text-muted-foreground">{sendHeadline(check)}</p>
        <ProviderStatusNote status={check?.provider_status} />
        {check?.printer?.observed_at ? (
          <p className="text-[11px] text-muted-foreground">{readAt(check.printer.observed_at)}</p>
        ) : null}

        {check?.available && (
          <>
            {(["blocker", "warning", "unknown"] as SendItem["kind"][]).map((kind) => {
              const items = itemsOfKind(check, kind);
              if (!items.length) return null;
              return (
                <ul key={kind} className="flex flex-col gap-2">
                  {items.map((item) => (
                    <li
                      key={`${kind}-${item.title}`}
                      className={`rounded-md border p-2.5 ${
                        kind === "blocker" ? "border-risk/50"
                        : kind === "warning" ? "border-risk/25" : "border-border"}`}
                    >
                      <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
                        {item.title}
                        <span className="rounded-full bg-muted px-1.5 py-px text-[10px] uppercase tracking-wide text-muted-foreground">
                          {itemLabel(kind)}
                        </span>
                      </p>
                      {item.detail && (
                        <p className="mt-1 text-xs text-muted-foreground">{item.detail}</p>
                      )}
                      {item.action && (
                        <p className="mt-1 text-xs">
                          <span className="font-medium">Do this:</span>{" "}
                          <span className="text-muted-foreground">{item.action}</span>
                        </p>
                      )}
                      {item.source && (
                        // The same answer, one level deeper: what this was read
                        // from. A beginner never opens it; an expert who doubts
                        // the verdict should not have to ask.
                        <details className="mt-1">
                          <summary className="cursor-pointer text-[11px] text-muted-foreground hover:text-foreground">
                            Where this came from
                          </summary>
                          <p className="mt-0.5 text-[11px] text-muted-foreground">{item.source}</p>
                        </details>
                      )}
                    </li>
                  ))}
                </ul>
              );
            })}

            {shouldDiscourageSend(check) && (
              <p className="rounded-md border border-risk/50 bg-risk/5 p-2.5 text-xs">
                Studio will not stop you — it is your printer. But sending this now
                spends the upload on a job that will not finish.
              </p>
            )}

            {check.provenance ? <ProvenanceNote result={check.provenance} /> : (
              // Without a project open there is nothing to compare this job to,
              // and silence reads as "fine". Someone who opened the wrong file
              // gets no other prompt than this one.
              <p className="rounded-md border border-border p-2.5 text-xs text-muted-foreground">
                No project is open, so Studio cannot tell you whether this is the slice of
                the model you checked. Open the project first and the two are compared.
              </p>
            )}

            <SendToPrinter path={path} check={check} projectPath={projectPath}
                           onRechecked={setCheck} />

            <p className="text-[11px] text-muted-foreground">{check.disclaimer}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Sending, against the checks that are on the screen and not against the ones
 * that were true when the page was drawn.
 *
 * The gap this closes is small and completely invisible: a person reads the
 * checks, walks to the printer, comes back and presses send. A slot can have
 * emptied, a spool changed, another print started, or the job been re-sliced to
 * the same filename in between — and nothing on screen would look any different.
 *
 * So the fingerprint of what was checked goes with the upload. If the engine
 * finds the world has moved, nothing is uploaded: what changed is named, the
 * fresh answer replaces the stale one, and the decision is put back to the person
 * who has to live with it. Studio uploads a file; it never starts a print.
 */
function SendToPrinter({ path, check, projectPath, onRechecked }: {
  path: string; check: SendCheck; projectPath?: string;
  onRechecked: (check: SendCheck) => void;
}) {
  const host = usePrinter((s) => s.host);
  // The upload re-runs the send check server-side and refuses if anything moved.
  // It has to re-run it against the same provider the user was shown, or it
  // would be comparing against a different set of facts than the one on screen.
  const args = providerArgs(useProvider());
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);

  useEffect(() => { setResult(null); }, [path, check.state?.token]);

  if (!host) {
    return (
      <p className="text-xs text-muted-foreground">
        Connect your U1 in Printer Hub to send this job to it.
      </p>
    );
  }

  // A printer Studio cannot reach cannot be sent to, and offering the button
  // anyway teaches people that pressing it does nothing.
  if (check.printer_reachable === false) {
    return (
      <p className="text-xs text-muted-foreground">
        Studio cannot reach your printer at the moment, so this job cannot be sent to it.
        Check it is on and on the same network, then look again in Printer Hub.
      </p>
    );
  }

  async function send() {
    setBusy(true);
    try {
      const sent = await printerUploadGcode(host!, path, 7125, check.state, projectPath, args);
      setResult(sent);
      // A refusal comes back with the answer that replaced the stale one, so the
      // page a person is looking at is the page they are deciding from.
      if (sent.state === "changed" && sent.check) onRechecked(sent.check);
    } catch (error) {
      setResult({
        ok: false, state: "not_accepted", uploaded: false,
        detail: error instanceof Error ? error.message
          : "Studio could not reach the printer. Nothing has been started.",
      } as UploadResult);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant={check.verdict === "blocker" ? "secondary" : "primary"}
                disabled={busy} onClick={send}>
          {busy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                : <Upload className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />}
          Send this job to the printer
        </Button>
        <span className="text-[11px] text-muted-foreground">
          Uploads the file. It does not start a print.
        </span>
      </div>
      {result && <UploadOutcome result={result} />}
    </div>
  );
}

function UploadOutcome({ result }: { result: UploadResult }) {
  const tone = uploadTone(result.state);
  const border = tone === "ready" ? "border-ready/40"
    : tone === "risk" ? "border-risk/50" : "border-border";
  return (
    <div className={`rounded-md border ${border} p-2.5`}>
      <p className="text-sm font-medium">{uploadTitle(result.state)}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {result.detail ?? result.confirmation?.detail ?? ""}
      </p>
      {result.changed?.length ? (
        <ul className="mt-1.5 flex flex-col gap-1">
          {result.changed.map((change) => (
            <li key={change.part} className="text-xs">
              <span className="font-medium">{change.title}.</span>{" "}
              <span className="text-muted-foreground">{change.detail}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {result.state === "changed" && (
        <p className="mt-1.5 text-xs text-muted-foreground">
          The checks above have been read again. Look at them, then send again if you
          still want to.
        </p>
      )}
    </div>
  );
}

/** What to load, slot by slot. An intelligence layer over spool state, not an inventory. */
export function MaterialPlanCard({ path }: { path: string }) {
  const host = usePrinter((s) => s.host);
  const provider = useProvider();
  const args = providerArgs(provider);
  const argsKey = JSON.stringify(args);
  const [plan, setPlan] = useState<MaterialPlan | null>(null);

  useEffect(() => {
    let alive = true;
    setPlan(null);
    materialPlan(path, host, 7125, args).then(
      (r) => { if (alive) setPlan(r); },
      () => { /* silent: the send card already carries the important half */ },
    );
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, host, argsKey]);

  const changes = changeCount(plan);

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            {plan ? <Package className={`h-4 w-4 ${changes ? "text-risk" : "text-ready"}`} aria-hidden="true" />
                  : <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
            {MATERIALS_TITLE}
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{MATERIALS_SUBTITLE}</p>
        </div>

        <p className="text-sm text-muted-foreground">{materialsHeadline(plan)}</p>

        {plan?.available && (
          <ul className="flex flex-col gap-2">
            {orderedSlots(plan).map((slot) => {
              const tone = slotTone(slot.state);
              const border = tone === "ready" ? "border-ready/40"
                : tone === "risk" ? "border-risk/40" : "border-border";
              return (
                <li key={slot.tool} className={`rounded-md border ${border} p-2.5`}>
                  <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
                    <span className="capitalize">{slot.label}</span>
                    <span className="rounded-full bg-muted px-1.5 py-px text-[10px] uppercase tracking-wide text-muted-foreground">
                      {slotLabel(slot.state)}
                    </span>
                    {slot.wants_colour && (
                      <span
                        className="inline-block h-3 w-3 rounded-full border border-border"
                        style={{ backgroundColor: slot.wants_colour }}
                        aria-label={`the job expects ${slot.wants_colour}`}
                      />
                    )}
                    {slot.has_colour && slot.has_colour !== slot.wants_colour && (
                      <span
                        className="inline-block h-3 w-3 rounded-full border border-border"
                        style={{ backgroundColor: slot.has_colour }}
                        aria-label={`${slot.has_colour} is loaded`}
                      />
                    )}
                  </p>
                  {slot.detail && (
                    <p className="mt-1 text-xs text-muted-foreground">{slot.detail}</p>
                  )}
                  {slot.action && (
                    <p className="mt-1 text-xs">
                      <span className="font-medium">Do this:</span>{" "}
                      <span className="text-muted-foreground">{slot.action}</span>
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * The print, in order.
 *
 * Loaded on request: it costs a full pass over the file, which on a 300 MB job is
 * seconds rather than milliseconds. Everything else on the page answers instantly
 * and should not wait for this.
 */
export function PrintPlanCard({ path }: { path: string }) {
  const [plan, setPlan] = useState<PrintPlan | null>(null);
  const [asked, setAsked] = useState(false);

  useEffect(() => { setPlan(null); setAsked(false); }, [path]);

  const lines = planLines(plan);

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            {asked && !plan
              ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              : <ListOrdered className="h-4 w-4" aria-hidden="true" />}
            {PLAN_TITLE}
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{PLAN_SUBTITLE}</p>
        </div>

        {!asked && (
          <Button
            variant="secondary"
            onClick={() => {
              setAsked(true);
              printPlan(path).then(setPlan, () => setPlan(null));
            }}
          >
            Read the whole job
          </Button>
        )}

        {asked && <p className="text-sm text-muted-foreground">{planHeadline(plan)}</p>}

        {lines.length > 0 && (
          <ol className="flex flex-col gap-1.5">
            {lines.map((line, index) => (
              <li key={`${line.at}-${index}`} className="rounded-md border border-border p-2.5">
                <p className="text-sm">
                  <span className="font-medium">{line.at}</span>
                  <span className="text-muted-foreground"> — {line.text}</span>
                </p>
                <details className="mt-1">
                  <summary className="cursor-pointer text-[11px] text-muted-foreground hover:text-foreground">
                    Evidence
                  </summary>
                  <p className="mt-1 text-[11px] text-muted-foreground">{line.evidence}</p>
                </details>
              </li>
            ))}
          </ol>
        )}

        {planIsTruncated(plan) && (
          <p className="text-[11px] text-muted-foreground">
            This job has more events than Studio keeps in one report, so the list above
            stops early rather than pretending to be complete.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
