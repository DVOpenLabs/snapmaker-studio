// Project Materials: the wire types, and the small amount of logic the screen needs.
//
// What this file does NOT do: rank spools, measure colour distance, judge whether a spool holds
// enough filament, or word a reason. The engine does all of that and sends the order and the
// sentences; the screen shows them as they arrive. What is here is the person's side of it:
// which spool and which installed preset they picked, what still needs their confirmation, and
// the request that carries those choices to Prepare.

import type { ProviderSpool } from "@/api";
import { weightStatus } from "@/lib/spoolPicker";

export type PresetStatus = "proven" | "needs_confirmation" | "no_match";

export interface MaterialReason {
  code: string;
  /** Written by the engine. Shown verbatim. */
  text: string;
  data?: Record<string, unknown>;
}

export interface MaterialMapping {
  status: PresetStatus;
  match_source: "saved_spool" | "saved_signature" | "exact_name" | "manual" | "none" | string;
  preset_name: string | null;
  base_name: string | null;
  /** The saved row exactly as stored, when this preset came from a saved mapping. */
  saved?: { preset_base: string; ref: string | null; fingerprint: string | null };
  reason: string;
  candidates: string[];
  stale: boolean;
  catalog_missing?: boolean;
  /** Where the preset the engine resolved lives: Orca's own, or one the person made. */
  source?: "system" | "user" | null;
  /** Pins one of the person's preset files; null for a system preset. */
  ref?: string | null;
  proof?: string | null;
  /** Which version of the preset this is, so a say-so given for it cannot be applied to a replacement. */
  fingerprint?: string | null;
  /** True for one of the person's own presets Studio could not itself tell is for the U1: usable only if they say so. */
  confirmable?: boolean;
  /** When a name is ambiguous, each installed preset that claims it. */
  choices?: { ref: string; name: string; source: string; location: string | null; proof: string }[];
}

export interface MaterialCandidate {
  provider: string;
  spool_id: number | string;
  rank: number;
  label: string;
  vendor: string | null;
  material: string | null;
  subtype: string | null;
  /** The engine's own key for this kind of spool; present on everything the engine returns. */
  signature?: { vendor: string; family: string; subtype: string };
  colour: string | null;
  color_name: string | null;
  remaining_g: number | null;
  remaining_quality: string | null;
  loaded_slot: number | null;
  slicer_filament: string | null;
  mapping: MaterialMapping;
  reasons: MaterialReason[];
}

export interface MaterialSuggestion {
  status: PresetStatus;
  preset_name: string;
  base_name: string;
  reason: string;
}

export interface MaterialSlot {
  slot: number; // 0-based on the wire; shown 1-based
  material: string | null;
  family: string | null;
  subtype: string | null;
  colour: string | null;
  required_g: number | null;
  required_source: string | null;
  settings_id: string | null;
  vendor: string | null;
  declared_keys: string[];
  candidates: MaterialCandidate[];
  candidate_count: number;
  close_call: boolean;
  selected: null;
  current_preset: { status: PresetStatus; reason: string } | null;
  suggestion: MaterialSuggestion | null;
}

export interface GuardConflict {
  key: string;
  preset: string;
  slots: number[];
  declared_in: number[];
  values: Record<string, string | null>;
}

export interface MaterialGuard {
  applies: boolean;
  blocking: boolean;
  conflicts: GuardConflict[];
  shared: { preset: string; slots: number[] }[];
  warnings: { preset: string; slots: number[]; keys: string[]; text: string }[];
  resolution: string | null;
  source_conflicts?: GuardConflict[];
  removed_by_mode?: GuardConflict[];
  mode?: string;
}

export interface ProjectMaterialsAnalysis {
  schema: string;
  supported: boolean;
  reason?: string;
  nozzle?: string;
  catalog?: { available: boolean; source: { profiles_version?: string | null } | null; fingerprint: string | null };
  provider?: { kind: string; available: boolean; error_code: string | null } | null;
  slots?: MaterialSlot[];
  guard?: MaterialGuard;
}

export interface MaterialPreset {
  base_name: string;
  preset_name: string;
  vendor: string | null;
  filament_type: string | null;
  fingerprint: string;
  /** "system" (Orca's own) or "user" (made by the person). Absent means system. */
  source?: "system" | "user";
  location?: string | null;
  /** Pins one user preset file; null for a system preset. */
  ref?: string | null;
  proof?: string | null;
  /** "proven" when Studio can tell it fits the U1; otherwise the person must say so. Absent means proven. */
  status?: PresetStatus;
  reason?: string | null;
  parent?: string | null;
  /** More than one installed preset has this name, so the source is what tells them apart. */
  ambiguous?: boolean;
}

