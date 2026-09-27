// Pure derivation of the "Nozzles · for <host>" table from a NozzleStatus
// response. The backend already computed source/conflict/out_of_range per
// toolhead (frozen contract); this only turns that into plain-language rows
// and never re-derives precedence itself.
import type { NozzleStatus, NozzleToolhead } from "@/api";

export type NozzleRowStatus = "reported_live" | "confirmed" | "unknown" | "conflict" | "out_of_range";

export interface NozzleRow {
  /** 1-based, as printed on the U1. Backend toolheads are 0-based. */
  toolhead: number;
  diameterLabel: string;
  sourceLabel: string;
  status: NozzleRowStatus;
  statusLabel: string;
  updateLabel: string | null;
  removeLabel: string | null;
  removable: boolean;
}

function fmtDiameter(d: number | null): string {
  return d == null ? "—" : `${d} mm`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString();
}

function deriveRow(t: NozzleToolhead): NozzleRow {
  const toolhead = t.toolhead + 1;

  if (t.out_of_range) {
    return {
      toolhead,
      diameterLabel: fmtDiameter(t.confirmed ?? t.diameter),
      sourceLabel: t.source === "user" ? `You · ${fmtDate(t.confirmed_at)}` : "—",
      status: "out_of_range",
      statusLabel: `Toolhead ${toolhead} isn't reported by this printer — note kept for removal`,
      updateLabel: null,
      removeLabel: "Remove my note",
      removable: true,
    };
  }

  if (t.conflict) {
    return {
      toolhead,
      diameterLabel: fmtDiameter(t.diameter),
      sourceLabel: "Printer",
      status: "conflict",
      statusLabel:
        `You noted ${fmtDiameter(t.confirmed)} · printer reports ${fmtDiameter(t.diameter)} — ` +
        `Studio uses the printer's reading`,
      updateLabel: t.diameter != null ? `Update my note to ${t.diameter}` : null,
      removeLabel: "Remove my note",
      removable: true,
    };
  }

  if (t.source === "printer") {
    return {
      toolhead, diameterLabel: fmtDiameter(t.diameter), sourceLabel: "Printer",
      status: "reported_live", statusLabel: "Reported live",
      updateLabel: null, removeLabel: null, removable: false,
    };
  }

  if (t.source === "user") {
    return {
      toolhead, diameterLabel: fmtDiameter(t.diameter), sourceLabel: `You · ${fmtDate(t.confirmed_at)}`,
      status: "confirmed", statusLabel: "Confirmed by you",
      updateLabel: null, removeLabel: "Remove my note", removable: true,
    };
  }

  return {
    toolhead, diameterLabel: "—", sourceLabel: "—",
    status: "unknown", statusLabel: "Unknown — tell Studio",
    updateLabel: null, removeLabel: null, removable: false,
  };
}

export function nozzleRows(status: NozzleStatus | null): NozzleRow[] {
  if (!status) return [];
  return status.toolheads.map(deriveRow);
}

/** Row count for the table header: the live list's length when the printer
 *  answered, else the profile/unknown toolhead_count with its source label —
 *  never truncated, repeated or inferred (plan D-6). */
export function rowCountLabel(status: NozzleStatus | null): { count: number; sourceLabel: string } | null {
  if (!status) return null;
  if (status.live && status.live.length > 0) {
    return { count: status.live.length, sourceLabel: "counted from your printer" };
  }
  if (status.toolhead_count != null) {
    const sourceLabel =
      status.toolhead_count_source === "profile"
        ? "from the U1 profile — connect the printer to confirm"
        : "unknown";
    return { count: status.toolhead_count, sourceLabel };
  }
  return { count: status.toolheads.length, sourceLabel: "unknown" };
}

export function countMismatchNote(status: NozzleStatus | null): string | null {
  if (!status || !status.count_mismatch) return null;
  return "Studio noticed a different number of toolheads than expected — showing what your printer reports.";
}

export function hasAnyConflict(status: NozzleStatus | null): boolean {
  return !!status?.toolheads.some((t) => t.conflict);
}

/** Whether to show the "No nozzle size reported…" banner — informational
 *  only, shown ABOVE the editable rows, never instead of them (D4). The
 *  backend now always returns a row per known toolhead (profile count when
 *  offline), so this is no longer "rows.length === 0". */
export function showsNothingReportedBanner(status: NozzleStatus | null): boolean {
  if (!status) return false;
  // N12: `live_error: "not_checked"` means "not probed yet" (the instant
  // snapshot confirm/clear now return, or the brief window before a
  // follow-up live fetch lands) — not "the printer has nothing to report".
  // Flashing this banner in that window on an otherwise-reachable printer
  // was the exact regression: "Confirmed by you" with no conflict row and no
  // live toolheads, until a manual Refresh.
  if (status.live_error === "not_checked") return false;
  const rows = nozzleRows(status);
  return !status.reachable || rows.every((r) => r.status === "unknown");
}

// ---- Building the /nozzles/confirm request body ------------------------------
// Every mutation sends an explicit, fully-built array derived straight from the
// last-known status — never a value assembled from component state at click
// time, which is exactly the race D3 fixes: `setDraft` then reading `draft` in
// the same tick is not guaranteed to see the update before the request goes
// out. These also carry every stored position, including ones beyond the
// current live/profile count, so "Save" never silently drops an out-of-range
// note (D7) — only an explicit remove does.

