import { useEffect, useRef, useState } from "react";
import { CheckCircle2, HelpCircle, TriangleAlert } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { settingsReceipt } from "@/api";
import type { ReceiptFact, SettingsReceipt } from "@/api";
import { receiptKey, STATUS_LABEL, statusTone, stepTitle } from "@/lib/settingsReceipt";

/**
 * Settings receipt: what the project asked for, what Studio prepared, what the
 * slicer recorded.
 *
 * Compares a few declared settings across the three files, per tool and in order,
 * and says what to do about each difference. It is about settings only: whether
 * the G-code belongs to the project, whether the profile fits the printer and
 * whether the print will work are separate questions answered elsewhere.
 */
export function SettingsReceiptCard({ original, prepared, sliced, revision = 0, preparedOmitted = false }: {
  original: string; prepared: string | null; sliced: string | null; revision?: number;
  /** A saved job has a prepared copy that is not part of this comparison. */
  preparedOmitted?: boolean;
}) {
  const key = receiptKey(original, prepared, sliced, revision);
  const [answer, setAnswer] = useState<{ key: string; receipt: SettingsReceipt } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
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
  }, [key, original, prepared, sliced]);

  // Only an answer about the files that are open now is shown.
  const receipt = answer && answer.key === key ? answer.receipt : null;

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div>
          <h3 className="text-sm font-semibold">Settings receipt</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            What the project asked for, what Studio prepared, and what the slicer recorded.
          </p>
        </div>

        {preparedOmitted && (
          <p className="text-xs text-muted-foreground" data-testid="receipt-prepared-omitted">
            This job has a saved prepared copy that was not reopened, so this compares the project with the slice
            directly. It cannot show whether the prepared copy changed anything.
          </p>
        )}

        {!receipt && failed !== key && <p className="text-xs text-muted-foreground">Comparing…</p>}
        {failed === key && (
          <p className="text-xs text-risk">Studio could not compare these files. Check that they are still where they were.</p>
        )}

        {receipt && (
          <>
            <p className="text-sm">{receipt.summary}</p>
            <ul className="flex flex-col gap-2">
              {receipt.facts.map((fact) => <FactRow key={fact.id} fact={fact} />)}
            </ul>
            <p className="text-[11px] text-muted-foreground">{receipt.scope_note}</p>
            <p className="text-[11px] text-muted-foreground">{receipt.separate_from}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function FactRow({ fact }: { fact: ReceiptFact }) {
  const tone = statusTone(fact.status);
  const Icon = tone === "ok" ? CheckCircle2 : tone === "attention" ? TriangleAlert : HelpCircle;
  const border = tone === "ok" ? "border-ready/40" : tone === "attention" ? "border-risk/40" : "border-border";
  return (
    <li className={`rounded-md border ${border} p-2.5`}>
      <p className="flex items-center gap-1.5 text-sm font-medium">
        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span>{fact.label}</span>
        <span className="ml-auto text-xs font-normal text-muted-foreground">{STATUS_LABEL[fact.status]}</span>
      </p>
      <ul className="mt-1 space-y-1.5">
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