export interface MaterialPresetList {
  available: boolean;
  nozzle: string;
  presets: MaterialPreset[];
}

/** What Prepare is sent for one slot. Spool facts are display data for the report; the engine
 *  reduces them to identity fields and never writes them into the project. */
export interface MaterialSelection {
  slot: number;
  preset: string | null;
  colour: string | null;
  /** Which installed preset when a name is ambiguous. */
  source?: "system" | "user";
  ref?: string;
  /** The person said this user preset is a U1 preset (Studio could not tell). */
  accept_unproven?: boolean;
  /** The preset they were shown when they said so; the engine refuses if it has changed since. */
  fingerprint?: string;
  spool?: {
    provider: string;
    id: number | string;
    vendor: string | null;
    material: string | null;
    subtype: string | null;
    colour: string | null;
    color_name: string | null;
    slicer_filament: string | null;
  };
}

export interface MappingRequest {
  scope: "spool" | "signature";
  provider: string;
  spool_id?: number | string;
  vendor?: string | null;
  material?: string | null;
  subtype?: string | null;
  preset: string;
  nozzle: string;
  origin: "manual" | "exact_name";
  source?: "system" | "user";
  ref?: string;
  accept_unproven?: boolean;
  fingerprint?: string;
}

// --- forgetting a saved mapping ------------------------------------------------------------------

/** What identifies one saved mapping to the engine's remove route. */
export type ForgetRequest = Pick<MappingRequest, "scope" | "provider" | "spool_id" | "vendor" | "material" | "subtype"> & { expect_preset_base?: string; expect_ref?: string; expect_fingerprint?: string };

/** Which kind of saved mapping a candidate's preset came from, if it came from one. */
export function savedScope(c: MaterialCandidate): "spool" | "signature" | null {
  const source = c.mapping.match_source;
  return source === "saved_spool" ? "spool" : source === "saved_signature" ? "signature" : null;
}

/** The request that removes exactly the mapping this candidate's preset came from. Null when it came from none. */
export function forgetRequest(c: MaterialCandidate): ForgetRequest | null {
  const scope = savedScope(c);
  if (!scope) return null;
  // The preset the person was shown: the engine forgets the mapping only if it still names it.
  const saved = c.mapping.saved;
  const expect = saved
    ? { expect_preset_base: saved.preset_base, ...(saved.ref ? { expect_ref: saved.ref } : {}), ...(saved.fingerprint ? { expect_fingerprint: saved.fingerprint } : {}) }
    : {};
  return scope === "spool"
    ? { scope, provider: c.provider, spool_id: c.spool_id, ...expect }
    : { scope, provider: c.provider, vendor: c.vendor, material: c.material, subtype: c.subtype, ...expect };
}

// The engine's own normalisation of a spool kind: whitespace collapsed, case folded.
const fold = (v: string | null | undefined) => (v ?? "").split(/\s+/).filter(Boolean).join(" ").toLowerCase().replace(/ß/g, "ss");
const same = (a: string | null | undefined, b: string | null | undefined) => fold(a) === fold(b);
/** Whether two spools are the same kind. The engine's own key decides; the local fold is only for data without one. */
const sameKind = (a: MaterialCandidate, b: MaterialCandidate) =>
  a.signature && b.signature
    ? a.signature.vendor === b.signature.vendor && a.signature.family === b.signature.family && a.signature.subtype === b.signature.subtype
    : same(a.vendor, b.vendor) && same(a.material, b.material) && same(a.subtype, b.subtype);

/**
 * The slots whose choice rests on the mapping a candidate came from, and so lose it when that mapping is forgotten: the
 * chosen spool got its preset from this very kind of saved mapping, and the slot still holds that preset. A slot whose
 * preset the person changed, or whose spool has a mapping of its own, does not depend on it and is left alone.
 */
export function slotsCoveredBy(choices: Choices, c: MaterialCandidate): number[] {
  const scope = savedScope(c);
  if (!scope) return [];
  return Object.entries(choices)
    .filter(([, choice]) => {
      const s = choice.spool;
      if (!s || s.provider !== c.provider) return false;
      if (savedScope(s) !== scope) return false;
      const offered = s.mapping.base_name ?? s.mapping.preset_name;
      if (!choice.preset || choice.preset.name !== offered || (choice.preset.fingerprint ?? null) !== (s.mapping.fingerprint ?? null)) return false;
      return scope === "spool"
        ? String(s.spool_id) === String(c.spool_id)
        : sameKind(s, c);
    })
    .map(([slot]) => Number(slot))
    .sort((a, b) => a - b);
}

