import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// Tab switcher used to merge two closely-related tools onto one page (one sidebar
// item, two panels) instead of two duplicate nav entries. Each panel is an existing
// route component rendered as-is.
//
// Keyboard model (WAI-ARIA tabs pattern, manual activation):
// - Only one tab is in the Tab order (roving tabindex): the focused tab while focus is
//   in the row, otherwise the selected tab.
// - Arrow Left/Right (with wrap), Home and End move focus only. They never switch the
//   panel. Enter, Space or a click selects the focused tab.
// - Manual activation is deliberate. Switching unmounts one route and mounts the
//   other, which re-runs that route's engine requests. Moving focus along the tab row
//   must not trigger that. The pattern allows manual activation for panels that are
//   expensive to show.
// - Focus entering the row always lands on the selected tab: the tab stop resets to it
//   when focus leaves the row.
// - The selected tab and the tab that owns the tab stop are tracked separately
//   (`active` and `focused`).
export interface ToolTab {
  id: string;
  label: string;
  icon?: LucideIcon;
  el: ReactNode;
}

export function ToolTabs({ tabs, initial, label }: {
  tabs: ToolTab[];
  initial?: string;
  /** Accessible name of the tab row (rendered as aria-label), for example "Print quality tools". */
  label: string;
}) {
  const uid = useId();
  const [active, setActive] = useState(initial ?? tabs[0]?.id);
  const [focused, setFocused] = useState(active);
  const rootRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef(new Map<string, HTMLButtonElement>());
  // True while keyboard focus is somewhere inside this component (tab row or panel).
  const focusInside = useRef(false);

  // A tab can disappear while selected or focused. Fall back to the first remaining tab.
  const activeId = tabs.some((t) => t.id === active) ? active : tabs[0]?.id;
  const focusedId = tabs.some((t) => t.id === focused) ? focused : activeId;
  const idKey = tabs.map((t) => t.id).join("\u0000");

  useEffect(() => {
    // With no tabs the root is gone and no blur fired; forget any focus that was inside it.
    if (!activeId) focusInside.current = false;
    // Keep the stored state in step with what is shown, so a removed tab that
    // returns later does not silently become selected again.
    if (activeId !== active) setActive(activeId);
    if (focusedId !== focused) setFocused(focusedId);
    // If focus was on the removed tab, or inside the panel that was unmounted, the
    // browser has dropped it to the page body. Put it on the selected tab.
    const now = document.activeElement;
    const lost = !now || now === document.body || !now.isConnected || !rootRef.current?.contains(now);
    if (focusInside.current && lost && activeId) tabRefs.current.get(activeId)?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idKey]);

  if (tabs.length === 0 || !activeId) return null;
  const current = tabs.find((t) => t.id === activeId) ?? tabs[0];
  const tabDomId = (id: string) => `${uid}-tab-${id}`;
  const panelDomId = (id: string) => `${uid}-panel-${id}`;

  const moveFocus = (id: string) => {
    setFocused(id);
    tabRefs.current.get(id)?.focus();
  };
  const select = (id: string) => {
    setFocused(id);
    setActive(id);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    // Browser and assistive-technology shortcuts (Alt+Left is Back, Ctrl+Home scrolls) are left alone.
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const last = tabs.length - 1;
    let next: number | null = null;
    if (e.key === "ArrowRight") next = index === last ? 0 : index + 1;
    else if (e.key === "ArrowLeft") next = index === 0 ? last : index - 1;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = last;
    if (next !== null) {
      e.preventDefault();
      moveFocus(tabs[next].id);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      select(tabs[index].id);
    }
  };

  return (
    <div
      ref={rootRef}
      className="space-y-4"
      onFocus={() => { focusInside.current = true; }}
      onBlur={(e) => {
        // A removed element fires no blur, so this only clears when focus truly moves out.
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) focusInside.current = false;
      }}
    >
      <div className="flex flex-wrap gap-1 border-b border-border" role="tablist" aria-label={label}
        onBlur={(e) => {
          // Leaving the row resets the tab stop to the selected tab, so coming back in (Shift+Tab from the
          // panel, or Tab from above) lands on the selected tab and not on one that was only arrowed to.
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(activeId);
        }}>
        {tabs.map((t, i) => (
          <button key={t.id} id={tabDomId(t.id)} role="tab" type="button"
            ref={(el) => { if (el) tabRefs.current.set(t.id, el); else tabRefs.current.delete(t.id); }}
            aria-selected={t.id === activeId}
            /* Inactive panels are unmounted, so only the selected tab can point at a panel id. */
            aria-controls={t.id === activeId ? panelDomId(t.id) : undefined}
            tabIndex={t.id === focusedId ? 0 : -1}
            onClick={() => select(t.id)}
            onFocus={() => setFocused(t.id)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(
              "-mb-px flex items-center gap-1.5 rounded-sm border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              // ring-offset-2 and ring-offset-background are an intentional addition to the button.tsx ring tokens.
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              t.id === activeId
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground")}>
            {t.icon ? <t.icon className="h-4 w-4" aria-hidden="true" /> : null}{t.label}
          </button>
        ))}
      </div>
      {/* key: always unmount the previous panel, even when two panels render the same component type. */}
      <div key={current.id} role="tabpanel" id={panelDomId(current.id)} aria-labelledby={tabDomId(current.id)} tabIndex={-1}
        className="outline-none">
        {current.el}
      </div>
    </div>
  );
}
