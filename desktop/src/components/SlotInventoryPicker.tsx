import { useEffect, useId, useMemo, useRef, useState } from "react";
import { AlertTriangle, Loader2, Search } from "lucide-react";
import { describeSpool, filterSpools, MAX_VISIBLE } from "@/lib/spoolPicker";
import {
  candidateAsSpool, needsSpoolConfirmation, slotNumber, STATUS_LABEL,
  type MaterialCandidate, type MaterialInventory,
} from "@/lib/projectMaterials";

// The deliberate manual override: every spool the provider lists for one slot, not only the few Studio
// ranked. It reuses the spool picker's own description, search and ordering (lib/spoolPicker), so a spool is
// worded the same way here as in the provider settings. A different colour is shown, never blocked. A spool
// of another material family carries the engine's warning and is used only after the person accepts it.
// Nothing is chosen for the person, and the words of every warning come from the engine.

export const INVENTORY_COPY = {
  button: "Choose another spool",
  close: "Close the spool list",
  loading: "Reading your spool inventory…",
  empty: "The provider lists no spools that can be used.",
  unavailable: "Studio could not read your spool provider just now, so there is no inventory to show.",
  unsupported: "This project can no longer be read for its filament slots.",
  sameFamily: "Same material",
  otherFamily: "Different material — you will be asked to confirm",
  useAnyway: "Use this spool anyway",
  cancel: "Cancel",
} as const;

function Swatch({ colour }: { colour: string | null }) {
  return <span aria-hidden className="inline-block h-3.5 w-3.5 shrink-0 rounded-full border border-border" style={colour ? { backgroundColor: colour } : undefined} />;
}

export interface InventoryPickerProps {
  slot: number;
  load: (slot: number) => Promise<MaterialInventory>;
  onChoose: (spool: MaterialCandidate) => void;
  onClose: () => void;
}

