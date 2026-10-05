import { CheckCircle2, RefreshCw, Wand2, AlertTriangle, HelpCircle, FileWarning } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReadyNowProject } from "@/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  COLOUR_NOTE, groupResults, confidenceLabel, rowChips, rowStatus, rowActions,
  type ReadyNowIcon, type ReadyNowSection,
} from "@/lib/readyNow";

const ICONS: Record<ReadyNowIcon, LucideIcon> = {
  check: CheckCircle2, swap: RefreshCw, prepare: Wand2, attention: AlertTriangle, unknown: HelpCircle,
};

/** One project. Meaning is carried by words (status line, chips), never by colour alone. */
export function ReadyNowRow({ r, onOpen, onPrepare }: {
  r: ReadyNowProject; onOpen: (r: ReadyNowProject) => void; onPrepare: (r: ReadyNowProject) => void;
}) {
  const chips = rowChips(r);
  const actions = rowActions(r);
  return (
    <li className="space-y-2 rounded-md border border-border p-3" aria-label={`${r.name}: ${rowStatus(r)}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="truncate font-medium" title={r.path}>{r.name}</span>
        <Badge className="border border-border bg-muted text-muted-foreground">
          Confidence: {confidenceLabel(r.confidence)}
        </Badge>
      </div>
      <p className="text-xs font-medium text-muted-foreground">{rowStatus(r)}</p>
      {r.colour_notes.length > 0 && (
        <div role="note" className="rounded-md border border-border bg-muted/50 p-2 text-sm font-medium">
          <p>{COLOUR_NOTE}</p>
          {r.colour_notes.map((n) => <p key={n} className="text-xs font-normal text-muted-foreground">{n}</p>)}
        </div>
      )}
      {/* The colour sentence above already states the reason for a colour-only match. */}
      {r.colour_notes.length === 0 && <p className="text-sm">{r.top_reason}</p>}
      {r.top_action && <p className="text-sm text-muted-foreground">Next: {r.top_action}</p>}
      {chips.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Notes">
          {chips.map((c) => (
            <li key={c.id}>
              <Badge className={cn("border", c.tone === "caution"
                ? "border-border bg-muted font-semibold" : "border-border bg-muted/60")}>
                {c.label}
              </Badge>
            </li>
          ))}
        </ul>
      )}
      {r.unknowns.length > 0 && (
        <div className="text-xs text-muted-foreground">
          <p className="font-medium">Studio can't tell</p>
          <ul className="list-disc pl-4">
            {r.unknowns.map((u) => <li key={u}>{u}</li>)}
          </ul>
        </div>
      )}
      {r.file_state !== "ok" && (
        <p className="flex items-center gap-1 text-xs text-muted-foreground">
          <FileWarning className="h-3.5 w-3.5" aria-hidden="true" />
          {r.file_state === "missing" ? "File not found" : "File could not be read"}
        </p>
      )}
      {actions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {actions.map((a) => (
            <Button key={a.id} size="sm" variant={a.id === "prepare" ? "primary" : "secondary"}
              onClick={() => (a.id === "open" ? onOpen(r) : onPrepare(r))}>
              {a.label}
            </Button>
          ))}
        </div>
      )}
    </li>
  );
}

export function ReadyNowSectionView({ s, onOpen, onPrepare }: {
  s: ReadyNowSection; onOpen: (r: ReadyNowProject) => void; onPrepare: (r: ReadyNowProject) => void;
}) {
  const Icon = ICONS[s.icon];
  return (
    <section aria-labelledby={`rn-${s.bucket}`} className="space-y-2">
      <div>
        <h3 id={`rn-${s.bucket}`} className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <Icon className="h-4 w-4" aria-hidden="true" /> {s.label} ({s.items.length})
        </h3>
        <p className="text-xs text-muted-foreground">{s.blurb}</p>
      </div>
      <Card>
        <CardContent className="p-3">
          <ul className="space-y-2">
            {s.items.map((r) => <ReadyNowRow key={r.path} r={r} onOpen={onOpen} onPrepare={onPrepare} />)}
          </ul>
        </CardContent>
      </Card>
    </section>
  );
}

/** The five buckets in display order; a bucket with nothing in it is not drawn. */
export function ReadyNowSections({ results, onOpen, onPrepare }: {
  results: ReadyNowProject[]; onOpen: (r: ReadyNowProject) => void; onPrepare: (r: ReadyNowProject) => void;
}) {
  return (
    <div className="space-y-6">
      {groupResults(results).filter((s) => s.items.length > 0).map((s) => (
        <ReadyNowSectionView key={s.bucket} s={s} onOpen={onOpen} onPrepare={onPrepare} />
      ))}
    </div>
  );
}
