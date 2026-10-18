import { NavLink, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Plus, Sparkles, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { library } from "@/api";
import { useSession } from "@/store/session";
import { useMode } from "@/store/mode";
import { useOpenFile } from "@/hooks/useOpenFile";
import { PRIMARY_NAV, SECONDARY_NAV, SIMPLE_SECONDARY_NAV, BEGINNER_NAV, MORE_NAV } from "@/lib/nav";

function navClass({ isActive }: { isActive: boolean }) {
  return cn(
    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
    isActive ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
  );
}

export function Sidebar({ className, id, onNavigate }: { className?: string; id?: string; onNavigate?: () => void }) {
  const nav = useNavigate();
  const setFile = useSession((s) => s.setFile);
  const openFile = useOpenFile();
  const { mode, setMode } = useMode();
  const { data } = useQuery({ queryKey: ["library"], queryFn: () => library() });
  const recent = (data ?? []).slice(0, 3);

  return (
    <aside id={id} onClick={(e) => { if (onNavigate && (e.target as HTMLElement).closest("a,[data-closes-menu]")) onNavigate(); }}
           className={cn("h-full w-[230px] flex-col border-r border-border bg-card", className ?? "flex")}>
      <div className="flex items-center gap-2.5 px-4 h-14 border-b border-border">
        {/* Brand mark — ribbon stubs → core → cube (Intelligence Layer) */}
        <div className="flex h-8 w-8 items-center justify-center rounded-lg shadow-sm" style={{ background: "linear-gradient(135deg,#141A2C,#0A101C)" }}>
          <svg viewBox="0 0 32 32" className="h-7 w-7" fill="none" aria-hidden="true">
            <g stroke-width="1.6" stroke-linecap="round">
              <path d="M3 12 C8 12,9 16,13 16" stroke="#00E1FF"/>
              <path d="M3 16 C8 16,9 16,13 16" stroke="#FF00FF"/>
              <path d="M3 20 C8 20,9 16,13 16" stroke="#FF8300"/>
            </g>
            <circle cx="15" cy="16" r="4.2" stroke="#0061FF" stroke-width="1.6"/>
            <circle cx="15" cy="16" r="1.8" fill="#00E1FF"/>
            <path d="M22 12 L27 14.5 L27 19.5 L22 22 L17 19.5 L17 14.5 Z" fill="#8000FF" opacity="0.9"/>
            <path d="M22 12 L27 14.5 L22 17 L17 14.5 Z" fill="#fff" opacity="0.25"/>
          </svg>
        </div>
        <div className="leading-none">
          <span className="block font-semibold tracking-tight">Snapmaker Studio</span>
          <span className="block text-[10px] font-medium uppercase tracking-wide text-muted-foreground">The Intelligence Layer</span>
        </div>
      </div>

      <button data-closes-menu onClick={openFile} className="mx-3 mt-3 mb-1 flex items-center gap-2 rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/60 hover:text-foreground">
        <Plus className="h-4 w-4" /> Open a model
      </button>

      <nav aria-label="Main" className="flex flex-1 flex-col gap-1 overflow-y-auto p-3">
        {mode === "simple" ? (
          <>
            {BEGINNER_NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} className={navClass}>
                <n.icon className="h-4 w-4" /> {n.label}
              </NavLink>
            ))}
            <details className="mt-1">
              <summary className="flex cursor-pointer list-none items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted/60 hover:text-foreground">
                <SlidersHorizontal className="h-4 w-4" /> More tools
              </summary>
              <div className="mt-1 flex flex-col gap-1">
                {MORE_NAV.map((n) => (
                  <NavLink key={n.to} to={n.to} end={n.end} className={navClass}>
                    <n.icon className="h-4 w-4" /> {n.label}
                  </NavLink>
                ))}
              </div>
            </details>
          </>
        ) : (
          PRIMARY_NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={navClass}>
              <n.icon className="h-4 w-4" /> {n.label}
            </NavLink>
          ))
        )}
      </nav>

      {recent.length > 0 && (
        <>
          <div className="px-4 pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Recent</div>
          <div className="flex flex-col gap-0.5 px-2 py-1 overflow-y-auto">
            {recent.map((p) => (
              <button
                key={p.id}
                data-closes-menu
                onClick={() => { setFile(p.source_path); nav("/workspace"); }}
                title={p.source_path}
                className={navClass({ isActive: false }) + " w-full text-left"}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-current opacity-60" />
                <span className="truncate">{p.name}</span>
              </button>
            ))}
          </div>
        </>
      )}

      <div className="mt-auto space-y-2 p-3 border-t border-border">
        {/* Persistent mode switch — the single highest-leverage setting, surfaced
            where users work instead of buried in Settings. */}
        <div>
          <div className="px-1 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">View</div>
          <div className="grid grid-cols-2 gap-1 rounded-md bg-muted/50 p-0.5" role="group" aria-label="Choose Simple or Advanced view">
            <button
              onClick={() => setMode("simple")}
              aria-pressed={mode === "simple"}
              title="Guided, step-by-step — best for first-time users"
              className={cn("flex items-center justify-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors",
                mode === "simple" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}
            >
              <Sparkles className="h-3.5 w-3.5" /> Simple
            </button>
            <button
              onClick={() => setMode("advanced")}
              aria-pressed={mode === "advanced"}
              title="Every tool and detail visible at once — for power users"
              className={cn("flex items-center justify-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors",
                mode === "advanced" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}
            >
              <SlidersHorizontal className="h-3.5 w-3.5" /> Advanced
            </button>
          </div>
        </div>
        <nav aria-label="Settings and help" className="flex flex-col gap-1">
          {(mode === "simple" ? SIMPLE_SECONDARY_NAV : SECONDARY_NAV).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={navClass}>
              <n.icon className="h-4 w-4" /> {n.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </aside>
  );
}
