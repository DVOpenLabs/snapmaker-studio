import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface PaneTab {
  id: string;
  label: string;
  /** A short mark beside the label (for example the number of choices held). */
  badge?: string | null;
  el: ReactNode;
}

/**
 * Tabs whose panels all stay mounted. The Materials panel holds spool choices in its own
 * state, so unmounting it on a tab change would silently throw them away.
 *
 * Keyboard: Arrow Left/Right, Home and End move between tabs and select (automatic
 * activation, because showing a mounted panel is free). Only the selected tab is in the Tab order.
 */
export function PaneTabs({ tabs, active, onChange, label }: {
  tabs: PaneTab[]; active: string; onChange: (id: string) => void; label: string;
}) {
  const uid = useId();
  const refs = useRef(new Map<string, HTMLButtonElement>());
  const tabId = (id: string) => `${uid}-tab-${id}`;
  const panelId = (id: string) => `${uid}-panel-${id}`;

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const last = tabs.length - 1;
    let next: number | null = null;
    if (e.key === "ArrowRight") next = index === last ? 0 : index + 1;
    else if (e.key === "ArrowLeft") next = index === 0 ? last : index - 1;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = last;
    if (next === null) return;
    e.preventDefault();
    const id = tabs[next].id;
    onChange(id);
    refs.current.get(id)?.focus();
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div role="tablist" aria-label={label} className="flex shrink-0 gap-0.5 border-b border-border">
        {tabs.map((t, i) => (
          <button key={t.id} id={tabId(t.id)} role="tab" type="button" data-pane-tab={t.id}
            ref={(el) => { if (el) refs.current.set(t.id, el); else refs.current.delete(t.id); }}
            aria-selected={t.id === active} aria-controls={panelId(t.id)}
            tabIndex={t.id === active ? 0 : -1}
            onClick={() => onChange(t.id)} onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(
              "-mb-px flex items-center gap-1.5 rounded-t-sm border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              t.id === active ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            {t.label}
            {t.badge ? <span className="rounded-full bg-primary/15 px-1.5 text-[11px] font-semibold text-primary">{t.badge}</span> : null}
          </button>
        ))}
      </div>
      {tabs.map((t) => (
        <div key={t.id} id={panelId(t.id)} role="tabpanel" aria-labelledby={tabId(t.id)} hidden={t.id !== active}
          tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto py-4 outline-none">
          {t.el}
        </div>
      ))}
    </div>
  );
}
