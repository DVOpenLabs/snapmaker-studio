import { Sun, Moon, FolderOpen, Info, Sparkles, SlidersHorizontal, Printer, ShieldCheck, Settings as SettingsIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { useTheme } from "@/store/theme";
import { useMode } from "@/store/mode";
import { usePrinter } from "@/store/printer";
import { useFilament } from "@/store/filament";
import MaterialProviderSettings from "@/components/MaterialProviderSettings";
import PrinterNozzleSettings from "@/components/PrinterNozzleSettings";

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <div>
        <p className="text-sm font-medium">{label}</p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
      {children}
    </div>
  );
}

export default function Settings() {
  const { theme, set } = useTheme();
  const { mode, setMode } = useMode();
  const { host, setHost } = usePrinter();
  const { pricePerKg, currency, setPrice, setCurrency } = useFilament();
  return (
    <div className="max-w-2xl space-y-6">
      <PageHeader icon={SettingsIcon} title="Settings" subtitle="Personalize Studio for your setup." />

      <MaterialProviderSettings />

      <Card>
        <CardContent className="divide-y divide-border p-5">
          <p className="flex items-center gap-2 pb-2 text-sm font-semibold"><Printer className="h-4 w-4" /> Printer</p>
          <Row label="Your Snapmaker U1" hint="Network name or IP. Used by the Printer Hub to show live status.">
            <input
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="U1.local"
              className="h-9 w-40 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            />
          </Row>
          <Row label="Printer access" hint="Monitors live status; send, pause, resume and cancel run only when you confirm — never auto-started.">
            <span className="inline-flex items-center gap-1 text-sm text-ready"><ShieldCheck className="h-4 w-4" /> Confirmed control</span>
          </Row>
        </CardContent>
      </Card>

      <PrinterNozzleSettings />

      <Card>
        <CardContent className="divide-y divide-border p-5">
          <p className="pb-2 text-sm font-semibold">Experience</p>
          <Row
            label="Mode"
            hint={
              mode === "simple"
                ? "Simple: guided, step-by-step — best for first-time users. Switch to Advanced for full diagnostics, side-by-side comparison, and raw settings."
                : "Advanced: every tool and detail visible at once — no hand-holding. Switch to Simple for a guided, one-action-at-a-time flow."
            }
          >
            <div className="flex gap-1">
              <Button variant={mode === "simple" ? "primary" : "secondary"} size="sm" onClick={() => setMode("simple")}>
                <Sparkles className="h-4 w-4" /> Simple
              </Button>
              <Button variant={mode === "advanced" ? "primary" : "secondary"} size="sm" onClick={() => setMode("advanced")}>
                <SlidersHorizontal className="h-4 w-4" /> Advanced
              </Button>
            </div>
          </Row>
          <p className="pt-2 text-xs text-muted-foreground">You can switch any time from the <b>View</b> toggle at the bottom of the sidebar.</p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="divide-y divide-border p-5">
          <p className="pb-2 text-sm font-semibold">Appearance</p>
          <Row label="Theme" hint="Match the look to your environment.">
            <div className="flex gap-1">
              <Button variant={theme === "light" ? "primary" : "secondary"} size="sm" onClick={() => set("light")}>
                <Sun className="h-4 w-4" /> Light
              </Button>
              <Button variant={theme === "dark" ? "primary" : "secondary"} size="sm" onClick={() => set("dark")}>
                <Moon className="h-4 w-4" /> Dark
              </Button>
            </div>
          </Row>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="divide-y divide-border p-5">
          <p className="pb-2 text-sm font-semibold">Filament</p>
          <Row label="Filament price" hint="Used to estimate the material cost of a print. Set it to what you pay per spool (per kg).">
            <div className="flex items-center gap-1">
              <input
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                aria-label="Currency symbol"
                className="h-9 w-12 rounded-md border border-border bg-card px-2 text-center text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
              />
              <input
                type="number" min={1} step={1}
                value={pricePerKg}
                onChange={(e) => setPrice(Number(e.target.value))}
                aria-label="Price per kilogram"
                className="h-9 w-20 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
              />
              <span className="text-sm text-muted-foreground">/ kg</span>
            </div>
          </Row>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="divide-y divide-border p-5">
          <p className="pb-2 text-sm font-semibold">Files</p>
          <Row label="Where U1 files are saved" hint="Converted projects are saved right next to the file you opened.">
            <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground"><FolderOpen className="h-4 w-4" /> Beside your original</span>
          </Row>
          <Row label="Keep originals" hint="Never overwrite source files.">
            <span className="text-sm text-muted-foreground">Always on</span>
          </Row>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-5">
          <div className="flex items-center gap-2 text-sm font-semibold"><Info className="h-4 w-4" /> About</div>
          <div className="mt-2 space-y-1 text-sm text-muted-foreground">
            <p>Snapmaker Studio · v{__APP_VERSION__}</p>
            <p>Local-first. No account, no cloud — nothing leaves your network. Printer Hub
            sends a sliced job to your own printer only when you confirm it.</p>
            <p>Independent open-source project — not affiliated with or endorsed by Snapmaker.</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
