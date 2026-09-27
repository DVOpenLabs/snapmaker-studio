import { useEffect, useState } from "react";
import { AlertTriangle, NotebookPen, Loader2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  ApiError, localSpoolsDelete, localSpoolsList, localSpoolsMarkUsed, localSpoolsSave,
  type LocalSpoolRow,
} from "@/api";
import { usePrinter } from "@/store/printer";
import { displayHost } from "@/lib/host";
import {
  buildSpoolSaveBody, remainingLabel, validateSpoolForm, validateUsedG,
  type SpoolFormErrors,
} from "@/lib/spoolForm";

// "Your spool notes · for <host>" — always visible, independent of whether a
// material provider is configured. A note only fills a gap the printer and the
// provider both leave open; the printer always wins about what is actually
// loaded, and changing provider never touches a note (they are unrelated
// stores, on purpose — see plan D-1/A1.3).

const SLOTS = [0, 1, 2, 3];

interface EditorState {
  slot: number;
  id: number | null; // editing an existing row, or null for a new note
  material: string;
  subtype: string;
  color: string; // "#RRGGBB", legacy free text as-is, or ""
  colorTouched: boolean;
  vendor: string;
  startingG: string;
  startingGTouched: boolean;
  remainingG: string;
  remainingGTouched: boolean;
  notes: string;
}

function blankEditor(slot: number): EditorState {
  return {
    slot, id: null, material: "", subtype: "", color: "", colorTouched: false,
    vendor: "", startingG: "", startingGTouched: false, remainingG: "", remainingGTouched: false,
    notes: "",
  };
}

/** Material can be null on a legacy colour-only row (D8) — the editor still
 *  opens, with an empty (required) material field for the user to fill in. */
function rowToEditor(row: LocalSpoolRow): EditorState {
  return {
    slot: row.slot, id: row.id, material: row.material ?? "", subtype: row.subtype ?? "",
    color: row.color ?? "", colorTouched: false, vendor: row.vendor ?? "",
    startingG: row.starting_g != null ? String(row.starting_g) : "", startingGTouched: false,
    remainingG: row.remaining_g != null ? String(row.remaining_g) : "", remainingGTouched: false,
    notes: row.notes ?? "",
  };
}

function isHexColor(c: string): boolean {
  return /^#[0-9A-Fa-f]{6}$/.test(c);
}

/** Pure presentational rendering of the slot list (rows, alias conflicts, and
 *  the empty "Add a note" affordance) — exported so its states (empty, one
 *  note, alias conflict) can be exercised directly in tests without needing
 *  the surrounding fetch effect to have run. */
export function SpoolRowsList({
  rows, busy, onEdit, onRemove, onAdd,
}: {
  rows: LocalSpoolRow[];
  busy: boolean;
  onEdit: (row: LocalSpoolRow) => void;
  onRemove: (row: LocalSpoolRow) => void;
  onAdd: (slot: number) => void;
}) {
  function rowsForSlot(slot: number): LocalSpoolRow[] {
    return rows.filter((r) => r.slot === slot);
  }

  return (
    <ul className="space-y-2">
      {SLOTS.map((slot) => {
        const slotRows = rowsForSlot(slot);
        if (slotRows.length === 0) return null;

        if (slotRows.length > 1) {
          // Alias conflict (A1.3/A3.4): never merged, shown per-row for removal.
          return slotRows.map((row) => (
            <li
              key={row.id}
              className="flex items-center gap-2 rounded-md border border-risk/40 bg-risk/5 p-2.5 text-xs"
            >
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-risk" aria-hidden="true" />
              <span>Two notes exist for slot {slot + 1} — remove one</span>
              <Button
                size="sm" variant="secondary" className="ml-auto"
                aria-label={`Remove one of the two notes for slot ${slot + 1}`}
                disabled={busy} onClick={() => onRemove(row)}
              >
                Remove
              </Button>
            </li>
          ));
        }

        const row = slotRows[0];
        return (
          <li key={row.id} className="flex items-center gap-2 rounded-md border border-border p-2.5 text-xs">
            <span
              className="h-3 w-3 shrink-0 rounded-full border border-border"
              style={{ backgroundColor: isHexColor(row.color ?? "") ? (row.color as string) : "transparent" }}
              aria-hidden="true"
            />
            <span className="w-16 shrink-0 text-muted-foreground">Slot {slot + 1}</span>
            <span className="flex-1 truncate">
              {row.material ?? "(no material recorded)"}
              {row.subtype ? ` · ${row.subtype}` : ""}{row.vendor ? ` · ${row.vendor}` : ""}
              {" — "}{remainingLabel(row.remaining_g, row.remaining_quality, row.remaining_as_of)}
            </span>
            <Button size="sm" variant="secondary" onClick={() => onEdit(row)}>Edit</Button>
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => onRemove(row)}>Remove</Button>
          </li>
        );
      })}
      {SLOTS.filter((slot) => rowsForSlot(slot).length === 0).map((slot) => (
        <li key={`empty-${slot}`} className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="w-16 shrink-0">Slot {slot + 1}</span>
          <Button size="sm" variant="ghost" onClick={() => onAdd(slot)}>Add a note</Button>
        </li>
      ))}
    </ul>
  );
}

