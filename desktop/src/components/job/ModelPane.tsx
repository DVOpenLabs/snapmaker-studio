import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Info, Loader2, RotateCcw } from "lucide-react";
import { paintedPreview } from "@/api";
import { PlateView } from "@/components/job/PlateView";
import type { usePlacement } from "@/components/PlacementCard";
import type { ViewerLoss } from "@/components/job/ModelViewer";
import {
  beyondHeads, colourOf, coverageClaim, draftColours, legend, percent, unavailableCopy,
  type LegendRow, type PaintedPreview, type PreviewMode,
} from "@/lib/paintedPreview";

const ModelViewer = lazy(() => import("@/components/job/ModelViewer"));

type Fetch = (path: string) => Promise<PaintedPreview>;
type Load = { status: "loading" } | { status: "failed" } | { status: "done"; preview: PaintedPreview };

const LOSS_COPY: Record<ViewerLoss, string> = {
  "no-graphics": "This computer could not start 3D graphics, so the colour preview is not shown.",
  "context-lost": "The graphics were interrupted, so the colour preview stopped.",
  failed: "The colour preview could not be drawn.",
};

const COVERAGE_COPY = {
  painted: "Painted regions are drawn where the project's paint is. Colours name which filament prints where; they are not a picture of the finished print.",
  assigned: "Nothing is painted in this project. Each part is drawn in the filament it is assigned.",
  geometry: "Shape only. This file does not say which filament prints where, so there is no painted coverage to check.",
} as const;

function usePreview(path: string | null, fetcher: Fetch): Load {
  const [state, setState] = useState<Load>({ status: "loading" });
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setState({ status: "loading" });
    fetcher(path).then(
      (preview) => { if (alive) setState({ status: "done", preview }); },
      () => { if (alive) setState({ status: "failed" }); },
    );
    return () => { alive = false; };
  }, [path, fetcher]);
  return state;
}

export interface ModelPaneProps {
  path: string;
  /** What Prepare would be sent (0-based slots). */
  selections: { slot: number; colour: string | null }[];
  /** A copy Studio wrote and validated for this project, if any. */
  preparedPath: string | null;
  placement: ReturnType<typeof usePlacement>;
  fetcher?: Fetch;
}

/**
 * The middle of the job screen: the model drawn by the filament that prints each part, beside what you have
 * chosen, with the plate fit one click away. When the colour preview cannot be built or drawn it says why and
 * shows the plate instead.
 */
export function ModelPane({ path, selections, preparedPath, placement, fetcher = paintedPreview }: ModelPaneProps) {
  const original = usePreview(path, fetcher);
  const written = usePreview(preparedPath, fetcher);
  const [mode, setMode] = useState<PreviewMode>("original");
  const [surface, setSurface] = useState<"colours" | "plate">("colours");
  const [lost, setLost] = useState<ViewerLoss | null>(null);
  const [highlight, setHighlight] = useState<number | null>(null);
  const [resetKey, setResetKey] = useState(0);

  const preview = original.status === "done" && original.preview.available ? original.preview : null;
  const draft = useMemo(() => draftColours(selections), [selections]);
  // The colours of the copy Studio actually wrote, read back from that file.
  const copyColours = useMemo(() => {
    if (!preview || written.status !== "done" || !written.preview.available) return null;
    const out: Record<number, string> = {};
    for (const s of written.preview.slots) if (s.colour) out[s.slot] = s.colour.toUpperCase();
    return Object.keys(out).length > 0 ? out : null;
  }, [preview, written]);

  const hasDraft = !!preview && legend(preview, draft).some((r) => r.changed);
  // A mode that is no longer available falls back to Original rather than showing a stale comparison.
  const effective: PreviewMode = mode === "proposed" && !hasDraft ? "original" : mode === "copy" && !copyColours ? "original" : mode;
  const overrides = effective === "copy" ? copyColours ?? {} : draft;
  const rows = useMemo(() => (preview ? legend(preview, overrides) : []), [preview, overrides]);
  const colourFor = useMemo(() => colourOf(rows, effective === "original" ? "original" : "proposed"), [rows, effective]);
  const onLost = useCallback((why: ViewerLoss) => setLost(why), []);

  const showColours = surface === "colours" && !!preview && !lost;
  const message = original.status === "done" || original.status === "failed"
    ? unavailableCopy(original.status === "done" ? original.preview : null, original.status === "failed")
    : "";

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3" data-testid="model-pane">
      {preview && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div role="group" aria-label="What to show" className="inline-flex rounded-md border border-border p-0.5 text-xs">
            <Seg on={surface === "colours"} onClick={() => setSurface("colours")}>Colours</Seg>
            <Seg on={surface === "plate"} onClick={() => setSurface("plate")}>Plate fit</Seg>
          </div>
          {showColours && (
            <div className="flex items-center gap-2">
              <div role="group" aria-label="Colours to show" className="inline-flex rounded-md border border-border p-0.5 text-xs">
                <Seg on={effective === "original"} onClick={() => setMode("original")}>Original</Seg>
                <Seg on={effective === "proposed"} disabled={!hasDraft} onClick={() => setMode("proposed")}
                  title={hasDraft ? undefined : "Pick a spool colour in Materials to compare it here."}>Your choices</Seg>
                {preparedPath && (
                  <Seg on={effective === "copy"} disabled={!copyColours} onClick={() => setMode("copy")}
                    title={copyColours ? undefined : written.status === "loading" ? "Reading the copy…" : "Studio could not read the colours back from the copy."}>U1 copy</Seg>
                )}
              </div>
              <button type="button" onClick={() => setResetKey((k) => k + 1)}
                className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
                <RotateCcw className="h-3 w-3" aria-hidden="true" /> Reset view
              </button>
            </div>
          )}
        </div>
      )}

      {original.status === "loading" && (
        <p className="flex min-h-[260px] items-center justify-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Building the colour preview…
        </p>
      )}

      {showColours && preview && (
        <div className="grid min-h-0 flex-1 gap-3 md:grid-cols-[minmax(0,1fr)_minmax(180px,240px)]">
          <div className="relative h-[calc(100vh-24rem)] min-h-[300px] max-h-[560px] overflow-hidden rounded-lg border border-border bg-muted/30" data-testid="colour-view">
            <Suspense fallback={<p className="p-4 text-sm text-muted-foreground" role="status">Starting the 3D view…</p>}>
              <ModelViewer preview={preview} colourFor={colourFor} highlightSlot={highlight} resetKey={resetKey} onLost={onLost}
                label={`3D view of the project, ${preview.instances.length} ${preview.instances.length === 1 ? "object" : "objects"}: ${preview.instances.map((i) => i.label).join("; ")}. Drag to turn, scroll to zoom, arrow keys to move.`} />
            </Suspense>
          </div>
          {rows.length > 0
            ? <Legend rows={rows} mode={effective} onHighlight={setHighlight} unknownDefault={preview.unknown_default} />
            : <p className="text-xs text-muted-foreground" data-testid="shape-only">Shape only. This file does not say which filament prints where, so there are no colours to show.</p>}
        </div>
      )}

      {(surface === "plate" || original.status === "failed" || (original.status === "done" && !preview) || lost) && (
        <>
          {(message || lost) && original.status !== "loading" && (
            <p className="flex items-start gap-2 rounded-md border border-border bg-muted/40 p-2.5 text-sm" role="status" data-testid="preview-unavailable">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              <span>{lost ? `${LOSS_COPY[lost]} The plate view below is unaffected.` : message}</span>
            </p>
          )}
          <PlateView placement={placement} />
        </>
      )}

      {preview && showColours && (
        <details className="text-xs text-muted-foreground" data-testid="preview-notes">
          <summary className="cursor-pointer select-none">About this preview</summary>
          <ul className="mt-1.5 list-disc space-y-1 pl-4">
            <li data-testid="coverage-note">{COVERAGE_COPY[coverageClaim(preview)]}</li>
            {preview.notes.slice(1).map((n) => <li key={n}>{n}</li>)}
            <li>{preview.instances.length === 1 ? "1 object placed." : `${preview.instances.length} objects placed: ${preview.instances.map((i) => i.label).join("; ")}.`}</li>
          </ul>
        </details>
      )}
    </div>
  );
}

