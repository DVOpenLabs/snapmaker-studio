import { Link } from "react-router-dom";
import { AlertTriangle, Check, Circle, CircleDot, Download, FileCheck2, Loader2, Rocket, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useOrca } from "@/hooks/useOrca";
import { ORCA_RELEASES_URL } from "@/lib/orca";
import type { Journey, StageId, StageState } from "@/lib/journey";

const MARK: Record<StageState, typeof Check> = {
  done: Check, review: AlertTriangle, current: CircleDot, todo: Circle, blocked: XCircle, error: XCircle,
};
const TONE: Record<StageState, string> = {
  done: "text-ready", review: "text-risk", error: "text-risk", blocked: "text-risk",
  current: "text-primary", todo: "text-muted-foreground",
};

/**
 * The job at a glance, in one compact bar: which file, which plate, where it is in the journey, and the
 * single thing to do next. Everything is derived; nothing here keeps its own state.
 */
export function JobBar({ name, path, ext, plates, journey, onView, preparedPath, busy, actions }: {
  name: string; path: string; ext: string;
  /** "1 plate" / "3 plates", or null while it is not known. */
  plates: string | null;
  journey: Journey;
  onView: (id: StageId) => void;
  preparedPath: string | null;
  busy: boolean;
  actions: { create: () => void; reviewMaterials: () => void; compare: () => void; recheck: () => void };
}) {
  const { primary } = journey;
  return (
    <header aria-labelledby="job-title" className="flex flex-col gap-3 border-b border-border pb-3">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <FileCheck2 className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
          <div className="min-w-0">
            <h2 id="job-title" className="truncate text-base font-semibold leading-tight" title={path}>{name}</h2>
            <p className="text-xs text-muted-foreground">
              {ext ? ext.toUpperCase() : "Model"}{plates ? ` · ${plates}` : ""}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="ghost" size="sm"><Link to="/compatibility">Full checks</Link></Button>
          <PrimaryAction primary={primary} busy={busy} preparedPath={preparedPath} actions={actions} />
        </div>
      </div>
      {primary.disabledReason && !busy && (
        <p className="text-xs text-muted-foreground" role="status" data-testid="primary-reason">{primary.disabledReason}</p>
      )}
      <ol aria-label="Job progress" className="flex flex-wrap gap-x-1 gap-y-1">
        {journey.stages.map((stage, i) => {
          const Icon = MARK[stage.state];
          const shown = stage.id === journey.current;
          return (
            <li key={stage.id} aria-current={stage.id === journey.current ? "step" : undefined} className="flex items-center">
              {i > 0 && <span aria-hidden="true" className="mr-1 h-px w-4 bg-border" />}
              <button type="button" onClick={() => onView(stage.id)}
                className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${shown ? "bg-muted font-medium" : "hover:bg-muted/60"} ${TONE[stage.state]}`}>
                <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                <span className={stage.state === "todo" ? "text-muted-foreground" : "text-foreground"}>{stage.label}</span>
                <span className="sr-only">, {stage.status}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </header>
  );
}

function PrimaryAction({ primary, busy, preparedPath, actions }: {
  primary: Journey["primary"]; busy: boolean; preparedPath: string | null;
  actions: { create: () => void; reviewMaterials: () => void; compare: () => void; recheck: () => void };
}) {
  if (primary.kind === "open-orca" && preparedPath) return <OrcaButton path={preparedPath} />;
  if (primary.kind === "none") {
    return primary.disabledReason
      ? <Button disabled>{primary.label}</Button>
      : null;
  }
  const onClick = primary.kind === "create" ? actions.create
    : primary.kind === "review-materials" ? actions.reviewMaterials
    : primary.kind === "compare" ? actions.compare
    : actions.recheck;
  const disabled = !!primary.disabledReason;
  return (
    <Button onClick={onClick} disabled={disabled} data-primary={primary.kind}>
      {busy && primary.kind === "create" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
      {primary.label}
    </Button>
  );
}

/** The one-way handoff, as the primary action once the copy exists. */
function OrcaButton({ path }: { path: string }) {
  const { state, opening, open } = useOrca(path);
  if (state === "detecting") return <Button disabled><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Checking for Orca…</Button>;
  if (state === "missing") {
    return (
      <Button asChild variant="secondary">
        <a href={ORCA_RELEASES_URL} target="_blank" rel="noreferrer"><Download className="h-4 w-4" aria-hidden="true" /> Install Snapmaker Orca</a>
      </Button>
    );
  }
  return (
    <Button onClick={open} disabled={opening} data-primary="open-orca">
      {opening ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Rocket className="h-4 w-4" aria-hidden="true" />}
      {opening ? "Opening…" : "Open in Orca"}
    </Button>
  );
}