export default function SlotInventoryPicker({ slot, load, onChoose, onClose }: InventoryPickerProps) {
  const uid = useId();
  const [state, setState] = useState<{ status: "loading" } | { status: "error"; error: string } | { status: "ready"; inventory: MaterialInventory }>({ status: "loading" });
  const [query, setQuery] = useState("");
  const [pending, setPending] = useState<MaterialCandidate | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  // Cancel is the safe answer, so it is where focus goes when a confirmation opens.
  useEffect(() => { if (pending) cancelRef.current?.focus(); }, [pending]);

  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    load(slot).then(
      (inventory) => { if (live) setState({ status: "ready", inventory }); },
      (e: any) => { if (live) setState({ status: "error", error: String(e?.message ?? e) }); },
    );
    return () => { live = false; };
  }, [slot, load]);

  useEffect(() => { if (state.status === "ready") searchRef.current?.focus(); }, [state.status]);

  const inventory = state.status === "ready" ? state.inventory : null;
  const entries = Array.isArray(inventory?.entries) ? inventory!.entries : [];
  // The engine answers "could not read the provider" and "not a project" as ordinary replies with no entries;
  // neither is an empty inventory.
  const problem = !inventory ? null
    : inventory.supported === false ? INVENTORY_COPY.unsupported
    : inventory.provider && !inventory.provider.available ? INVENTORY_COPY.unavailable
    : null;
  // The picker's own search over the picker's own description of each spool, applied to the engine's order.
  const shown = useMemo(() => {
    const byId = new Map(entries.map((c) => [String(c.spool_id), c]));
    return filterSpools(entries.map(candidateAsSpool), query).map((s) => byId.get(String(s.id))!).filter(Boolean);
  }, [entries, query]);
  const visible = shown.slice(0, MAX_VISIBLE);
  const same = visible.filter((c) => c.family_match !== false);
  const other = visible.filter((c) => c.family_match === false);

  function pick(c: MaterialCandidate) {
    if (needsSpoolConfirmation(c)) { setPending(c); return; }
    onChoose(c);
  }

  function row(c: MaterialCandidate) {
    const d = describeSpool(candidateAsSpool(c));
    const confirming = pending && String(pending.spool_id) === String(c.spool_id);
    const warning = needsSpoolConfirmation(c);
    return (
      <li key={`${c.provider}:${c.spool_id}`} className="rounded-md border border-border">
        <button type="button" onClick={() => pick(c)} aria-expanded={confirming ? true : undefined}
          className="flex w-full flex-wrap items-center gap-x-2 gap-y-0.5 rounded-md px-2 py-1.5 text-left text-xs hover:bg-muted/50">
          <Swatch colour={d.swatch} />
          <span className="min-w-0 flex-1 truncate">{d.text}</span>
          <span className="shrink-0 text-[11px] text-muted-foreground" data-testid="preset-status">
            Orca preset: {STATUS_LABEL[c.mapping.status]}{c.mapping.status !== "no_match" && c.mapping.base_name ? ` · ${c.mapping.base_name}` : ""}
          </span>
          {warning && (
            <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-repairable/15 px-2 py-px text-[11px] font-semibold text-repairable">
              <AlertTriangle className="h-3 w-3" />Different material
            </span>
          )}
        </button>
        {confirming && warning && (
          <div className="space-y-2 border-t border-border bg-repairable/10 p-2 text-xs" role="alertdialog" aria-label="Confirm a different material" data-testid="family-confirm"
            onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); setPending(null); } }}>
            <p className="flex items-start gap-1.5 text-repairable"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{warning}</p>
            <div className="flex gap-2">
              <button type="button" className="rounded-md bg-primary px-2 py-1 font-medium text-primary-foreground" onClick={() => { setPending(null); onChoose(c); }}>{INVENTORY_COPY.useAnyway}</button>
              <button ref={cancelRef} type="button" className="rounded-md bg-secondary px-2 py-1" onClick={() => setPending(null)}>{INVENTORY_COPY.cancel}</button>
            </div>
          </div>
        )}
      </li>
    );
  }

  return (
    <div className="space-y-2 rounded-md border border-border bg-card p-2" data-testid="inventory-picker">
      {state.status === "loading" && <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />{INVENTORY_COPY.loading}</p>}
      {state.status === "error" && <p className="text-xs text-risk" role="alert">Couldn&apos;t read your spool inventory: {state.error}</p>}
      {state.status === "ready" && (
        <>
          <div className="flex items-center gap-2 border-b border-border pb-1">
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <input ref={searchRef} type="search" value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="Type to find a spool — vendor, material, colour, #id" aria-label={`Find a spool for slot ${slotNumber(slot)}`}
              aria-controls={`${uid}-list`} className="h-8 w-full bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground" />
          </div>
          <div id={`${uid}-list`} className="max-h-72 space-y-2 overflow-auto">
            {problem && <p className="px-1 py-1 text-xs text-risk" role="alert" data-testid="inventory-problem">{problem}</p>}
            {!problem && entries.length === 0 && <p className="px-1 py-1 text-xs text-muted-foreground" data-testid="inventory-empty">{INVENTORY_COPY.empty}</p>}
            {entries.length > 0 && shown.length === 0 && <p className="px-1 py-1 text-xs text-muted-foreground">No spool matches “{query}”.</p>}
            {same.length > 0 && (
              <div>
                <p className="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{INVENTORY_COPY.sameFamily}</p>
                <ul className="space-y-1" aria-label={`Spools of the same material for slot ${slotNumber(slot)}`}>{same.map(row)}</ul>
              </div>
            )}
            {other.length > 0 && (
              <div>
                <p className="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wide text-repairable">{INVENTORY_COPY.otherFamily}</p>
                <ul className="space-y-1" aria-label={`Spools of a different material for slot ${slotNumber(slot)}`}>{other.map(row)}</ul>
              </div>
            )}
            {shown.length > MAX_VISIBLE && <p className="px-1 text-[11px] text-muted-foreground">Showing the first {MAX_VISIBLE} of {shown.length}. Type to narrow the list.</p>}
          </div>
        </>
      )}
      <button type="button" className="text-xs text-muted-foreground hover:underline" onClick={onClose}>{INVENTORY_COPY.close}</button>
    </div>
  );
}
