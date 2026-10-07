import { Link } from "react-router-dom";
import { Rocket, ArrowRight, ExternalLink } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/layout";
import { USER_GUIDE_BLURB, USER_GUIDE_LABEL, USER_GUIDE_URL } from "@/lib/guide";

// Lightweight beginner guide: from model to first print. Each step links to the
// real Studio feature. Studio does NOT slice or send prints — those steps happen
// in Snapmaker Orca / on the printer, and we say so plainly.
interface Step { n: number; title: string; body: string; to?: string; link?: string; inStudio: boolean; }

const STEPS: Step[] = [
  { n: 1, title: "Find a model", inStudio: true, to: "/find-models", link: "Find Models",
    body: "Browse approved model sites inside Studio and check the license. Download with the site's own button and Studio adds supported downloads to your Library." },
  { n: 2, title: "Open it in Studio", inStudio: true, to: "/", link: "Open a model",
    body: "Drag an STL or 3MF in. Studio reads it locally — your file stays on your computer." },
  { n: 3, title: "Run the Project Doctor", inStudio: true, to: "/doctor/project", link: "Project Doctor",
    body: "Check fit, geometry and printability before you waste filament." },
  { n: 4, title: "Fix compatibility / colour / scale", inStudio: true, to: "/compatibility", link: "Compatibility Doctor",
    body: "Foreign/stale 3MF? Compatibility Doctor. One plate's colour? Plate Color Remap. Resizing? Scale Doctor — all advisory/verified, never silent edits." },
  { n: 5, title: "Slice in Snapmaker Orca", inStudio: false,
    body: "Studio does not slice. Open the prepared file in Snapmaker Orca with the U1 profile and set layer height / infill / supports / adhesion." },
  { n: 6, title: "Prepare the printer", inStudio: false,
    body: "Load filament, level the bed and set Z-offset on the U1. Make sure the build plate is clean." },
  { n: 7, title: "Watch the first layer", inStudio: true, to: "/first-layer", link: "First Layer Doctor",
    body: "The first layer makes or breaks a print. If it looks wrong, the First Layer Doctor lists safe first checks." },
  { n: 8, title: "Monitor the print", inStudio: true, to: "/printers", link: "Printer Hub",
    body: "Keep an eye on it. If the result looks bad, the Print Quality Doctor helps diagnose. (Printer controls always ask for an explicit confirmation.)" },
];

export default function BeginnerWorkflow() {
  return (
    <div className="space-y-6">
      <PageHeader icon={Rocket} title="From model to first print"
        subtitle="A beginner's path through Studio — and where Orca and your printer take over." />

      <Card><CardContent className="space-y-1.5 p-4 text-sm">
        <p className="font-medium">Prefer a click-through tour?</p>
        <p className="text-muted-foreground">{USER_GUIDE_BLURB}</p>
        <a href={USER_GUIDE_URL} target="_blank" rel="noreferrer"
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
          {USER_GUIDE_LABEL} <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
      </CardContent></Card>

      <div className="space-y-3">
        {STEPS.map((s) => (
          <Card key={s.n}><CardContent className="flex gap-3 p-4">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary">{s.n}</span>
            <div className="min-w-0">
              <p className="flex items-center gap-2 text-sm font-medium">
                {s.title}
                {!s.inStudio && <span className="rounded bg-muted px-1.5 py-px text-[10px] font-medium uppercase tracking-wide text-muted-foreground">outside Studio</span>}
              </p>
              <p className="text-sm text-muted-foreground">{s.body}</p>
              {s.to && s.link && (
                <Link to={s.to} className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline">
                  {s.link} <ArrowRight className="h-3 w-3" />
                </Link>
              )}
            </div>
          </CardContent></Card>
        ))}
      </div>

      <p className="text-xs text-muted-foreground">
        Studio understands, checks and prepares your files locally. It does not slice or send prints —
        that's Snapmaker Orca and your U1.
      </p>
    </div>
  );
}
