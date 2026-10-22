import { Layers, Ruler } from "lucide-react";
import type { BedFit, FirstLayerReport } from "@/api";
import { Card, CardContent } from "@/components/ui/card";
import { NotCheckedReason } from "@/components/GeometryNotice";

/** What a size-dependent card shows when the model's physical size is not established: the same
 *  "Not checked" pill, the same reason sentence, and which check this card withheld. */
function Shell({ icon, title, pill, children }: { icon: React.ReactNode; title: string; pill: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="space-y-2 p-5" data-testid="size-not-checked">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-sm font-semibold">{icon} {title}</span>
          <span className="inline-flex items-center gap-1 rounded-full bg-repairable/10 px-2.5 py-0.5 text-[11px] font-semibold text-repairable">{pill}</span>
        </div>
        {children}
      </CardContent>
    </Card>
  );
}

export function BedFitNotChecked({ bed }: { bed?: BedFit | null }) {
  if (bed?.status !== "not_checked") return null;
  return (
    <Shell icon={<Ruler className="h-4 w-4 text-primary" />} title="Will it fit your U1?" pill="Not checked">
      <NotCheckedReason reason={bed.reason} scope={bed.scope} />
    </Shell>
  );
}

export function FirstLayerNotChecked({ report }: { report?: FirstLayerReport | null }) {
  if (report?.status !== "not_checked") return null;
  return (
    <Shell icon={<Layers className="h-4 w-4 text-primary" />} title="First-layer check" pill="Not checked">
      <NotCheckedReason reason={report.reason} scope={report.scope} />
    </Shell>
  );
}