/** Whether the spool a slot chose still has a saved mapping of the same kind after the project was read again. */
export function stillSaved(a: ProjectMaterialsAnalysis, c: MaterialCandidate, chosen: MaterialCandidate | null): boolean {
  if (!chosen) return true;
  const scope = savedScope(c);
  return (a.slots ?? []).some((sl) => sl.candidates.some((k) =>
    k.provider === chosen.provider && String(k.spool_id) === String(chosen.spool_id) && savedScope(k) === scope));
}

/** The words of the confirmation. The engine decides nothing here; these describe only what the control does. */
export function forgetWording(c: MaterialCandidate): { title: string; body: string; details: string[] } {
  const preset = c.mapping.base_name ?? c.mapping.preset_name ?? "the saved preset";
  const kind = [c.vendor, materialText(c)].filter(Boolean).join(" ");
  const unchanged = "Your spool inventory, your Orca presets and this project are not changed. You can choose a preset for it again at any time.";
  if (savedScope(c) === "signature") {
    return {
      title: "Forget the saved mapping for similar spools?",
      body: `Studio will no longer use the mapping saved for every ${kind || "such"} spool, which names “${preset}”. A spool that has a mapping of its own keeps it. ${unchanged}`,
      details: [`Spools: ${kind || "similar spools"}`, `Saved preset: ${preset}`],
    };
  }
  return {
    title: "Forget the saved mapping for this spool?",
    body: `Studio will no longer use the mapping saved for this spool, which names “${preset}”. A mapping saved for similar spools, if there is one, still applies. ${unchanged}`,
    details: [`Spool: ${[kind, `#${c.spool_id}`].filter(Boolean).join(" ")}`, `Saved preset: ${preset}`],
  };
}

/** The exact sentence for a slot that keeps its own filament. */
export const KEEP_OWN_NOTICE =
  "Studio keeps the project's existing filament identity. If Snapmaker Orca does not recognize that preset, Orca may treat it as a Customized Preset and rename it.";

export const STATUS_LABEL: Record<PresetStatus, string> = {
  proven: "Proven",
  needs_confirmation: "Needs confirmation",
  no_match: "No match",
};

export const MATCH_SOURCE_LABEL: Record<string, string> = {
  saved_spool: "Saved for this spool",
  saved_signature: "Saved for similar spools",
  exact_name: "Named by the provider",
  manual: "Chosen by you",
  none: "Not matched",
};

// --- the person's choices -------------------------------------------------------------------

export type RememberMode = "off" | "spool" | "signature";

export interface PresetChoice {
  name: string;
  /** A preset taken from a remembered mapping is already confirmed. One the provider merely names, or the engine merely suggests, is not until the person says so. */
  confirmed: boolean;
  source?: "system" | "user";
  ref?: string;
  /** One of the person's own presets that Studio could not tell is for the U1: it is used only once they confirm it. */
  needsSayso?: boolean;
  /** The engine's own words for why it needs their say-so. */
  note?: string | null;
  /** Which version of the preset they were shown. */
  fingerprint?: string | null;
}

export interface SlotChoice {
  spool: MaterialCandidate | null;
  preset: PresetChoice | null;
  keepOwn: boolean;
  remember: RememberMode;
}

export type Choices = Record<number, SlotChoice>;

export const emptyChoice: SlotChoice = { spool: null, preset: null, keepOwn: false, remember: "off" };

export type ChoiceAction =
  | { type: "chooseSpool"; slot: number; spool: MaterialCandidate }
  | { type: "clearSpool"; slot: number }
  | { type: "pickPreset"; slot: number; name: string; source?: "system" | "user"; ref?: string | null; unproven?: boolean; note?: string | null; fingerprint?: string | null }
  | { type: "confirmPreset"; slot: number }
  | { type: "clearPreset"; slot: number }
  | { type: "keepOwn"; slot: number }
  | { type: "remember"; slot: number; mode: RememberMode }
  | { type: "discardSlots"; slots: number[] }
  | { type: "reset" };

export function choiceReduce(state: Choices, action: ChoiceAction): Choices {
  if (action.type === "reset") return {};
  if (action.type === "discardSlots") {
    const next = { ...state };
    for (const slot of action.slots) delete next[slot];
    return next;
  }
  const current = state[action.slot] ?? emptyChoice;
  const put = (next: SlotChoice): Choices => ({ ...state, [action.slot]: next });
  switch (action.type) {
    case "chooseSpool": {
      // Picking a spool is the person's act. The preset the engine already has for it is offered
      // along with it: confirmed when they confirmed it earlier, awaiting them otherwise.
      const m = action.spool.mapping;
      // base_name is the installed preset the engine resolved; an ambiguous match has none and gets no preset.
      const name = m.base_name ?? m.preset_name;
      const pin = { source: (m.source ?? undefined) as "system" | "user" | undefined, ref: m.ref ?? undefined,
                    fingerprint: m.fingerprint ?? null };
      // A name more than one installed preset claims has no single preset to offer; the person picks one by its source.
      if ((m.choices?.length ?? 0) > 1) return put({ spool: action.spool, preset: null, keepOwn: false, remember: "off" });
      // A remembered mapping the person confirmed (even one they said was a U1 preset) stays confirmed; a
      // preset the engine could not prove, or the provider merely names, waits for them.
      const preset: PresetChoice | null =
        name && m.status === "proven" ? { name, confirmed: true, ...pin, needsSayso: m.proof === "user_confirmed" }
        : name && m.status === "needs_confirmation" ? { name, confirmed: false, ...pin, needsSayso: !!m.confirmable, note: m.reason }
        : null;
      return put({ spool: action.spool, preset, keepOwn: false, remember: "off" });
    }
    case "clearSpool":
      return put({ ...current, spool: null, remember: "off", preset: current.preset?.confirmed ? current.preset : null });
    case "pickPreset":
      // Choosing from the installed list is the confirmation - except for one of the person's own presets that
      // Studio could not tell is for the U1: that needs their explicit say-so first.
      return put({ ...current, keepOwn: false, remember: "off", preset: {
        name: action.name, confirmed: !action.unproven, source: action.source, ref: action.ref ?? undefined,
        needsSayso: !!action.unproven, note: action.note ?? null, fingerprint: action.fingerprint ?? null } });
    case "confirmPreset":
      return current.preset ? put({ ...current, preset: { ...current.preset, confirmed: true } }) : state;
    case "clearPreset":
      return put({ ...current, preset: null, keepOwn: false, remember: "off" });
    case "keepOwn":
      return put({ ...current, preset: null, keepOwn: true, remember: "off" });
    case "remember":
      return put({ ...current, remember: action.mode });
  }
}

/** Slots whose preset is waiting for the person to confirm it. Prepare is not offered until none are. */
export function unconfirmedSlots(choices: Choices): number[] {
  return Object.entries(choices)
    .filter(([, c]) => c.preset && !c.preset.confirmed && !c.keepOwn)
    .map(([slot]) => Number(slot))
    .sort((a, b) => a - b);
}

/** Whether Project Materials holds anything that a one-click Prepare elsewhere on the page would drop: a choice that
 *  will be sent, or one still waiting for the person to confirm it. */
export function holdsChoices(choices: Choices): boolean {
  return buildSelections(choices).length > 0 || unconfirmedSlots(choices).length > 0;
}

/** The request Prepare (and its dry-run review) is sent. Only what the person has chosen and confirmed. */
export function buildSelections(choices: Choices): MaterialSelection[] {
  const out: MaterialSelection[] = [];
  for (const [key, c] of Object.entries(choices)) {
    const preset = !c.keepOwn && c.preset?.confirmed ? c.preset.name : null;
    const colour = c.spool?.colour ?? null;
    if (!preset && !colour) continue;
    const sel: MaterialSelection = { slot: Number(key), preset, colour };
    if (preset && c.preset) {
      if (c.preset.source) sel.source = c.preset.source;
      if (c.preset.ref) sel.ref = c.preset.ref;
      if (c.preset.needsSayso) sel.accept_unproven = true;
      // The version the person was shown, for every preset: one replaced since is refused, not silently used.
      if (c.preset.fingerprint) sel.fingerprint = c.preset.fingerprint;
    }
    if (c.spool) {
      sel.spool = {
        provider: c.spool.provider, id: c.spool.spool_id, vendor: c.spool.vendor,
        material: c.spool.material, subtype: c.spool.subtype, colour: c.spool.colour,
        color_name: c.spool.color_name, slicer_filament: c.spool.slicer_filament,
      };
    }
    out.push(sel);
  }
  return out.sort((a, b) => a.slot - b.slot);
}

/** The same installed record, not merely the same name: two presets of one name are different choices. */
export function samePreset(preset: PresetChoice, m: MaterialMapping): boolean {
  if (!m.base_name || preset.name !== m.base_name) return false;
  return !m.ref || !preset.ref || m.ref === preset.ref;
}

/** Whether offering to remember this pair makes sense: a spool and a confirmed preset, and not
 *  a mapping that is already saved for exactly that preset. */
export function canRemember(choice: SlotChoice): boolean {
  if (!choice.spool || !choice.preset?.confirmed || choice.keepOwn) return false;
  const m = choice.spool.mapping;
  const saved = m.match_source === "saved_spool" || m.match_source === "saved_signature";
  const same = m.status === "proven" && samePreset(choice.preset, m);
  return !(saved && same);
}

/** Mappings to save, built only from slots where the person ticked "Remember" - and only when they go on to prepare. */
export function mappingRequests(choices: Choices, nozzle: string): MappingRequest[] {
  const out: MappingRequest[] = [];
  for (const c of Object.values(choices)) {
    if (c.remember === "off" || !canRemember(c) || !c.spool || !c.preset) continue;
    const origin = c.spool.mapping.match_source === "exact_name" ? "exact_name" : "manual";
    const pin: Partial<MappingRequest> = {};
    if (c.preset.source) pin.source = c.preset.source;
    if (c.preset.ref) pin.ref = c.preset.ref;
    if (c.preset.needsSayso) pin.accept_unproven = true;
    if (c.preset.fingerprint) pin.fingerprint = c.preset.fingerprint;
    out.push(c.remember === "spool"
      ? { scope: "spool", provider: c.spool.provider, spool_id: c.spool.spool_id, preset: c.preset.name, nozzle, origin, ...pin }
      : { scope: "signature", provider: c.spool.provider, vendor: c.spool.vendor, material: c.spool.material,
          subtype: c.spool.subtype, preset: c.preset.name, nozzle, origin, ...pin });
  }
  return out;
}

// --- showing what the engine sent --------------------------------------------------------------

export function slotNumber(slot: number): number {
  return slot + 1;
}

function cap(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

export function colourWord(c: { color_name: string | null }): string | null {
  const name = (c.color_name ?? "").trim();
  return name ? cap(name) : null;
}

export function materialText(c: { material: string | null; subtype: string | null }): string {
  return [c.material, c.subtype].filter(Boolean).join(" ");
}

/** "412 g tracked" / "weight unknown" - the same words the spool list uses. */
export function amountText(c: { remaining_g: number | null; remaining_quality: string | null }): string {
  return weightStatus({ id: "", label: "", remaining_g: c.remaining_g, remaining_quality: c.remaining_quality } as ProviderSpool);
}

export function presetStatusFor(c: SlotChoice, slot: MaterialSlot): PresetStatus | null {
  if (c.keepOwn) return null;
  if (c.preset) return c.preset.confirmed ? "proven" : "needs_confirmation";
  if (c.spool) return c.spool.mapping.status;
  return slot.suggestion ? slot.suggestion.status : null;
}

/** "Yoopai PLA+ - User preset": what tells two presets of one name apart. */
export function presetSourceLabel(p: { source?: string | null }): string {
  return p.source === "user" ? "User preset" : "System preset";
}

/** Filter the installed-preset list by what the person typed. Every word must appear somewhere. */
export function filterPresets(presets: MaterialPreset[], query: string): MaterialPreset[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return presets;
  return presets.filter((p) => {
    const hay = `${p.base_name} ${p.vendor ?? ""} ${p.filament_type ?? ""} ${presetSourceLabel(p)}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** The engine's own words for why Prepare stopped: the guard's resolution and its first error. Nothing is added. */
export function blockedFacts(result: { blocked?: boolean; errors?: string[]; settings_summary?: { project_materials?: { guard?: MaterialGuard | null } } }):
  { conflicts: GuardConflict[]; resolution: string | null; message: string | null } | null {
  if (!result.blocked) return null;
  const guard = result.settings_summary?.project_materials?.guard;
  return {
    conflicts: guard?.conflicts ?? [],
    resolution: guard?.resolution ?? null,
    message: result.errors?.[0] ?? null,
  };
}
