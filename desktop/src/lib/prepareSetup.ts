import type { Topology } from "./extTypes";

/**
 * The printer setup a person chose to prepare for, and the rules that decide whether Studio may send it.
 *
 * A selection is one of:
 *   none     no setup chosen: Prepare behaves as it always did (stock four-toolhead U1) and sends nothing.
 *   reading  a read is in flight: nothing is sent and Prepare waits.
 *   ready    a setup the host reported that passes the same structural checks the engine applies. Only this
 *            state ever puts a topology in a request, and it is the very object shown to the person.
 *   unknown  the host did not report a complete setup. Nothing is guessed or filled in.
 *   invalid  the host reported a setup that contradicts itself.
 *   failed   the read itself failed.
 *
 * Every selection carries a `token`. Anything shown or in flight (a preview, a prepared copy, a late read)
 * is kept only while the token it was made under is still the current one.
 */
export type PrepareSetupSelection =
  | { status: "none"; token: number }
  | { status: "reading"; token: number; projectPath: string; label: string }
  | { status: "ready"; token: number; projectPath: string; label: string; topology: Topology; summary: SetupSummary }
  | { status: "unknown" | "invalid" | "failed"; token: number; projectPath: string; label: string; reason: string };

export interface SetupSummary {
  heads: number;
  slots: number;
  lanes: number;
  /** Slots with any reported binding. Counted from the reported bindings, never inferred. */
  boundSlots: number;
  /** Of those, slots bound to a feeder lane. */
  laneBound: number;
  /** Of those, slots bound directly to a toolhead (a printer with no feeder). */
  headBound: number;
  text: string;
}

export const NO_SETUP = (token = 0): PrepareSetupSelection => ({ status: "none", token });

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export type TopologyCheck =
  | { ok: true; topology: Topology }
  | { ok: false; kind: "unknown" | "invalid"; reason: string };

/**
 * Mirror of the engine's own acceptance rule (backend `accepted_logical_slots`), so what the screen calls usable is
 * what the engine will use. The engine stays the authority: a setup it refuses is reported in the copy's warnings.
 */
export function checkTopology(raw: unknown): TopologyCheck {
  const invalid = (reason: string): TopologyCheck => ({ ok: false, kind: "invalid", reason });
  if (!isObj(raw)) return invalid("the host reported no readable setup");
  if (raw.schema_version !== "topology/1") return invalid("the setup is in a format this version does not read");
  const { heads, slots, units, bindings } = raw as Record<string, unknown>;
  if (!Array.isArray(heads) || !Array.isArray(slots) || !Array.isArray(units) || !Array.isArray(bindings)) {
    return invalid("the setup is missing its toolheads, slots, feeders or bindings");
  }
  const headIds = new Set<string>();
  for (const h of heads) {
    if (!isObj(h) || typeof h.id !== "string" || typeof h.index !== "number") return invalid("a toolhead entry is malformed");
    if (headIds.has(h.id)) return invalid("two toolheads share the same id");
    headIds.add(h.id);
  }
  const slotIds = new Set<string>();
  const indexes: number[] = [];
  for (const s of slots) {
    if (!isObj(s) || typeof s.id !== "string" || !Number.isInteger(s.index)) return invalid("a slot entry is malformed");
    if (slotIds.has(s.id)) return invalid("two slots share the same id");
    slotIds.add(s.id);
    indexes.push(s.index as number);
  }
  const laneIds = new Set<string>();
  for (const u of units) {
    if (!isObj(u) || !Array.isArray(u.lanes)) return invalid("a feeder entry is malformed");
    for (const l of u.lanes) {
      if (!isObj(l) || typeof l.id !== "string") return invalid("a lane entry is malformed");
      if (laneIds.has(l.id)) return invalid("two lanes share the same id");
      laneIds.add(l.id);
      if (l.reachable_heads != null) {
        if (!Array.isArray(l.reachable_heads) || l.reachable_heads.some((id) => typeof id !== "string" || !headIds.has(id))) {
          return invalid("a lane reaches a toolhead that is not listed");
        }
      }
    }
  }
  for (const b of bindings) {
    if (!isObj(b) || typeof b.slot_id !== "string" || !slotIds.has(b.slot_id)) return invalid("a binding names a slot that is not listed");
    // A binding targets a feeder lane or, for a printer with no feeder, a toolhead directly (the engine accepts both).
    if (b.target != null && (typeof b.target !== "string" || !(laneIds.has(b.target) || headIds.has(b.target)))) return invalid("a binding names a lane or toolhead that is not listed");
  }
  if (raw.complete !== true || heads.length === 0) {
    return { ok: false, kind: "unknown", reason: "the host did not list every physical toolhead" };
  }
  const sorted = [...indexes].sort((a, b) => a - b);
  if (sorted.length === 0 || sorted.some((n, i) => n !== i)) {
    return { ok: false, kind: "unknown", reason: "the logical slots are missing or not numbered 0 to n-1" };
  }
  return { ok: true, topology: raw as unknown as Topology };
}

