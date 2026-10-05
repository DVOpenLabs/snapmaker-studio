// Presentation logic for the "Ready now" page.
//
// Free of JSX so the wording rules stay testable. The rules that matter:
//  - "ready" is never said without the amount-checked caveat when the amount was
//    not checked (a visible "Amount not checked" chip),
//  - a different colour of the right material is a prominent note, never a pass,
//  - unknown stays unknown: nothing here turns a missing answer into a claim.

import type { ReadyNowBucket, ReadyNowProject, ReadyNowResult } from "@/api";

/** Display order — what the person can act on first. Not the engine's decision order. */
export const DISPLAY_ORDER: ReadyNowBucket[] = [
  "ready_now", "one_change_away", "needs_preparation", "needs_attention", "cant_determine",
];

export type ReadyNowIcon = "check" | "swap" | "prepare" | "attention" | "unknown";

export const BUCKET_META: Record<ReadyNowBucket, { label: string; icon: ReadyNowIcon; blurb: string }> = {
  ready_now: {
    label: "Ready now", icon: "check",
    blurb: "A suitable spool is loaded for every filament the project declares.",
  },
  one_change_away: {
    label: "One change away", icon: "swap",
    blurb: "A filament has no suitable spool loaded; loading or swapping one fixes it.",
  },
  needs_preparation: {
    label: "Needs preparation", icon: "prepare",
    blurb: "Made for another printer. Studio can prepare a U1 copy.",
  },
  needs_attention: {
    label: "Needs attention", icon: "attention",
    blurb: "Something to resolve first: the bed, toolheads, nozzle, a busy printer or too little filament.",
  },
  cant_determine: {
    label: "Can't determine", icon: "unknown",
    blurb: "Studio does not have enough information to say, and will not guess.",
  },
};

export const READY_NOW_TITLE = "What can I print on my U1 right now?";
export const COLOUR_NOTE = "Prints now, but the loaded colour differs from the project.";
export const AMOUNT_CHIP = "Amount not checked";
export const READY_NOW_FOOTER =
  "Advisory only. Based on projects already in your Studio library, your printer's reported " +
  "state and the filament inventory you have configured. Studio does not change your printer, " +
  "slot mapping or inventory.";
export const DECLARED_NOTE =
  "Matching uses the filaments each project declares, so a project that lists filaments it " +
  "never prints with can look further from ready than it is.";
export const NO_PRINTER_TITLE = "Add your printer's address first";
export const NO_PRINTER_TEXT =
  "Ready now compares your projects with what is loaded on your printer, so it needs the " +
  "printer's address (set it in Printer Hub). Without a printer Studio can still tell you which " +
  "projects need preparation for the U1, but it cannot say anything is ready.";

export interface ReadyNowSection {
  bucket: ReadyNowBucket;
  label: string;
  icon: ReadyNowIcon;
  blurb: string;
  items: ReadyNowProject[];
}

/** Five sections in display order, empty ones included. Items keep the order the
 *  engine returned them in (newest library project first), so grouping is stable. */
export function groupResults(results: ReadyNowProject[] | undefined | null): ReadyNowSection[] {
  const list = results ?? [];
  return DISPLAY_ORDER.map((bucket) => ({
    bucket, ...BUCKET_META[bucket],
    items: list.filter((r) => r.bucket === bucket),
  }));
}

export function confidenceLabel(c: ReadyNowProject["confidence"]): string {
  switch (c) {
    case "confirmed": return "Confirmed";
    case "likely": return "Likely";
    case "informational": return "For information";
    default: return "Unknown";
  }
}

export interface RowChip { id: "amount" | "colour"; label: string; tone: "caution" | "note" }

/** Chips a row must show. Ready without a checked amount always carries one. */
export function rowChips(r: ReadyNowProject): RowChip[] {
  const chips: RowChip[] = [];
  if (r.bucket === "ready_now" && !r.amount_checked) {
    chips.push({ id: "amount", label: AMOUNT_CHIP, tone: "caution" });
  }
  if (r.colour_notes.length > 0) {
    chips.push({ id: "colour", label: "Different colour loaded", tone: "note" });
  }
  return chips;
}

/** The status wording for a row. "Ready now" only stands alone when the amount was checked. */
export function rowStatus(r: ReadyNowProject): string {
  const label = BUCKET_META[r.bucket].label;
  if (r.bucket === "ready_now" && !r.amount_checked) return `${label} — amount not checked`;
  return label;
}

export type RowAction = { id: "open" | "prepare"; label: string };

/** Actions need a file Studio can still open. */
export function rowActions(r: ReadyNowProject): RowAction[] {
  if (r.file_state !== "ok") return [];
  const out: RowAction[] = [{ id: "open", label: "Open project" }];
  if (r.bucket === "needs_preparation") out.push({ id: "prepare", label: "Prepare a U1 copy" });
  return out;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** One honest sentence for the page subtitle. */
export function summarySentence(result: ReadyNowResult | null | undefined, running = false): string {
  if (!result) return running ? "Checking your library…" : "Check your library to see what you can print.";
  const rows = result.results ?? [];
  if (rows.length === 0) return running ? "Checking your library…" : "No projects in your library yet.";
  const n = (b: ReadyNowBucket) => rows.filter((r) => r.bucket === b).length;
  const parts = [`${plural(rows.length, "project", "projects")} checked`];
  if (n("ready_now")) parts.push(`${n("ready_now")} ready now`);
  if (n("one_change_away")) parts.push(`${n("one_change_away")} one change away`);
  if (n("needs_preparation")) parts.push(`${n("needs_preparation")} need${n("needs_preparation") === 1 ? "s" : ""} preparation`);
  if (n("needs_attention")) parts.push(`${n("needs_attention")} need${n("needs_attention") === 1 ? "s" : ""} attention`);
  if (n("cant_determine")) parts.push(`${n("cant_determine")} can't be determined`);
  const capped = result.library_total != null && result.scanned != null && result.library_total > result.scanned;
  return parts.join(" · ") + (capped ? ` (newest ${result.scanned} of ${result.library_total})` : "");
}

export function progressText(p: { done: number; total: number | null } | undefined): string {
  if (!p || p.total == null) return "Reading your library…";
  return `Checked ${p.done} of ${p.total}`;
}
