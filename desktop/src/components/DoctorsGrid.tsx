import { Link } from "react-router-dom";
import { PRIMARY_DOCTORS } from "@/lib/doctors";
import { Stethoscope } from "lucide-react";

// The Doctors as first-class citizens: the platform's primary user-facing
// capabilities, surfaced as a grid so a novice immediately sees what Studio does.
// "Powered by Studio Intelligence" is the supporting line — the engine behind them.
export function DoctorsGrid({ showP1 = true }: { showP1?: boolean }) {
  const doctors = showP1 ? PRIMARY_DOCTORS : PRIMARY_DOCTORS.filter((d) => d.tier === "P0");
  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Stethoscope className="h-4 w-4 text-primary" /> Your Doctors
        </h3>
        <span className="text-[11px] text-muted-foreground">Powered by Studio Intelligence</span>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {doctors.map((d) => (
          <Link key={d.id} to={d.route}
            className="surface-hover flex items-start gap-3 rounded-lg border border-border p-3 transition-colors hover:border-primary/40">
            <div
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
              style={{
                color: `hsl(var(${d.token}))`,
                backgroundColor: `hsl(var(${d.token}) / 0.12)`,
                boxShadow: `inset 0 0 0 1px hsl(var(${d.token}) / 0.25)`,
              }}
            >
              <d.icon className="h-[18px] w-[18px]" />
            </div>
            <div className="min-w-0">
              <p className="flex items-center gap-1.5 text-sm font-semibold">
                {d.name}
                {/* The stage word is text, so it reads in the foreground colour; the doctor's hue stays on the tint. */}
                <span className="rounded-full px-1.5 py-px text-[9px] font-medium uppercase tracking-wide text-foreground"
                      style={{ backgroundColor: `hsl(var(${d.token}) / 0.12)` }}>
                  {d.stage}
                </span>
              </p>
              <p className="text-xs leading-snug text-muted-foreground">{d.answers}</p>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
