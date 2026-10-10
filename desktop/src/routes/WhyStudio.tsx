import { Check, Minus, X, GitCompareArrows } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/layout";

// "Why Studio?" — positioning by OUTCOMES, not features. Studio is the layer
// above the slicer (Orca) and the host (Fluidd): it answers the questions they
// can't, before you waste filament. Each row is a question a maker actually asks.
type Cell = { v: "yes" | "partial" | "no"; t: string };
const ROWS: { q: string; orca: Cell; fluidd: Cell; studio: Cell }[] = [
  { q: "What is at risk — before I slice?",
    orca: { v: "no", t: "Slices, then errors" }, fluidd: { v: "no", t: "No model analysis" },
    studio: { v: "yes", t: "Project Doctor findings (advisory)" } },
  { q: "Why won't it slice (and the fix)?",
    orca: { v: "no", t: "“Out of bounds”, no reason" }, fluidd: { v: "no", t: "—" },
    studio: { v: "yes", t: "Cause + exact fix" } },
  { q: "What will it cost to make?",
    orca: { v: "no", t: "Grams + time only" }, fluidd: { v: "no", t: "—" },
    studio: { v: "yes", t: "Cost Doctor" } },
  { q: "What should I sell it for / my profit?",
    orca: { v: "no", t: "—" }, fluidd: { v: "no", t: "—" },
    studio: { v: "yes", t: "Pricing + Profit Doctor" } },
  { q: "Is my printer healthy?",
    orca: { v: "no", t: "—" }, fluidd: { v: "partial", t: "Raw telemetry" },
    studio: { v: "yes", t: "0–100 health score" } },
  { q: "What's the community's fix for this?",
    orca: { v: "no", t: "—" }, fluidd: { v: "no", t: "—" },
    studio: { v: "yes", t: "Built-in, per risk" } },
  { q: "One clear answer in 15 seconds?",
    orca: { v: "no", t: "Read the gcode" }, fluidd: { v: "no", t: "Read the dials" },
    studio: { v: "yes", t: "Intelligence Report" } },
];

function Mark({ cell, accent }: { cell: Cell; accent?: boolean }) {
  const icon = cell.v === "yes" ? <Check className="h-4 w-4" style={{ color: "hsl(var(--stage-validate))" }} />
    : cell.v === "partial" ? <Minus className="h-4 w-4 text-repairable" />
    : <X className="h-4 w-4 text-muted-foreground/50" />;
  return (
    <div className={`flex flex-col items-center gap-0.5 px-2 py-2 text-center ${accent ? "rounded-md" : ""}`}
         style={accent ? { backgroundColor: "hsl(var(--stage-validate) / 0.06)" } : undefined}>
      {icon}
      <span className={`text-[11px] ${cell.v === "yes" ? "text-foreground" : "text-muted-foreground"}`}>{cell.t}</span>
    </div>
  );
}

export default function WhyStudio() {
  return (
    <div className="space-y-6">
      <PageHeader icon={GitCompareArrows} title="Why Studio?"
        subtitle="Studio answers the questions the slicer can't, before you waste filament." />
      <Card>
        <CardContent className="p-0">
          <div className="grid grid-cols-[1.4fr_1fr_1fr_1fr] border-b border-border text-xs font-semibold">
            <div className="p-3 text-muted-foreground">The question a maker asks</div>
            <div className="p-3 text-center">OrcaSlicer</div>
            <div className="p-3 text-center">Fluidd</div>
            <div className="p-3 text-center text-primary">Snapmaker Studio</div>
          </div>
          {ROWS.map((r, i) => (
            <div key={i} className="grid grid-cols-[1.4fr_1fr_1fr_1fr] items-center border-b border-border last:border-0">
              <div className="p-3 text-sm font-medium">{r.q}</div>
              <Mark cell={r.orca} />
              <Mark cell={r.fluidd} />
              <Mark cell={r.studio} accent />
            </div>
          ))}
        </CardContent>
      </Card>
      <p className="text-center text-sm text-muted-foreground">
        Orca slices. Fluidd monitors. <span className="font-semibold text-foreground">Studio flags print risks, estimates the cost, and suggests a price</span> — in one screen.
      </p>
    </div>
  );
}
