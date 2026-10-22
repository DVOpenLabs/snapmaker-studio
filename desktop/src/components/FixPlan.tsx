import { AlertTriangle, CheckCircle2, ListChecks } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// Beginner Fix Plan (beta.21): one prioritized, plain-language list built ONLY
// from checks that already ran — no new analysis, no fake readiness. Max 5
// actions; each says whether to do it in Studio or in Snapmaker Orca. Wording
// rules: advisory only, never "ready / safe / guaranteed".

type Level = "ok" | "warn" | "risk";

interface FixAction {
  title: string;
  detail: string;
  where: "Studio" | "Orca";
  level: Level;
}

interface FixPlanProps {
  doctor?: {
    object_count?: number | null;
    filament_count?: number | null;
    prepare_blocked?: boolean;
  } | null;
  isStl: boolean;
  report?: { ready: boolean; at_risk: string[] } | null;
  bed?: { available?: boolean; overall_level?: string | null; overall_text?: string | null; fixes?: string[] | null } | null;
  mm?: { available?: boolean; multi_material?: boolean; overall_level?: string | null; fixes?: string[] | null } | null;
  mesh?: {
    available?: boolean;
    integrity?: { watertight: boolean; holes: number } | null;
    overhang?: { supports_likely: boolean } | null;
  } | null;
}

export function buildFixPlan(p: FixPlanProps): FixAction[] {
  const issues: FixAction[] = [];
  const level = (l?: string | null): Level => (l === "risk" ? "risk" : l === "warn" ? "warn" : "ok");

  if (p.bed?.available && p.bed.overall_level && p.bed.overall_level !== "ok") {
    issues.push({
      title: "Make it fit the plate",
      detail: p.bed.fixes?.[0] ?? p.bed.overall_text ?? "The design is tight or outside the U1's plate — scale it down or rotate it.",
      where: "Orca",
      level: level(p.bed.overall_level),
    });
  }
  if (p.mesh?.available && p.mesh.integrity && (!p.mesh.integrity.watertight || p.mesh.integrity.holes > 0)) {
    issues.push({
      title: "Repair the mesh first",
      detail: "The mesh isn't watertight, so slicing can misbehave. Use Snapmaker Orca's repair (right-click the model → Fix model) before slicing.",
      where: "Orca",
      level: "warn",
    });
  }
  if (p.mm?.available && p.mm.multi_material && p.mm.overall_level && p.mm.overall_level !== "ok") {
    issues.push({
      title: "Sort colours vs toolheads",
      detail: p.mm.fixes?.[0] ?? "This design uses more colours than the U1 has toolheads — merge similar colours or plan filament swaps in Orca.",
      where: "Orca",
      level: level(p.mm.overall_level),
    });
  }
  if (p.mesh?.available && p.mesh.overhang?.supports_likely) {
    issues.push({
      title: "Turn on supports",
      detail: "Steep overhangs found — enable supports in Snapmaker Orca (tree supports are a good first try).",
      where: "Orca",
      level: "warn",
    });
  }
  if (!p.isStl && (p.doctor?.object_count ?? 0) > 1) {
    issues.push({
      title: "Check object spacing",
      detail: "Studio can't verify object-to-object spacing for multi-part layouts. Review the project in Snapmaker Orca and watch for too-close / collision warnings.",
      where: "Orca",
      level: "warn",
    });
  }

  // Risks first, then warns; cap at 4 so the next step always fits.
  issues.sort((a, b) => (a.level === b.level ? 0 : a.level === "risk" ? -1 : 1));
  const top = issues.slice(0, 4);

  top.push(p.doctor?.prepare_blocked ? {
    title: "Review the original in Snapmaker Orca",
    detail: "Studio cannot prepare this project. Check the reported settings or structure in the slicer that made the file and export it again.",
    where: "Orca",
    level: "warn",
  } : {
    title: "Prepare a U1 profile copy",
    detail: "Studio writes a new copy with U1 profile settings — your original is never changed. Then open the copy in Snapmaker Orca and review it before slicing.",
    where: "Studio",
    level: "ok",
  });
  return top;
}

export function FixPlan(props: FixPlanProps) {
  const plan = buildFixPlan(props);
  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-sm font-semibold">
            <ListChecks className="h-4 w-4 text-primary" /> Your fix plan
          </span>
          <span className="text-[11px] text-muted-foreground">advisory — not a guarantee</span>
        </div>
        <ol className="space-y-2">
          {plan.map((a, i) => (
            <li key={i} className="flex items-start gap-2.5 text-sm">
              <span className={cn("mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold",
                a.level === "risk" ? "bg-risk/15 text-risk" : a.level === "warn" ? "bg-repairable/15 text-repairable" : "bg-ready/15 text-ready")}>
                {i + 1}
              </span>
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 font-medium">
                  {a.level === "ok"
                    ? <CheckCircle2 className="h-3.5 w-3.5 text-ready" />
                    : <AlertTriangle className={cn("h-3.5 w-3.5", a.level === "risk" ? "text-risk" : "text-repairable")} />}
                  {a.title}
                  <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-semibold",
                    a.where === "Studio" ? "border-primary/40 text-primary" : "border-border text-muted-foreground")}>
                    {a.where === "Studio" ? "Do this in Studio" : "Do this in Orca"}
                  </span>
                </p>
                <p className="text-xs text-muted-foreground">{a.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