function Seg({ on, children, ...rest }: { on: boolean } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" aria-pressed={on} {...rest}
      className={`rounded px-2.5 py-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50 ${on ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}>
      {children}
    </button>
  );
}

function Swatch({ colour }: { colour: string | null }) {
  return (
    <span aria-hidden="true" className="inline-block h-4 w-4 shrink-0 rounded-sm border border-border"
      style={colour ? { backgroundColor: colour } : { backgroundImage: "repeating-linear-gradient(45deg, hsl(var(--border)) 0 3px, transparent 3px 6px)" }} />
  );
}

function Legend({ rows, mode, onHighlight, unknownDefault }: { rows: LegendRow[]; mode: PreviewMode; onHighlight: (slot: number | null) => void; unknownDefault: boolean }) {
  const beyond = beyondHeads(rows);
  const changedWord = mode === "copy" ? "in the copy" : "your choice";
  return (
    <div className="flex min-h-0 flex-col gap-2" data-testid="legend">
      <h3 className="flex items-baseline justify-between text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Filaments <span className="font-normal normal-case tracking-normal">share of surface</span>
      </h3>
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {rows.map((r) => (
          <li key={r.slot}>
            <button type="button" data-slot={r.slot}
              onMouseEnter={() => onHighlight(r.slot)} onMouseLeave={() => onHighlight(null)}
              onFocus={() => onHighlight(r.slot)} onBlur={() => onHighlight(null)}
              className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-sm hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
              aria-label={`${r.head ? `Toolhead ${r.head}` : `Slot ${r.slot}, no toolhead`}: ${r.original ?? "no colour listed"}${r.changed && mode !== "original" ? `, ${changedWord} ${r.proposed}` : ""}, ${r.used ? percent(r.share) : "unused"}`}>
              <Swatch colour={r.original} />
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{r.head ? `Head ${r.head}` : `Slot ${r.slot}`}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  {r.original ?? "no colour listed"}
                  {r.changed && mode !== "original" && (<> <span aria-hidden="true">→</span> {r.proposed}</>)}
                </span>
              </span>
              {r.changed && mode !== "original" && <Swatch colour={r.proposed} />}
              <span className="text-xs tabular-nums text-muted-foreground">{r.used ? percent(r.share) : "unused"}</span>
            </button>
          </li>
        ))}
      </ul>
      {beyond.length > 0 && (
        <p className="flex items-start gap-1.5 rounded-md bg-repairable/10 p-2 text-xs text-repairable-text" role="note" data-testid="beyond-heads">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            {beyond.length === 1 ? `Slot ${beyond[0].slot} has` : `Slots ${beyond.map((r) => r.slot).join(", ")} have`} no toolhead: the U1 has four.
            Studio draws {beyond.length === 1 ? "it" : "them"} in {beyond.length === 1 ? "its" : "their"} own colour and does not remove or merge colours. Decide in Snapmaker Orca before slicing.
          </span>
        </p>
      )}
      {unknownDefault && (
        <p className="text-xs text-muted-foreground" data-testid="unknown-default">
          Grey surface: the project does not say which filament prints it.
        </p>
      )}
    </div>
  );
}
