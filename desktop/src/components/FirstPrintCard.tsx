import { Link } from "react-router-dom";
import { Rocket, ArrowRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

// Beginner anchor for the Dashboard: the whole "find → check → prepare → slice →
// send" path in one card, so a first-time U1 owner isn't lost in 20+ sidebar items.
// Plain language; the one slicer term (gcode) is explained where it appears.
const STEPS: { n: number; label: string; to: string }[] = [
  { n: 1, label: "Find a model", to: "/find-models" },
  { n: 2, label: "Source Check (what file is this?)", to: "/source" },
  { n: 3, label: "Project Doctor (what is at risk?)", to: "/doctor/project" },
  { n: 4, label: "Prepare a U1 copy", to: "/doctor/project" },
  { n: 5, label: "Open in Snapmaker Orca", to: "/doctor/project" },
  { n: 6, label: "Export the gcode from Orca", to: "/doctor/project" },
  { n: 7, label: "Upload / send in Printer Hub", to: "/printers" },
];

export function FirstPrintCard() {
  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div className="flex items-center gap-2">
          <Rocket className="h-5 w-5 text-primary" />
          <p className="text-base font-semibold">Start your first print</p>
        </div>
        <p className="text-sm text-muted-foreground">
          New to the Snapmaker U1? Studio walks you from a downloaded model to a print —
          checking, preparing, and sending. You slice in Snapmaker Orca; Studio does the rest.
        </p>
        <ol className="grid gap-1 sm:grid-cols-2">
          {STEPS.map((s) => (
            <li key={s.n}>
              <Link to={s.to} className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm text-muted-foreground hover:bg-muted/40 hover:text-foreground">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-semibold">{s.n}</span>
                {s.label}
              </Link>
            </li>
          ))}
        </ol>
        <Button asChild>
          <Link to="/start"><Rocket className="h-4 w-4" /> Start guided flow <ArrowRight className="h-4 w-4" /></Link>
        </Button>
      </CardContent>
    </Card>
  );
}
