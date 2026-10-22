import { useEffect, useRef, useState } from "react";
import { CheckCircle2, HelpCircle, TriangleAlert } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { settingsReceipt } from "@/api";
import type { ReceiptFact, ReceiptStage, SettingsReceipt } from "@/api";
import { receiptKey, STAGE_LABEL, STATUS_LABEL, stageCell, statusTone, stepTitle } from "@/lib/settingsReceipt";

const STAGES: ReceiptStage[] = ["original", "prepared", "sliced"];

/**
 * Settings receipt: the project's, the prepared copy's and the slice's declared values, side by side.
 *
 * Compares a few declared settings across the three files, per tool and in order,
 * and says what to do about each difference. It is about settings only: whether
 * the G-code belongs to the project, whether the profile fits the printer and
 * whether the print will work are separate questions answered elsewhere.
 */
export function SettingsReceiptCard({ original, prepared, sliced, revision = 0, preparedOmitted = false, preparing = false }: {
  original: string; prepared: string | null; sliced: string | null; revision?: number;
  /** A saved job has a prepared copy that is not part of this comparison. */
  preparedOmitted?: boolean;
  /** A new prepared copy is being made; it joins the comparison once Studio has checked it. */
  preparing?: boolean;
}) {
  const key = receiptKey(original, prepared, sliced, revision);
  const [answer, setAnswer] = useState<{ key: string; receipt: SettingsReceipt } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const current = useRef(key);
  current.current = key;

  useEffect(() => {
    let alive = true;
    setFailed(null);
    settingsReceipt(original, prepared, sliced).then(
      (receipt) => { if (alive && current.current === key) setAnswer({ key, receipt }); },
      () => { if (alive && current.current === key) setFailed(key); },
    );
    return () => { alive = false; };
  }, [key, original, prepared, sliced, attempt]);

  // Only an answer about the files that are open now is shown.
  const receipt = answer && answer.key === key ? answer.receipt : null;

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div>
          <h3 className="text-sm font-semibold">Settings receipt</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            The declared values in the project, the prepared copy and the sliced G-code, side by side.
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground" data-testid="receipt-scope">
            {receipt ? receipt.scope_note : "Compared as whole-project settings; per-plate and per-object overrides are not compared."}
          </p>
        </div>

        {preparing && (
          <p className="text-xs text-muted-foreground" data-testid="receipt-preparing">
            A new prepared copy is being made. It joins this comparison once Studio has checked it.
          </p>
        )}
        {preparedOmitted && !preparing && (
          <p className="text-xs text-muted-foreground" data-testid="receipt-prepared-omitted">
            This job has a saved prepared copy that was not reopened, so this compares the project with the slice
            directly. It cannot show whether the prepared copy changed anything.
          </p>
        )}

        {!receipt && failed !== key && <p className="text-xs text-muted-foreground" role="status">Comparing…</p>}
        {failed === key && (
          <div className="flex flex-wrap items-center gap-3" role="alert">
            <p className="text-xs text-risk">Studio could not compare these files. Check that they are still where they were.</p>
            <Button size="sm" variant="secondary" onClick={() => setAttempt((n) => n + 1)}>Try again</Button>
          </div>
        )}

        {receipt && (
          <>
            <p className="text-sm font-medium">{receipt.summary}</p>
            <ul className="flex flex-col gap-3">
              {receipt.facts.map((fact) => <FactRow key={fact.id} fact={fact} receipt={receipt} />)}
            </ul>
            <p className="text-[11px] text-muted-foreground">{receipt.separate_from}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Cell({ receipt, fact, stage }: { receipt: SettingsReceipt; fact: ReceiptFact; stage: ReceiptStage }) {
  const cell = stageCell(receipt, fact, stage);
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{STAGE_LABEL[stage]}</dt>
      <dd className="mt-0.5 text-sm">
        {cell.kind === "value" && cell.lines.map((line) => <span key={line} className="block break-words">{line}</span>)}
        {cell.kind === "not_stated" && <span className="text-muted-foreground">Not stated</span>}
        {cell.kind === "not_checked" && <span className="text-muted-foreground">Not checked</span>}
        {cell.kind === "not_included" && <span className="text-muted-foreground">Not included</span>}
      </dd>
    </div>
  );
}

function FactRow({ fact, receipt }: { fact: ReceiptFact; receipt: SettingsReceipt }) {
  const tone = statusTone(fact.status);
  const Icon = tone === "ok" ? CheckCircle2 : tone === "attention" ? TriangleAlert : HelpCircle;
  const border = tone === "ok" ? "border-ready/40" : tone === "attention" ? "border-risk/40" : "border-border";
  return (
    <li className={`rounded-md border ${border} p-3`}>
      <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span>{fact.label}</span>
        <span className="ml-auto text-xs font-normal text-muted-foreground">{STATUS_LABEL[fact.status]}</span>
      </p>
      <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
        {STAGES.map((stage) => <Cell key={stage} receipt={receipt} fact={fact} stage={stage} />)}
      </dl>
      <ul className="mt-2 space-y-1.5 border-t border-border pt-2">
        {fact.steps.map((step) => (
          <li key={`${step.from}-${step.to}`} className="text-xs">
            <span className="font-medium">{stepTitle(step.from, step.to)}</span>{" "}
            <span className="text-muted-foreground">· {STATUS_LABEL[step.status]}</span>
            <p className="mt-0.5 text-muted-foreground">{step.detail}</p>
            {step.next_action && <p className="mt-0.5">→ {step.next_action}</p>}
          </li>
        ))}
        {fact.steps.length === 0 && <li className="text-xs text-muted-foreground">Open a sliced G-code to compare.</li>}
      </ul>
    </li>
  );
}