export function describeTopology(t: Topology): SetupSummary {
  const lanes = t.units.reduce((n, u) => n + u.lanes.length, 0);
  const laneIds = new Set(t.units.flatMap((u) => u.lanes.map((l) => l.id)));
  const headIds = new Set(t.heads.map((h) => h.id));
  const slotsBoundTo = (ids: Set<string>) => new Set(t.bindings.filter((b) => b.target != null && ids.has(b.target)).map((b) => b.slot_id)).size;
  const laneBound = slotsBoundTo(laneIds), headBound = slotsBoundTo(headIds);
  const boundSlots = new Set(t.bindings.filter((b) => b.target != null).map((b) => b.slot_id)).size;
  // A slot bound straight to a toolhead (a printer with no feeder) is not a feeder-lane binding; the two are reported apart.
  const text = `${plural(t.heads.length, "toolhead", "toolheads")}, ${plural(t.slots.length, "logical slot", "logical slots")}, `
    + `${plural(lanes, "feeder lane", "feeder lanes")}; ${boundSlots} of ${t.slots.length} slots are bound `
    + `(${laneBound} to feeder lanes, ${headBound} directly to toolheads)`;
  return { heads: t.heads.length, slots: t.slots.length, lanes, boundSlots, laneBound, headBound, text };
}

export interface SelectionBase { token: number; projectPath: string; label: string }

/** The host's own words for why it gave no setup, taken from the response; nothing is invented. */
function hostReason(res: unknown): string {
  const read = isObj(res) && isObj(res.read) ? res.read : null;
  const report = isObj(res) && isObj(res.report) ? res.report : null;
  const entry = report && Array.isArray(report.entries) && isObj(report.entries[0]) ? report.entries[0] : null;
  const text = (entry && typeof entry.reason_text === "string" && entry.reason_text)
    || (read && typeof read.reason === "string" && read.reason) || "";
  return text || "the host did not report its setup";
}

export function selectionFromEvaluate(base: SelectionBase, res: unknown): PrepareSetupSelection {
  const raw = isObj(res) ? res.topology : undefined;
  if (raw == null) return { status: "unknown", ...base, reason: hostReason(res) };
  const checked = checkTopology(raw);
  if (!checked.ok) return { status: checked.kind, ...base, reason: checked.reason };
  return { status: "ready", ...base, topology: checked.topology, summary: describeTopology(checked.topology) };
}

export function selectionFromFailure(base: SelectionBase, error: unknown): PrepareSetupSelection {
  const reason = error instanceof Error && error.message ? error.message : "the read failed";
  return { status: "failed", ...base, reason };
}

/** A setup chosen for another project is not this project's: it is treated as no setup, never sent and never shown here. */
export function setupFor(sel: PrepareSetupSelection, projectPath: string): PrepareSetupSelection {
  return sel.status === "none" || sel.projectPath === projectPath ? sel : NO_SETUP(sel.token);
}

/** Why Prepare must not run right now because of the chosen setup, or null when it may (no setup, or a usable one for this project). */
export function prepareBlockedBy(selection: PrepareSetupSelection, projectPath: string): string | null {
  const sel = setupFor(selection, projectPath);
  if (sel.status === "none") return null;
  switch (sel.status) {
    case "ready": return null;
    case "reading": return "Studio is still reading the printer setup. Wait for it to finish, or clear it.";
    default:
      return `The chosen printer setup (${sel.label}) can't be used: ${sel.reason}. Read it again, clear it, or choose Prepare without a setup.`;
  }
}

/** The topology to put in a request: only a ready setup for this very project; otherwise nothing. */
export function topologyToSend(sel: PrepareSetupSelection, projectPath: string): Topology | undefined {
  return sel.status === "ready" && sel.projectPath === projectPath ? sel.topology : undefined;
}

/** One plain sentence for the current selection. Advisory: it never says the project will fit or print. */
export function setupStatusLine(sel: PrepareSetupSelection): string {
  switch (sel.status) {
    case "none": return "No setup chosen. Prepare uses Studio's stock four-toolhead U1 behaviour.";
    case "reading": return `Reading ${sel.label}...`;
    case "ready": return `Selected setup reported by ${sel.label}: ${sel.summary.text}. Whether Prepare applies it depends on the preparation mode; the engine reports what it did.`;
    default: return `${sel.label}: ${sel.reason}.`;
  }
}

