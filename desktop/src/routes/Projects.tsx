import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Search, FolderKanban, FileBox, Boxes, Loader2, AlertTriangle, Trash2, RotateCw,
  Clock, ChevronDown, Copy, CheckCircle2, Plus,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/badge";
import type { Verdict } from "@/components/ui/badge";
import { PageHeader, EmptyState } from "@/components/ui/layout";
import { library, libraryDelete, history } from "@/api";
import type { LibraryProject } from "@/api";
import { useSession } from "@/store/session";
import { useMode } from "@/store/mode";
import { useToast } from "@/store/toast";
import { cn } from "@/lib/utils";

function eventLabel(action: string): string {
  if (action === "convert") return "Prepared U1 copy";
  if (action === "doctor") return "Checked";
  return action;
}

const FILTERS: { label: string; match: (v: string | null) => boolean }[] = [
  { label: "All", match: () => true },
  { label: "Profile compatible", match: (v) => v === "READY" },
  { label: "Needs prep", match: (v) => v !== "READY" },
];

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
}

function Timeline({ projectId }: { projectId: number }) {
  const { data, status } = useQuery({
    queryKey: ["history", projectId],
    queryFn: () => history(projectId),
  });
  if (status === "pending") return <p className="px-1 py-2 text-xs text-muted-foreground">Loading…</p>;
  if (status === "error") return <p className="px-1 py-2 text-xs text-muted-foreground">Couldn’t load history.</p>;
  if (!data || data.length === 0) return <p className="px-1 py-2 text-xs text-muted-foreground">No activity yet.</p>;
  return (
    <ol className="relative space-y-2 border-l border-border pl-4 pt-2">
      {data.map((e) => (
        <li key={e.id} className="relative">
          <span className="absolute -left-[21px] top-1 h-2 w-2 rounded-full border-2 border-primary bg-background" />
          <p className="text-xs font-medium">{eventLabel(e.action)}</p>
          <p className="flex items-center gap-1 text-[11px] text-muted-foreground"><Clock className="h-3 w-3" /> {fmtDate(e.at)}</p>
        </li>
      ))}
    </ol>
  );
}

function LibraryCard({ p, onOpen, onDelete, simple }: {
  p: LibraryProject; onOpen: () => void; onDelete: () => void; simple: boolean;
}) {
  const Icon = p.name.toLowerCase().endsWith(".stl") ? FileBox : Boxes;
  const [showHistory, setShowHistory] = useState(false);
  const unit = simple ? "color" : "filament";
  const showToast = useToast((s) => s.show);
  const copyOutput = () => {
    if (!p.output_path) return;
    navigator.clipboard?.writeText(p.output_path).then(
      () => showToast("U1 file path copied"),
      () => showToast("Couldn’t copy the path"),
    );
  };
  return (
    <Card className="group transition-all hover:border-primary/40 hover:shadow-md">
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <button
            onClick={onOpen}
            className="flex min-w-0 items-center gap-2.5 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            title={p.source_path}
          >
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground group-hover:text-foreground">
              <Icon className="h-[18px] w-[18px]" />
            </span>
            <span className="truncate font-medium">{p.name}</span>
          </button>
          {p.verdict && <StatusBadge verdict={p.verdict as Verdict} />}
        </div>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {(p.source_family ?? "project")}
            {p.filament_count != null && ` · ${p.filament_count} ${unit}${p.filament_count === 1 ? "" : "s"}`}
          </span>
          <span>{fmtDate(p.updated_at)}</span>
        </div>
        <div className="flex items-center justify-between">
          {p.output_path ? (
            <button
              onClick={copyOutput}
              className="inline-flex items-center gap-1 rounded text-xs text-ready hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
              title={p.output_path}
            >
              <CheckCircle2 className="h-3.5 w-3.5" /> U1 profile copy <Copy className="h-3 w-3 opacity-70" />
            </button>
          ) : (
            <span className="text-xs text-muted-foreground">Last: {p.last_action ? eventLabel(p.last_action) : "—"}</span>
          )}
          <button
            onClick={onDelete}
            className="rounded p-1 text-muted-foreground opacity-0 transition hover:text-risk group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            title="Remove from library (keeps your files)"
            aria-label={`Remove ${p.name} from library`}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
        <div className="border-t border-border pt-2">
          <button
            onClick={() => setShowHistory((v) => !v)}
            className="flex items-center gap-1 rounded text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
          >
            <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", showHistory && "rotate-180")} /> History
          </button>
          {showHistory && <Timeline projectId={p.id} />}
        </div>
      </CardContent>
    </Card>
  );
}