function apiErrorMessage(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.message : fallback;
}

export default function LocalSpoolSettings() {
  const host = usePrinter((s) => s.host);
  const canonical = displayHost(host);
  const [rows, setRows] = useState<LocalSpoolRow[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [errors, setErrors] = useState<SpoolFormErrors>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [markUsedFor, setMarkUsedFor] = useState<number | null>(null);
  const [usedGrams, setUsedGrams] = useState("");
  const [usedError, setUsedError] = useState<string | null>(null);
  const [usedConfirm, setUsedConfirm] = useState(false);

  useEffect(() => {
    let alive = true;
    setRows(null);
    setLoadError(false);
    setEditor(null);
    localSpoolsList(host).then(
      (r) => { if (alive) setRows(r.rows); },
      () => { if (alive) setLoadError(true); },
    );
    return () => { alive = false; };
  }, [host]);

  async function refresh() {
    try {
      const r = await localSpoolsList(host);
      setRows(r.rows);
    } catch {
      setLoadError(true);
    }
  }

  async function save() {
    if (!editor) return;
    const formErrors = validateSpoolForm({
      material: editor.material, color: editor.color, colorTouched: editor.colorTouched,
      startingG: editor.startingG, remainingG: editor.remainingG,
    });
    setErrors(formErrors);
    if (Object.keys(formErrors).length > 0) return;

    // Only a field the user actually touched is ever sent (D2) — an untouched
    // remaining weight is never re-stamped by an unrelated edit, and a change
    // to material/colour/etc. is left for the backend to decide whether it
    // resets the weight (A2.2), rather than the desktop guessing at it here.
    const body = buildSpoolSaveBody({
      material: editor.material, subtype: editor.subtype, color: editor.color,
      colorTouched: editor.colorTouched, vendor: editor.vendor,
      startingG: editor.startingG, startingGTouched: editor.startingGTouched,
      remainingG: editor.remainingG, remainingGTouched: editor.remainingGTouched,
      notes: editor.notes,
    });

    setBusy(true);
    setActionError(null);
    try {
      await localSpoolsSave({ host, slot: editor.slot, ...body });
      setEditor(null);
      await refresh();
    } catch (e) {
      setActionError(apiErrorMessage(e, "Couldn't save this note. Try again."));
    } finally {
      setBusy(false);
    }
  }

  async function remove(row: LocalSpoolRow) {
    setBusy(true);
    setActionError(null);
    try {
      await localSpoolsDelete(host, row.slot, row.id);
      await refresh();
    } catch (e) {
      setActionError(apiErrorMessage(e, "Couldn't remove this note. Try again."));
    } finally {
      setBusy(false);
    }
  }

  async function confirmMarkUsed(slot: number) {
    const result = validateUsedG(usedGrams);
    if (!result.ok) { setUsedError(result.error); return; }
    setBusy(true);
    setActionError(null);
    try {
      await localSpoolsMarkUsed(host, slot, result.value);
      setMarkUsedFor(null);
      setUsedGrams("");
      setUsedConfirm(false);
      setUsedError(null);
      // The server now holds a fresh, backend-computed estimate for this slot.
      // Close the editor rather than let it keep showing the grams that were
      // just typed in — reopening (Edit) re-reads the refreshed row (D2).
      setEditor(null);
      await refresh();
    } catch (e) {
      setUsedError(apiErrorMessage(e, "Couldn't record what you used. Try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 border-t border-border pt-4">
      <div>
        <p className="flex items-center gap-2 text-sm font-semibold">
          <NotebookPen className="h-4 w-4" aria-hidden="true" /> Your spool notes · for {canonical}
        </p>
        <p className="pt-1 text-xs text-muted-foreground">
          What you know is loaded, slot by slot. Studio uses a note only for what the printer
          and your provider do not report — the printer always wins about what is loaded.
        </p>
      </div>

      {loadError && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" /> Couldn't load your spool notes. Try again.
        </p>
      )}

      {rows === null && !loadError && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> Loading your notes…
        </p>
      )}

      {rows !== null && rows.length === 0 && (
        <p className="text-[11px] text-muted-foreground">
          No notes yet. Add one when you load a spool the printer or provider cannot describe —
          Studio never fills this in for you.
        </p>
      )}

      {actionError && (
        <p className="flex items-center gap-2 rounded-md border border-risk/40 bg-risk/5 p-2 text-[11px] text-risk">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> {actionError}
        </p>
      )}

      {rows !== null && (
        <SpoolRowsList
          rows={rows} busy={busy}
          onEdit={(row) => { setEditor(rowToEditor(row)); setErrors({}); setActionError(null); }}
          onRemove={(row) => remove(row)}
          onAdd={(slot) => { setEditor(blankEditor(slot)); setErrors({}); setActionError(null); }}
        />
      )}

      {editor && (
        <div className="space-y-2 rounded-md border border-border p-3">
          <p className="text-xs font-medium">Slot {editor.slot + 1}</p>

          <label className="block text-xs">
            Material
            <input
              aria-label="Material" required value={editor.material}
              onChange={(e) => setEditor({ ...editor, material: e.target.value })}
              className="mt-1 h-8 w-full rounded-md border border-border bg-card px-2 text-xs outline-none"
            />
            {errors.material && <span className="mt-1 block text-[11px] text-risk">{errors.material}</span>}
          </label>

          <label className="block text-xs">
            Subtype
            <input
              aria-label="Subtype" value={editor.subtype}
              onChange={(e) => setEditor({ ...editor, subtype: e.target.value })}
              className="mt-1 h-8 w-full rounded-md border border-border bg-card px-2 text-xs outline-none"
            />
          </label>

          <div className="flex items-center gap-2 text-xs">
            <label className="flex items-center gap-2">
              Colour
              <input
                type="color" aria-label="Colour"
                value={isHexColor(editor.color) ? editor.color : "#888888"}
                onChange={(e) => setEditor({ ...editor, color: e.target.value.toUpperCase(), colorTouched: true })}
                className="h-8 w-10 rounded border border-border bg-card"
              />
            </label>
            {editor.color && !isHexColor(editor.color) && (
              <span className="text-muted-foreground">{editor.color} (as recorded)</span>
            )}
            <Button
              size="sm" variant="ghost"
              onClick={() => setEditor({ ...editor, color: "", colorTouched: true })}
            >
              Clear
            </Button>
            {errors.color && <span className="text-[11px] text-risk">{errors.color}</span>}
          </div>

          <label className="block text-xs">
            Vendor
            <input
              aria-label="Vendor" value={editor.vendor}
              onChange={(e) => setEditor({ ...editor, vendor: e.target.value })}
              className="mt-1 h-8 w-full rounded-md border border-border bg-card px-2 text-xs outline-none"
            />
          </label>

          <div className="flex gap-2">
            <label className="flex-1 text-xs">
              Starting g
              <input
                type="number" min={0} max={10000} aria-label="Starting weight in grams"
                value={editor.startingG}
                onChange={(e) => setEditor({ ...editor, startingG: e.target.value, startingGTouched: true })}
                className="mt-1 h-8 w-full rounded-md border border-border bg-card px-2 text-xs outline-none"
              />
              {errors.startingG && <span className="mt-1 block text-[11px] text-risk">{errors.startingG}</span>}
            </label>
            <label className="flex-1 text-xs">
              Remaining g
              <input
                type="number" min={0} max={10000} aria-label="Remaining weight in grams"
                value={editor.remainingG}
                onChange={(e) => setEditor({ ...editor, remainingG: e.target.value, remainingGTouched: true })}
                className="mt-1 h-8 w-full rounded-md border border-border bg-card px-2 text-xs outline-none"
              />
              {errors.remainingG && <span className="mt-1 block text-[11px] text-risk">{errors.remainingG}</span>}
            </label>
          </div>

          <label className="block text-xs">
            Notes
            <textarea
              aria-label="Notes" value={editor.notes}
              onChange={(e) => setEditor({ ...editor, notes: e.target.value })}
              className="mt-1 h-16 w-full rounded-md border border-border bg-card px-2 py-1 text-xs outline-none"
            />
          </label>

          <div className="flex items-center gap-2 pt-1">
            <Button size="sm" disabled={busy} onClick={save}>Save</Button>
            <Button size="sm" variant="secondary" onClick={() => setEditor(null)}>Cancel</Button>
            {editor.id != null && (
              <Button
                size="sm" variant="ghost" className="ml-auto"
                onClick={() => { setMarkUsedFor(editor.slot); setUsedGrams(""); setUsedError(null); setUsedConfirm(false); }}
              >
                Record filament used
              </Button>
            )}
          </div>

          {markUsedFor === editor.slot && (
            <div className="space-y-2 rounded-md border border-border bg-muted/20 p-2">
              <label className="block text-xs">
                Grams used
                <input
                  type="number" min={1} max={10000} aria-label="Grams used"
                  value={usedGrams}
                  onChange={(e) => { setUsedGrams(e.target.value); setUsedConfirm(false); }}
                  className="mt-1 h-8 w-full rounded-md border border-border bg-card px-2 text-xs outline-none"
                />
              </label>
              {usedError && <p className="text-[11px] text-risk">{usedError}</p>}
              {!usedConfirm ? (
                <Button
                  size="sm" variant="secondary"
                  onClick={() => {
                    const r = validateUsedG(usedGrams);
                    if (!r.ok) { setUsedError(r.error); return; }
                    setUsedError(null);
                    setUsedConfirm(true);
                  }}
                >
                  Record {usedGrams || "…"} g used
                </Button>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-muted-foreground">
                    Confirm: subtract {usedGrams} g — the new remaining weight will be estimated from what you recorded.
                  </span>
                  <Button size="sm" disabled={busy} onClick={() => confirmMarkUsed(editor.slot)}>Confirm</Button>
                  <Button size="sm" variant="ghost" onClick={() => setUsedConfirm(false)}>Back</Button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
