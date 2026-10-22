import { AlertTriangle, Loader2 } from "lucide-react";
import { FlatCards } from "@/components/ui/card";
import { PlacementView, type usePlacement } from "@/components/PlacementCard";
import { plateModel } from "@/lib/plateView";

const GRID_MM = 50;

/**
 * The plate, from the placement check alone: each object's footprint against the printable area.
 *
 * This is a footprint drawing, not a rendered model, and it is only drawn when Studio established
 * where the objects sit. A multi-plate or partly-judged project gets the reason instead of a picture
 * that would read as a fit.
 */
export function PlateView({ placement }: { placement: ReturnType<typeof usePlacement> }) {
  const { check, failed, fix, fixing, runFix } = placement;
  const model = plateModel(check);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3" data-testid="plate-view">
      <div className="flex min-h-[220px] flex-1 items-center justify-center rounded-lg border border-border bg-muted/30 p-3">
        {failed ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
            <AlertTriangle className="h-4 w-4 text-repairable" aria-hidden="true" />
            Studio could not check this project&apos;s placement. Review it in Snapmaker Orca before slicing.
          </p>
        ) : model.kind === "loading" ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Reading where the objects sit…
          </p>
        ) : model.kind === "none" ? (
          <p className="max-w-sm text-center text-sm text-muted-foreground" data-testid="plate-none">{model.reason}</p>
        ) : (
          <PlateSvg model={model} />
        )}
      </div>
      {!failed && (
        <FlatCards>
          <PlacementView check={check} fix={fix} fixing={fixing} onFix={runFix} />
        </FlatCards>
      )}
    </div>
  );
}

function PlateSvg({ model }: { model: Extract<ReturnType<typeof plateModel>, { kind: "drawn" }> }) {
  const { width, depth, rects } = model;
  const lines = (n: number) => Array.from({ length: Math.floor(n / GRID_MM) }, (_, i) => (i + 1) * GRID_MM);
  const summary = `Top view of ${model.bedName} printable area, ${Math.round(width)} by ${Math.round(depth)} millimetres. ` +
    rects.map((r) => `${r.label}${r.off ? " is outside the area" : ""}`).join("; ") + ".";
  return (
    <figure className="m-0 flex max-h-full w-full max-w-[420px] flex-col items-center gap-1.5">
      <svg role="img" aria-label={summary} viewBox={`-6 -6 ${width + 12} ${depth + 12}`} className="h-auto max-h-[340px] w-full">
        <rect x={0} y={0} width={width} height={depth} rx={4} className="fill-card stroke-border" strokeWidth={1.5} />
        {lines(width).map((x) => <line key={`v${x}`} x1={x} x2={x} y1={0} y2={depth} className="stroke-border" strokeWidth={0.5} opacity={0.6} />)}
        {lines(depth).map((y) => <line key={`h${y}`} x1={0} x2={width} y1={y} y2={y} className="stroke-border" strokeWidth={0.5} opacity={0.6} />)}
        {rects.map((r) => {
          // The front edge is at the bottom, as the person looks at the printer.
          const y = depth - r.y - r.h;
          const fits = r.w > 60 && r.h > 22;
          return (
            <g key={r.key}>
              <rect x={r.x} y={y} width={r.w} height={r.h} rx={2}
                className={r.off ? "fill-risk/25 stroke-risk" : "fill-primary/20 stroke-primary"} strokeWidth={2}
                strokeDasharray={r.off ? "6 4" : undefined} />
              {fits && <text x={r.x + r.w / 2} y={y + r.h / 2} textAnchor="middle" dominantBaseline="middle"
                className="fill-foreground" fontSize={Math.min(14, r.w / 9)}>{r.label.replace(" · ", "\n").split("\n")[0]}</text>}
            </g>
          );
        })}
        <text x={width / 2} y={depth + 4.5} textAnchor="middle" className="fill-muted-foreground" fontSize={8}>front</text>
      </svg>
      <figcaption className="text-xs text-muted-foreground">
        Footprints from the project file against {model.bedName} printable area. Not a rendered model.
      </figcaption>
    </figure>
  );
}
