import { useEffect, useId, useMemo, useReducer, useRef } from "react";
import { ChevronDown, Search } from "lucide-react";
import type { ProviderSpool } from "@/api";
import {
  MAX_VISIBLE, describeSpool, filterSpools, initialListbox, listboxReduce, sortSpools,
} from "@/lib/spoolPicker";

// A searchable, keyboard-driven spool picker in Studio's own colours.
//
// It replaces a native <select>, whose popup is drawn by the operating system and came out
// light-on-light in the dark theme. Everything here uses the theme tokens, so the theme
// stays in Studio's hands, and every row says what the spool is in words (vendor, material,
// colour name, the provider's id, the weight status), with the swatch as an extra.

function Swatch({ colour }: { colour: string | null }) {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-3.5 w-3.5 shrink-0 rounded-full border border-border"
      style={colour ? { backgroundColor: colour } : undefined}
    />
  );
}

export default function SpoolListbox({
  spools, value, onChange, ariaLabel, noneLabel = "— nothing mapped —",
}: {
  spools: ProviderSpool[];
  value: number | string | null | undefined;
  onChange: (id: number | string | null) => void;
  ariaLabel: string;
  noneLabel?: string;
}) {
  const uid = useId();
  const listId = `${uid}-list`;
  const [state, dispatch] = useReducer(listboxReduce, initialListbox);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const sorted = useMemo(() => sortSpools(spools), [spools]);
  const matches = useMemo(() => filterSpools(sorted, state.query), [sorted, state.query]);
  const shown = matches.slice(0, MAX_VISIBLE);
  const selected = value === null || value === undefined || value === ""
    ? null
    : sorted.find((s) => String(s.id) === String(value)) ?? null;
  const active = Math.min(state.active, shown.length - 1);

  function openList() {
    const idx = selected ? shown.findIndex((s) => String(s.id) === String(selected.id)) : -1;
    dispatch({ type: "open", selectedIndex: idx });
  }

  function choose(index: number) {
    onChange(index < 0 ? null : shown[index]?.id ?? null);
    dispatch({ type: "close" });
  }

  useEffect(() => {
    if (!state.open) return;
    inputRef.current?.focus();
    function outside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) dispatch({ type: "close" });
    }
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [state.open]);

  function onKey(e: React.KeyboardEvent) {
    switch (e.key) {
      case "ArrowDown": e.preventDefault(); dispatch({ type: "move", delta: 1, count: shown.length }); break;
      case "ArrowUp": e.preventDefault(); dispatch({ type: "move", delta: -1, count: shown.length }); break;
      case "Home": if (state.open) { e.preventDefault(); dispatch({ type: "home" }); } break;
      case "End": if (state.open) { e.preventDefault(); dispatch({ type: "end", count: shown.length }); } break;
      case "Enter": if (state.open) { e.preventDefault(); choose(active); } break;
      case "Escape": if (state.open) { e.preventDefault(); dispatch({ type: "close" }); } break;
      case "Tab": if (state.open) dispatch({ type: "close" }); break;
    }
  }

  const description = selected ? describeSpool(selected) : null;

  return (
    <div ref={rootRef} className="relative flex-1">
      <button
        type="button"
        role="combobox"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={state.open}
        aria-controls={listId}
        onClick={() => (state.open ? dispatch({ type: "close" }) : openList())}
        onKeyDown={(e) => { if (!state.open && (e.key === "ArrowDown" || e.key === "ArrowUp")) { e.preventDefault(); openList(); } }}
        className="flex h-8 w-full items-center gap-2 rounded-md border border-border bg-card px-2 text-left text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {description ? (
          <>
            <Swatch colour={description.swatch} />
            <span className="min-w-0 flex-1 truncate">{description.text}</span>
          </>
        ) : (
          <span className="flex-1 text-muted-foreground">{noneLabel}</span>
        )}
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
      </button>

      {state.open && (
        <div className="absolute left-0 right-0 z-20 mt-1 rounded-md border border-border bg-card text-foreground shadow-lg">
          <div className="flex items-center gap-2 border-b border-border px-2">
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
            <input
              ref={inputRef}
              value={state.query}
              onChange={(e) => dispatch({ type: "type", query: e.target.value })}
              onKeyDown={onKey}
              placeholder="Type to find a spool — vendor, material, colour, #id"
              aria-label="Find a spool"
              aria-controls={listId}
              aria-activedescendant={active >= 0 ? `${uid}-opt-${active}` : undefined}
              className="h-8 w-full bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
            />
          </div>
          <ul id={listId} role="listbox" aria-label={ariaLabel} className="max-h-64 overflow-auto py-1">
            <li
              role="option"
              aria-selected={!selected}
              onMouseDown={(e) => { e.preventDefault(); choose(-1); }}
              className={`cursor-pointer px-2 py-1.5 text-xs text-muted-foreground ${active === -1 ? "bg-muted" : ""}`}
            >
              {noneLabel}
            </li>
            {shown.map((spool, i) => {
              const d = describeSpool(spool);
              return (
                <li
                  key={String(spool.id)}
                  id={`${uid}-opt-${i}`}
                  role="option"
                  aria-selected={!!selected && String(selected.id) === String(spool.id)}
                  onMouseDown={(e) => { e.preventDefault(); choose(i); }}
                  className={`flex cursor-pointer items-center gap-2 px-2 py-1.5 text-xs ${active === i ? "bg-muted" : ""}`}
                >
                  <Swatch colour={d.swatch} />
                  <span className="min-w-0 flex-1 truncate">{d.text}</span>
                </li>
              );
            })}
            {matches.length === 0 && (
              <li role="presentation" className="px-2 py-2 text-xs text-muted-foreground">
                No spool matches “{state.query}”.
              </li>
            )}
            {matches.length > MAX_VISIBLE && (
              <li role="presentation" className="px-2 py-2 text-[11px] text-muted-foreground">
                Showing the first {MAX_VISIBLE} of {matches.length}. Type to narrow the list.
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