/** The stored/confirmed diameter for every known toolhead position, indexed
 *  by the row's own `toolhead` number — NOT by row position. The backend
 *  omits an out_of_range row whose stored value is null, so `status.toolheads`
 *  can have gaps (stored [0.4,0.4,0.4,0.4,null,0.3] with count 4 arrives as
 *  rows for toolheads 0,1,2,3,5 only, toolhead 4 entirely absent). Mapping
 *  the N returned rows to sequential array positions would silently shift
 *  toolhead 5's value into slot 4 on the next save (Opus follow-up). The
 *  array is padded with `null` up to at least one past the highest toolhead
 *  number seen, so a gap stays a gap and every value stays at its own index. */
export function diametersFromStatus(status: NozzleStatus): (number | null)[] {
  const maxToolhead = status.toolheads.reduce((max, t) => Math.max(max, t.toolhead), -1);
  const length = Math.max(maxToolhead + 1, status.toolheads.length);
  const arr: (number | null)[] = new Array(length).fill(null);
  for (const t of status.toolheads) {
    arr[t.toolhead] = t.confirmed;
  }
  return arr;
}

/** The full array to send for "Save": the stored value everywhere the user
 *  didn't touch a row, the drafted choice everywhere they did. `draftFor`
 *  returns "" for an untouched row, a diameter string, or "not_sure". */
export function diametersForSaveAll(
  status: NozzleStatus, draftFor: (toolhead0: number) => string,
): (number | null)[] {
  return diametersFromStatus(status).map((stored, i) => {
    const v = draftFor(i);
    if (v === "") return stored;
    return v === "not_sure" ? null : Number(v);
  });
}

/** "Update my note to X": every other position keeps its stored value. */
export function diametersForUpdate(
  status: NozzleStatus, toolhead1: number, value: number,
): (number | null)[] {
  const arr = diametersFromStatus(status);
  arr[toolhead1 - 1] = value;
  return arr;
}

/** "Remove my note": every other position keeps its stored value; this one
 *  goes back to unknown. Array length is never touched — an earlier attempt
 *  to shorten the array by popping trailing nulls (CodeRabbit PR #41 #2)
 *  could delete a NEIGHBOURING toolhead's own stored "not sure" (null)
 *  record just because it was also trailing and null, and still couldn't
 *  remove a non-trailing out-of-range note at all (Sol follow-up block).
 *  The backend is instead being changed so an out_of_range position whose
 *  stored value is null produces no row at all — so simply nulling the
 *  target position here is sufficient, for any position, trailing or not. */
export function diametersForRemove(status: NozzleStatus, toolhead1: number): (number | null)[] {
  const arr = diametersFromStatus(status);
  arr[toolhead1 - 1] = null;
  return arr;
}

// ---- Printer Hub's one-line nozzle summary -----------------------------------
// The backend now always returns profile rows even offline, so the previous
// "rows.length === 0 -> not reported" branch almost never fires; an
// all-unknown offline printer instead produced "—, —, — · from printer",
// attributing values nobody reported to the printer (CodeRabbit PR #41 #4).
// The source word is now derived honestly from what each row actually is.

const SOURCE_WORDS = { printer: "from printer", you: "from you", unknown: "not reported" } as const;

function nozzleSourceSummary(rows: NozzleRow[]): string {
  const present = new Set<keyof typeof SOURCE_WORDS>();
  for (const r of rows) {
    if (r.status === "reported_live") present.add("printer");
    else if (r.status === "confirmed") present.add("you");
    else present.add("unknown"); // "unknown" only — out_of_range is excluded upstream
  }
  if (present.size === 1) return SOURCE_WORDS[[...present][0]];
  const order: (keyof typeof SOURCE_WORDS)[] = ["printer", "you", "unknown"];
  // Never "some from unknown" (Opus P1 follow-up) — "not reported" already
  // reads correctly standing alone, so it does here too.
  return order.filter((w) => present.has(w)).map((w) => `some ${SOURCE_WORDS[w]}`).join(", ");
}

/** The Printer Hub's "Nozzle sizes: ..." line. Pure so it's testable without
 *  a DOM (CodeRabbit PR #41 #4). Out-of-range notes are excluded entirely
 *  (Opus P2 follow-up) — they're a leftover, removable note about a toolhead
 *  the printer doesn't currently have, not a "nozzle size" to summarise
 *  alongside the ones that are; they stay visible (and removable) only in
 *  the Settings table. */
export function nozzleSummaryLine(status: NozzleStatus | null): string {
  const rows = nozzleRows(status).filter((r) => r.status !== "out_of_range");
  if (rows.length === 0) return "Nozzle sizes: not reported";
  if (rows.every((r) => r.status === "unknown")) {
    return "Nozzle sizes: not reported — confirm in Settings";
  }
  const sizes = rows.map((r) => r.diameterLabel).join(", ");
  const label = rows.some((r) => r.status === "conflict")
    ? "conflict — printer wins"
    : nozzleSourceSummary(rows);
  return `Nozzle${rows.length === 1 ? "" : "s"}: ${sizes} · ${label}`;
}
