import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  UploadCloud, Plus, ArrowRight,
  FileBox, Boxes, Loader2, CheckCircle2, AlertTriangle, RotateCw,
  Printer, Thermometer, Sparkles, Wand2,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/badge";
import type { Verdict } from "@/components/ui/badge";
import { SectionTitle } from "@/components/ui/layout";
import { Workflow } from "@/components/Workflow";
import { HeroMark } from "@/components/HeroMark";
import { DoctorsGrid } from "@/components/DoctorsGrid";
import { FirstPrintCard } from "@/components/FirstPrintCard";
import { IntelligenceReport } from "@/components/IntelligenceReport";
import { library, printerStatus, demoReport } from "@/api";
import { useState } from "react";
import type { LibraryProject } from "@/api";
import { useSession } from "@/store/session";
import { useMode } from "@/store/mode";
import { usePrinter } from "@/store/printer";
import { useOpenFile } from "@/hooks/useOpenFile";

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24); if (d < 7) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

function activityText(p: LibraryProject): string {
  if (p.last_action === "convert") return `Prepared ${p.name} for U1`;
  return `Checked ${p.name}${p.verdict ? ` — ${p.verdict[0]}${p.verdict.slice(1).toLowerCase()}` : ""}`;
}

function PrinterCard() {
  const host = usePrinter((s) => s.host);
  const { data, status } = useQuery({
    queryKey: ["dash-printer", host],
    queryFn: () => printerStatus(host),
    refetchInterval: 5000,   // read-only liveness
    retry: false,
  });
  const online = status === "success";
  const printing = data?.print_state === "printing";
  return (
    <Card>
      <CardContent className="p-5">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-semibold"><Printer className="h-4 w-4" /> Your U1</h3>
          <Link to="/printers" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            Printer Hub <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
        {status === "pending" ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Checking {host}…</div>
        ) : online && data ? (
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${printing ? "bg-primary" : "bg-ready"}`} />
              <span className="font-medium capitalize">{data.print_state ?? "idle"}</span>
              {data.progress != null && <span className="ml-auto text-muted-foreground">{Math.round(data.progress * 100)}%</span>}
            </div>
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Thermometer className="h-3.5 w-3.5" /> Bed {data.bed.temperature ?? "—"}°
              {data.toolheads[0] ? ` · Tool 1 ${data.toolheads[0].temperature ?? "—"}°` : ""}
            </p>
          </div>
        ) : (
          <div className="space-y-2 text-sm text-muted-foreground">
            <p>No U1 connected.</p>
            <Button variant="secondary" size="sm" asChild>
              <Link to="/printers"><Printer className="h-4 w-4" /> Connect your printer</Link>
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function Dashboard() {
  const openFile = useOpenFile();
  const nav = useNavigate();
  const setFile = useSession((s) => s.setFile);
  const unit = useMode((s) => s.mode) === "simple" ? "color" : "filament";

  const { data, status, error, refetch } = useQuery({ queryKey: ["library"], queryFn: () => library() });
  const projects = data ?? [];
  const recent = projects.slice(0, 3);
  const ready = projects.filter((p) => p.verdict === "READY").length;
  const needsWork = projects.length - ready;

  const openProject = (p: LibraryProject) => { setFile(p.source_path); nav("/workspace"); };

  // Demo Mode: one click → a full Studio Intelligence Report, no file or printer.
  const [demoOn, setDemoOn] = useState(false);
  const demo = useQuery({ queryKey: ["demo-report"], queryFn: () => demoReport(), enabled: demoOn, retry: false });

  return (
    <div className="space-y-8">
      <div className="flex items-center gap-5">
        <HeroMark className="hidden h-20 w-44 shrink-0 sm:block" />
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">
            The <span className="brand-gradient">Intelligence Layer</span> for Open 3D Printing
          </h2>
          <p className="text-muted-foreground">One place. Any file. Any printer. Catch print risks before slicing — your Project, Printer &amp; Cost Doctors check every model before your U1 ever sees it. Local-first &amp; open source.</p>
          <button onClick={() => setDemoOn(true)}
                  className="mt-3 inline-flex h-9 items-center gap-2 rounded-md border border-primary/40 bg-primary/5 px-4 text-sm font-medium text-primary transition-colors hover:bg-primary/10">
            <Sparkles className="h-4 w-4" /> {demo.isFetching ? "Loading demo…" : "See a 10-second demo"}
          </button>
        </div>
      </div>

      {/* Demo Mode — full Intelligence Report, no file or printer needed */}
      {demoOn && demo.data?.available && (
        <div className="space-y-3">
          <IntelligenceReport data={demo.data} />
          <div className="flex justify-end">
            <button onClick={() => nav("/why")}
                    className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground shadow-sm">
              Why Studio? <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* Hero: open a model + the end-to-end workflow it flows through */}
      <Card className="surface-raised overflow-hidden">
        <CardContent className="p-0">
          <button onClick={openFile} className="flex w-full items-center gap-4 border-b border-border p-5 text-left transition-colors hover:bg-muted/40">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary ring-1 ring-primary/20">
              <UploadCloud className="h-6 w-6" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-base font-medium">Open a model to begin</p>
              <p className="text-sm text-muted-foreground">Drag in or browse for a <b>.stl</b> or <b>.3mf</b> · your file stays on your computer</p>
            </div>
            <span className="hidden shrink-0 sm:block">
              <span className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground shadow-sm">
                <Plus className="h-4 w-4" /> Open a model
              </span>
            </span>
          </button>
          <div className="p-3 sm:p-4">
            <Workflow />
          </div>
        </CardContent>
      </Card>

      {/* Beginner anchor: the whole first-print path in one card. */}
      <FirstPrintCard />

      {/* The Doctors — Studio's first-class, user-facing capabilities. */}
      <DoctorsGrid />

      {/* First-run "why Studio?" — only for a brand-new, empty library. */}
      {status === "success" && projects.length === 0 && (
        <Card>
          <CardContent className="p-5">
            <h3 className="text-sm font-semibold">Why Snapmaker Studio?</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Before you slice in Snapmaker Orca, Studio flags a model's print risks for your U1 — then keeps an eye on it while it does.
            </p>
            <div className="mt-4 grid gap-4 sm:grid-cols-3">
              <div className="flex gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Sparkles className="h-[18px] w-[18px]" /></span>
                <div className="min-w-0">
                  <p className="text-sm font-medium">Understand &amp; check</p>
                  <p className="text-xs text-muted-foreground">Size, colors, geometry health and a plain-language list of risks — before you waste filament.</p>
                </div>
              </div>
              <div className="flex gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Wand2 className="h-[18px] w-[18px]" /></span>
                <div className="min-w-0">
                  <p className="text-sm font-medium">Fix &amp; prepare U1 copy</p>
                  <p className="text-xs text-muted-foreground">Prepares any STL or 3MF into a U1 profile copy. Your original is never changed.</p>
                </div>
              </div>
              <div className="flex gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Printer className="h-[18px] w-[18px]" /></span>
                <div className="min-w-0">
                  <p className="text-sm font-medium">Watch it print</p>
                  <p className="text-xs text-muted-foreground">Live temperatures, progress, cost and failure insights from your U1. Monitoring is read-only; send, pause, resume and cancel run only when you confirm.</p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {status === "error" && (
        <Card>
          <CardContent className="flex items-center gap-2 p-4 text-sm">
            <AlertTriangle className="h-4 w-4 text-risk" />
            <span className="text-muted-foreground">Couldn’t load your library: {String((error as Error)?.message ?? error)}</span>
            <Button variant="secondary" size="sm" className="ml-auto" onClick={() => refetch()}>
              <RotateCw className="h-4 w-4" /> Retry
            </Button>
          </CardContent>
        </Card>
      )}

      <section>
        <SectionTitle trailing={
          <Link to="/projects" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            All projects <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        }>Continue working</SectionTitle>
        {status === "pending" ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
        ) : status === "error" ? (
          <div className="py-6 text-sm text-muted-foreground">Library unavailable — see the error above.</div>
        ) : recent.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {recent.map((p) => {
              const Icon = p.name.toLowerCase().endsWith(".stl") ? FileBox : Boxes;
              return (
                <Card key={p.id} role="button" tabIndex={0}
                  onClick={() => openProject(p)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openProject(p); } }}
                  className="group cursor-pointer transition-all hover:border-primary/40 hover:shadow-md">
                  <CardContent className="space-y-3 p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2.5">
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground group-hover:text-foreground">
                          <Icon className="h-[18px] w-[18px]" />
                        </span>
                        <span className="truncate font-medium">{p.name}</span>
                      </div>
                      {p.verdict && <StatusBadge verdict={p.verdict as Verdict} />}
                    </div>
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>{(p.source_family ?? "project")}{p.filament_count != null ? ` · ${p.filament_count} ${unit}${p.filament_count === 1 ? "" : "s"}` : ""}</span>
                      <span>{timeAgo(p.updated_at)}</span>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        ) : (
          <Card>
            <CardContent className="flex flex-col items-center justify-center gap-1 py-10 text-center">
              <p className="text-sm font-medium">No projects yet</p>
              <p className="text-sm text-muted-foreground">Open a model above — it’ll appear here once you check or prepare it.</p>
            </CardContent>
          </Card>
        )}
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardContent className="p-5">
            <h3 className="mb-3 text-sm font-semibold">Activity</h3>
            {status === "pending" ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
            ) : status === "error" ? (
              <p className="text-sm text-muted-foreground">Activity unavailable.</p>
            ) : projects.length > 0 ? (
              <ul className="space-y-2 text-sm">
                {projects.slice(0, 6).map((p) => (
                  <li key={p.id} className="flex items-center gap-2 text-muted-foreground">
                    <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                    <span className="truncate text-foreground">{activityText(p)}</span>
                    <span className="ml-auto shrink-0 text-xs">{timeAgo(p.updated_at)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No activity yet. Your conversions and checks will show up here.</p>
            )}
          </CardContent>
        </Card>
        <div className="space-y-4">
          <Card>
            <CardContent className="p-5">
              <h3 className="mb-3 text-sm font-semibold">Library</h3>
              <div className="space-y-1 text-sm text-muted-foreground">
                {status === "error" ? (
                  <p>Library unavailable.</p>
                ) : (
                  <>
                    <p><span className="text-2xl font-semibold text-foreground">{projects.length}</span> project{projects.length === 1 ? "" : "s"}</p>
                    {projects.length > 0 ? (
                      <p className="flex items-center gap-1.5">
                        <CheckCircle2 className="h-3.5 w-3.5 text-ready" />{ready} profile-compatible · {needsWork} need prep
                      </p>
                    ) : (
                      <p>Nothing indexed yet.</p>
                    )}
                  </>
                )}
              </div>
            </CardContent>
          </Card>
          <PrinterCard />
        </div>
      </section>
    </div>
  );
}