/** What the engine reports about the printer setup it was sent: `settings_summary.setup` (backend convert.py / repair.py). */
export interface EngineSetupReport {
  state?: string;
  /** The engine states whether a valid setup was applied: true for Preserve; false for Recommended or a file with nothing per-head. Absent means unknown. */
  applied?: boolean;
  heads?: number;
  slots?: number;
  unbound?: string[];
  reasons?: string[];
  stock_alternative?: string;
  /** The engine's own plain-language cause when `applied` is false (Recommended mode, or a file with nothing per-head). */
  not_applied_reason?: string;
}

export type TopologyOutcome =
  | { state: "not_requested" }
  | { state: "used"; heads: number | null; slots: number | null; unbound: string[] | null }
  | { state: "unused"; heads: number | null; slots: number | null; reason: string | null }
  | { state: "blocked"; reasons: string[]; alternative: string | null }
  | { state: "unknown" };

const count = (v: unknown): number | null => (typeof v === "number" && Number.isInteger(v) && v >= 0 ? v : null);
const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/**
 * What the engine says about the setup it was sent. Choosing a setup is not proof the engine used it, so each answer comes only
 * from the engine's own `settings_summary.setup` (backend convert.py / repair.py):
 *   state "invalid" (or a blocked result)  -> blocked: nothing was written; its reasons and the stock alternative are carried through
 *   state "valid" with applied === false   -> unused: read but not applied; not_applied_reason says why
 *   state "valid" with applied === true    -> used: the engine echoes the heads, slots and unbound slots it applied
 *   state "valid" with no applied field   -> unknown (an engine that does not say)
 * Anything else, including an absent field, is unknown. A chosen setup is never success by default.
 */
export function topologyOutcome(requested: boolean, result: {
  blocked?: boolean; settings_summary?: { setup?: EngineSetupReport | null } | null;
} | null | undefined, expected?: { heads: number; slots: number }): TopologyOutcome {
  if (!requested) return { state: "not_requested" };
  const rep = result?.settings_summary?.setup;
  const blocked = (): TopologyOutcome => ({
    state: "blocked", reasons: strings(rep?.reasons), alternative: typeof rep?.stock_alternative === "string" ? rep.stock_alternative : null,
  });
  if (!rep || typeof rep !== "object") return result?.blocked ? blocked() : { state: "unknown" };
  if (rep.state === "invalid" || result?.blocked) return blocked();
  if (rep.state !== "valid") return { state: "unknown" };
  const heads = count(rep.heads), slots = count(rep.slots);
  // The engine echoing a different shape than the one sent is not confirmation that this setup was the one used.
  if (expected && ((heads !== null && heads !== expected.heads) || (slots !== null && slots !== expected.slots))) return { state: "unknown" };
  if (rep.applied === false) return { state: "unused", heads, slots, reason: typeof rep.not_applied_reason === "string" ? rep.not_applied_reason : null };
  // Only an explicit applied === true is a confirmed use; a report with no applied field (an older engine) is unknown.
  if (rep.applied !== true) return { state: "unknown" };
  return { state: "used", heads, slots, unbound: Array.isArray(rep.unbound) ? strings(rep.unbound) : null };
}

const shape = (heads: number | null, slots: number | null) =>
  heads !== null && slots !== null ? ` (${heads} ${heads === 1 ? "toolhead" : "toolheads"}, ${slots} logical ${slots === 1 ? "slot" : "slots"})` : "";

export function topologyOutcomeLine(o: TopologyOutcome): string | null {
  switch (o.state) {
    case "used": {
      const u = o.unbound ?? [];
      const unbound = u.length ? ` ${u.length} ${u.length === 1 ? "slot has" : "slots have"} no reported feeder lane: ${u.join(", ")}.` : "";
      return `The engine reports it used this printer setup${shape(o.heads, o.slots)}.${unbound}`;
    }
    case "unused": return `The engine read this printer setup${shape(o.heads, o.slots)} but did not apply it. ${o.reason ?? "The engine gave no reason."}`;
    case "blocked": return `The engine could not use this printer setup, so nothing was prepared.${o.reasons.length ? ` ${o.reasons.join("; ")}.` : ""}${o.alternative ? ` ${o.alternative}` : ""}`;
    case "unknown": return "The engine did not say whether it used this printer setup, so Studio cannot confirm it did.";
    default: return null;
  }
}

/** Only a confirmed use reads as success; unused, blocked and unknown all read as a problem. */
export const outcomeIsGood = (o: TopologyOutcome): boolean => o.state === "used";
