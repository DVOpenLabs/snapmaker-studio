import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CapabilityStateName, SetupEntry, SetupReport } from "@/lib/setupsTypes";

const STATE_LABEL: Record<CapabilityStateName, string> = {
  available: "Available", unavailable: "Unavailable", stale: "Stale", unknown: "Unknown",
};
const STATE_CLASS: Record<CapabilityStateName, string> = {
  available: "bg-ready/10 text-ready", unavailable: "bg-risk/10 text-risk",
  stale: "bg-repairable/10 text-repairable", unknown: "bg-muted text-muted-foreground",
};

function EntryCard({ entry }: { entry: SetupEntry }) {
  const heads = entry.counts?.physical_heads;
  // An empty slot list can mean "never read", so the count only shows when the capability says it was read.
  const slotState = entry.capabilities.find((c) => c.key === "logical_slots")?.state;
  const slotsKnown = slotState === "available" || slotState === "stale";
  return (
    <Card>
      <CardHeader>
        <CardTitle>{entry.label}{entry.kind ? ` (${entry.kind}${entry.variant ? `, ${entry.variant}` : ""})` : ""}</CardTitle>
        {entry.reason_text && <p className="mt-1 text-sm text-muted-foreground" role="status">{entry.reason_text}</p>}
      </CardHeader>
      <CardContent className="space-y-3">
        {entry.counts && (
          <p className="text-sm" data-testid="counts">
            Physical heads: {heads === null || heads === undefined ? "not reported" : heads}. Logical slots: {slotsKnown ? entry.counts.logical_slots : "not reported"}.
          </p>
        )}
        <ul className="space-y-1.5" aria-label="What was read">
          {entry.capabilities.map((c) => (
            <li key={c.key} className="flex flex-wrap items-start gap-2 text-sm">
              <Badge className={STATE_CLASS[c.state]}>{STATE_LABEL[c.state]}</Badge>
              {c.historical && <Badge>Historical</Badge>}
              <span className="font-medium">{c.label}</span>
              <span className="text-muted-foreground">{c.reason}</span>
            </li>
          ))}
        </ul>
        {entry.assignability && (
          <p className="rounded-md border border-border p-3 text-sm" data-testid="verdict">{entry.assignability.text}</p>
        )}
      </CardContent>
    </Card>
  );
}

/** Pure presentation of a setup report. No state, no network, no storage. */
export default function SetupReportView({ report }: { report: SetupReport }) {
  const legacy = report.legacy_limitation;
  return (
    <div className="space-y-4">
      {legacy.applies && legacy.text && (
        <div className="rounded-md border border-border bg-muted p-3 text-sm" role="note" data-testid="legacy-notice">
          <p>{legacy.text}</p>
          <ul className="mt-1 list-disc pl-5 text-muted-foreground">
            {legacy.reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
        </div>
      )}
      {report.entries.map((e, i) => <EntryCard key={`${e.label}-${i}`} entry={e} />)}
      <p className="text-xs text-muted-foreground">{report.advisory}</p>
    </div>
  );
}