export default function Projects() {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState(0);
  const nav = useNavigate();
  const setFile = useSession((s) => s.setFile);
  const qc = useQueryClient();
  const simple = useMode((s) => s.mode) === "simple";

  const { data, status, error, refetch, isFetching } = useQuery({
    queryKey: ["library", query],
    queryFn: () => library(query),
  });

  const del = useMutation({
    mutationFn: (id: number) => libraryDelete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["library"] }),
  });

  const shown = useMemo(
    () => (data ?? []).filter((p) => FILTERS[filter].match(p.verdict)),
    [data, filter]
  );
  const total = data?.length ?? 0;
  const readyCount = (data ?? []).filter((p) => p.verdict === "READY").length;

  const openProject = (p: LibraryProject) => {
    setFile(p.source_path);
    nav("/workspace");
  };

  return (
    <div className="space-y-6">
      <PageHeader
        icon={FolderKanban}
        title={simple ? "My Designs" : "Projects"}
        subtitle={
          status === "success" && total > 0 ? (
            <span className="flex items-center gap-1.5">
              <span>{total} design{total === 1 ? "" : "s"}</span>
              <span>·</span>
              <CheckCircle2 className="h-3.5 w-3.5 text-ready" />
              <span>{readyCount} profile compatible</span>
              {total - readyCount > 0 && <span>· {total - readyCount} need prep</span>}
            </span>
          ) : (
            simple ? "Everything you've worked on, ready to revisit." : "Your prepared and checked designs."
          )
        }
        actions={
          <Button variant="secondary" size="sm" onClick={() => refetch()} disabled={isFetching}>
            {isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />} Refresh
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex h-9 min-w-[220px] flex-1 items-center gap-2 rounded-md border border-border bg-card px-3">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search projects…"
            className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
        </div>
        <div className="flex gap-1">
          {FILTERS.map((f, i) => (
            <Button key={f.label} variant={filter === i ? "primary" : "secondary"} size="sm" onClick={() => setFilter(i)}>
              {f.label}
            </Button>
          ))}
        </div>
      </div>

      {status === "pending" && (
        <div className="flex items-center gap-2 py-16 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading your library…
        </div>
      )}

      {status === "error" && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
            <AlertTriangle className="h-7 w-7 text-risk" />
            <p className="font-medium">Couldn’t load your library</p>
            <p className="text-sm text-muted-foreground">{String((error as Error)?.message ?? error)}</p>
            <Button variant="secondary" size="sm" onClick={() => refetch()}>
              <RotateCw className="h-4 w-4" /> Retry
            </Button>
          </CardContent>
        </Card>
      )}

      {status === "success" && shown.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {shown.map((p) => (
            <LibraryCard key={p.id} p={p} simple={simple} onOpen={() => openProject(p)} onDelete={() => del.mutate(p.id)} />
          ))}
        </div>
      )}

      {status === "success" && shown.length === 0 && (
        <Card>
          <CardContent className="p-0">
            {(data?.length ?? 0) === 0 && !query ? (
              <EmptyState
                icon={FolderKanban}
                title="Your design library starts here"
                description="All your models, with what Studio found."
                action={<Button size="sm" onClick={() => nav("/")}><Plus className="h-4 w-4" /> Open your first model</Button>}
              />
            ) : (
              <EmptyState
                icon={Search}
                title="No matching designs"
                description="Try a different search term or switch filters."
              />
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
