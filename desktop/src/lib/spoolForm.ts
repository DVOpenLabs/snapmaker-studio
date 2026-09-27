// Pure validation for the spool-note editor. Mirrors the backend's frozen
// error map (A3.6/A4.3) closely enough to give the same words before a round
// trip, but the backend's validation is still authoritative.

export interface SpoolFormInput {
  material: string;
  color?: string; // undefined/never-touched -> never resend; "" -> clear; else set
  colorTouched: boolean;
  colorIsLegacyFreeText?: boolean; // legacy free-text colour shown as-is, never resent unless changed
  startingG: string; // raw text input, "" = not entered
  remainingG: string;
}

export interface SpoolFormErrors {
  material?: string;
  color?: string;
  startingG?: string;
  remainingG?: string;
}

const HEX_RE = /^#[0-9A-Fa-f]{6}$/;
const WEIGHT_MSG = "Weight must be between 0 and 10000 grams.";
const COLOR_MSG = "Colour must be a hex value like #1A2B3C, or empty.";

export type ColorResult =
  | { ok: true; send: undefined } // unchanged: never resend
  | { ok: true; send: "" } // clear
  | { ok: true; send: string } // normalised #RRGGBB
  | { ok: false; error: string };

/** Tri-state clear semantics (A1.4/A3.3): legacy free-text colour is shown as
 *  typed and never resent unless the user actually changes it. */
export function validateColor(color: string | undefined, touched: boolean): ColorResult {
  if (!touched) return { ok: true, send: undefined };
  if (color === undefined || color === "") return { ok: true, send: "" };
  const normalized = color.startsWith("#") ? color : `#${color}`;
  if (!HEX_RE.test(normalized)) return { ok: false, error: COLOR_MSG };
  return { ok: true, send: normalized.toUpperCase() };
}

export type WeightResult = { ok: true; value: number | null } | { ok: false; error: string };

export function validateWeight(raw: string): WeightResult {
  if (raw.trim() === "") return { ok: true, value: null };
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0 || n > 10000) return { ok: false, error: WEIGHT_MSG };
  return { ok: true, value: n };
}

export type UsedGResult = { ok: true; value: number } | { ok: false; error: string };

/** "Record filament used": grams, strictly > 0, <= 10000 (A2.6). */
export function validateUsedG(raw: string): UsedGResult {
  if (raw.trim() === "") return { ok: false, error: WEIGHT_MSG };
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0 || n > 10000) return { ok: false, error: WEIGHT_MSG };
  return { ok: true, value: n };
}

export function validateSpoolForm(input: SpoolFormInput): SpoolFormErrors {
  const errors: SpoolFormErrors = {};
  if (!input.material.trim()) errors.material = "Material is required.";

  const color = validateColor(input.color, input.colorTouched);
  if (!color.ok) errors.color = color.error;

  const starting = validateWeight(input.startingG);
  if (!starting.ok) errors.startingG = starting.error;

  const remaining = validateWeight(input.remainingG);
  if (!remaining.ok) errors.remainingG = remaining.error;

  return errors;
}

export function hasErrors(errors: SpoolFormErrors): boolean {
  return Object.keys(errors).length > 0;
}

function fmtAsOf(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString();
}

/** Quality label to show next to a remaining weight.
 *
 *  `user_confirmed` is a figure someone typed in directly ("entered by you");
 *  `derived` is one Studio worked out from a "Record filament used" entry
 *  ("estimated from what you recorded") — the two are not interchangeable,
 *  and a previous version of this label had them backwards. `tracked` is a
 *  provider's own measurement, never something Studio or the person computed. */
export function remainingLabel(
  remainingG: number | null,
  quality: "tracked" | "derived" | "user_confirmed" | "unknown",
  asOf?: string | null,
): string {
  if (remainingG == null) return "no weight recorded";
  const amount = `${Math.round(remainingG)} g`;
  const date = fmtAsOf(asOf);
  const suffix = date ? ` · ${date}` : "";
  if (quality === "user_confirmed") return `${amount} · entered by you${suffix}`;
  if (quality === "derived") return `${amount} · estimated from what you recorded${suffix}`;
  if (quality === "tracked") return `${amount} · tracked by your provider`;
  return amount;
}

// ---- Building the save request body ------------------------------------------
// Only the fields the user actually touched are ever sent. Sending remaining_g
// unconditionally would let an unrelated edit (say, the vendor) silently
// re-stamp a weight that was never touched — and after "Record filament used"
// resets it to a backend-computed estimate, resending the old typed figure
// would immediately overwrite that estimate with stale grams.

export interface SpoolSaveDraft {
  material: string;
  subtype: string;
  color: string;
  colorTouched: boolean;
  vendor: string;
  startingG: string;
  startingGTouched: boolean;
  remainingG: string;
  remainingGTouched: boolean;
  notes: string;
}

export interface SpoolSaveBody {
  material?: string;
  subtype?: string;
  color?: string;
  vendor?: string;
  starting_g?: number | null;
  remaining_g?: number | null;
  notes?: string;
}

/** Pure request-body builder (D2/D10): weight fields are included only when
 *  `*Touched` is true, so an untouched weight is never re-sent. */
export function buildSpoolSaveBody(draft: SpoolSaveDraft): SpoolSaveBody {
  const body: SpoolSaveBody = {
    material: draft.material.trim(),
    subtype: draft.subtype.trim(),
    vendor: draft.vendor.trim(),
    notes: draft.notes.trim(),
  };
  const color = validateColor(draft.color, draft.colorTouched);
  if (color.ok && color.send !== undefined) body.color = color.send;
  if (draft.startingGTouched) {
    const starting = validateWeight(draft.startingG);
    if (starting.ok) body.starting_g = starting.value;
  }
  if (draft.remainingGTouched) {
    const remaining = validateWeight(draft.remainingG);
    if (remaining.ok) body.remaining_g = remaining.value;
  }
  return body;
}
