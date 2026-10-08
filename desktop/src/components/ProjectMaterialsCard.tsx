import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Loader2, Layers, AlertTriangle, Info, Check } from "lucide-react";
import {
  confirmMaterialMapping, convert, materialPresets, projectMaterials, projectMaterialsInventory,
  type ConversionResult, type PrepareMode, type ProjectMaterialsSummary,
} from "@/api";
import SlotInventoryPicker, { INVENTORY_COPY } from "@/components/SlotInventoryPicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { colorName } from "@/lib/plateRemapWizard";
import {
  KEEP_OWN_NOTICE, MATCH_SOURCE_LABEL, STATUS_LABEL, amountText, blockedFacts, buildSelections, canRemember,
  SPOOL_WITHOUT_PRESET, SPOOL_WITHOUT_PRESET_NONE_EXISTING, choiceReduce, colourWord, emptyChoice, filterPresets, holdsChoices, mappingRequests, materialText,
  presetSourceLabel, presetStatusFor, samePreset, slotNumber, unconfirmedSlots,
  type Choices, type ChoiceAction, type MaterialCandidate, type MaterialInventory, type MaterialPreset, type MaterialPresetList, type MaterialSelection,
  type MaterialSlot, type PresetStatus, type ProjectMaterialsAnalysis, type SlotChoice,
} from "@/lib/projectMaterials";
import { PROVIDERS, providerArgs, useProvider, type ProviderKind } from "@/store/provider";

// UI wording that is the screen's own: states, buttons, headings. Everything that explains a
// recommendation, a mapping, a guard conflict or a change comes from the engine and is shown as sent.
export const COPY = {
  title: "Project materials",
  subtitle: "Pick the real spool and the installed Orca preset for each colour. Studio never chooses for you.",
  loading: "Reading your project and your spool list…",
  noOrca:
    "Studio could not find Snapmaker Orca's installed filament presets, so it cannot apply a preset. " +
    "Studio keeps the project's filament identity as it is.",
  providerDown:
    "Studio could not read your spool provider. You can still choose an installed Orca preset for a slot, " +
    "or keep the project's filament.",
  noProvider:
    "No spool provider is set up, so there are no spools to suggest. You can still choose an installed Orca " +
    "preset for a slot.",
  noCandidates: "No spool in your inventory matches this material.",
  closeCall: "The top choices are very close. Check which spool you actually have.",
  stale: "Saved mapping is out of date",
  selectedSpool: "Selected spool",
  notVerified: "These facts are what you selected. They are not read from the project file.",
  confirmFirst: "Confirm the highlighted preset first.",
  review: "Review before preparing",
  prepare: "Prepare with these choices",
  back: "Back to choices",
  blocked: "Prepare stopped",
} as const;

// A preset the person made is theirs to vouch for: Studio can name it, but cannot confirm Orca applies its values.
export const MANUAL_CHECK = "Manual check in Orca required";

const STATUS_STYLE: Record<PresetStatus, string> = {
  proven: "bg-ready/10 text-ready",
  needs_confirmation: "bg-repairable/15 text-repairable ring-1 ring-repairable/40",
  no_match: "bg-muted text-muted-foreground",
};

export function StatusBadge({ status, confirmedByYou = false }: { status: PresetStatus; confirmedByYou?: boolean }) {
  // "Proven" is something Studio worked out. A preset the person vouched for is not that, and is never called so.
  if (confirmedByYou) {
    return (
      <span data-status="confirmed_by_you" className="inline-flex items-center rounded-full bg-primary/15 px-2 py-px text-[11px] font-semibold text-primary">
        Confirmed by you
      </span>
    );
  }
  return (
    <span data-status={status} className={`inline-flex items-center rounded-full px-2 py-px text-[11px] font-semibold ${STATUS_STYLE[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}

function Swatch({ colour }: { colour: string | null }) {
  return <span data-testid="swatch" aria-hidden className="inline-block h-4 w-4 shrink-0 rounded-sm border border-border" style={{ backgroundColor: colour ?? "transparent" }} />;
}

// --- installed preset picker ---------------------------------------------------------------------

export function PresetPicker({ list, onPick, label }: { list: MaterialPresetList; onPick: (preset: MaterialPreset) => void; label: string }) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => filterPresets(list.presets, query), [list.presets, query]);
  // Two presets of one name from one source (two bundled files, say) differ only by position, so say which of how many.
  const twins = useMemo(() => {
    const groups = new Map<string, MaterialPreset[]>();
    for (const p of list.presets) {
      const key = `${p.base_name}\u0000${p.source ?? "system"}`;
      groups.set(key, [...(groups.get(key) ?? []), p]);
    }
    return (p: MaterialPreset): string => {
      const group = groups.get(`${p.base_name}\u0000${p.source ?? "system"}`) ?? [];
      return group.length > 1 ? ` (${group.indexOf(p) + 1} of ${group.length})` : "";
    };
  }, [list.presets]);
  return (
    <div className="space-y-1 rounded-md border border-border bg-card p-2">
      <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search installed presets"
        aria-label={`Search installed presets for ${label}`}
        className="h-8 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground" />
      <ul role="listbox" aria-label={`Installed presets for ${label}`} className="max-h-44 overflow-auto">
        {shown.length === 0 && <li className="px-2 py-1 text-xs text-muted-foreground">No installed preset matches that.</li>}
        {shown.slice(0, 100).map((p) => (
          <li key={`${p.ref ?? "system"}:${p.preset_name}`} role="option" aria-selected={false}>
            <button type="button" onClick={() => onPick(p)}
              className="flex w-full items-baseline justify-between gap-2 rounded px-2 py-1 text-left text-sm hover:bg-muted">
              <span className="truncate">
                {p.base_name}
                {/* what tells two presets of one name apart */}
                {(p.source === "user" || p.ambiguous) && <span className="text-muted-foreground"> — {presetSourceLabel(p)}{twins(p)}</span>}
              </span>
              <span className="flex shrink-0 items-center gap-1.5 text-[11px] text-muted-foreground">
                {p.status === "needs_confirmation" && <StatusBadge status="needs_confirmation" />}
                {[p.vendor, p.filament_type].filter(Boolean).join(" · ")} ·{" "}
                {p.status === "needs_confirmation" ? (p.reason ?? "compatibility not stated")
                  : p.source === "user" ? `fits ${list.nozzle} mm nozzle · ${MANUAL_CHECK}` : `fits ${list.nozzle} mm nozzle`}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// --- one candidate spool -----------------------------------------------------------------------------

function CandidateRow({ c, selected, onChoose }: { c: MaterialCandidate; selected: boolean; onChoose: () => void }) {
  const colour = colourWord(c);
  return (
    <li>
      <button type="button" aria-pressed={selected} onClick={onChoose}
        className={`w-full rounded-md border p-2 text-left text-sm ${selected ? "border-primary bg-primary/5" : "border-border hover:bg-muted/50"}`}>
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Swatch colour={c.colour} />
          {colour && <span className="font-medium">{colour}</span>}
          <span>{[c.vendor, materialText(c)].filter(Boolean).join(" ")}</span>
          <span className="text-muted-foreground">#{c.spool_id}</span>
          <span className="text-muted-foreground">{amountText(c)}</span>
          <StatusBadge status={c.mapping.status} confirmedByYou={c.mapping.status === "proven" && c.mapping.proof === "user_confirmed"} />
          {c.mapping.stale && <span className="rounded-full bg-repairable/15 px-2 py-px text-[11px] font-semibold text-repairable">{COPY.stale}</span>}
        </span>
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
          {c.reasons.map((r, i) => <li key={`${r.code}-${i}`}>{r.text}</li>)}
        </ul>
        {c.mapping.reason && c.mapping.status !== "proven" && !c.reasons.some((r) => r.text.includes(c.mapping.reason)) && (
          <span className="mt-1 block text-[11px] text-muted-foreground">{c.mapping.reason}</span>
        )}
      </button>
    </li>
  );
}

// --- one slot -----------------------------------------------------------------------------------------

export interface SlotRowProps {
  slot: MaterialSlot;
  choice: SlotChoice;
  presets: MaterialPresetList | null;
  providerLabel: string | null;
  dispatch: (a: ChoiceAction) => void;
  /** Reads the provider's whole inventory for a slot. Absent when there is no readable provider. */
  loadInventory?: (slot: number) => Promise<MaterialInventory>;
}

export function SlotRow({ slot, choice, presets, providerLabel, dispatch, loadInventory }: SlotRowProps) {
  const [picking, setPicking] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const browseToggle = useRef<HTMLButtonElement>(null);
  const wasBrowsing = useRef(false);
  // The list unmounts when it closes; focus goes back to the control that opened it.
  useEffect(() => {
    if (wasBrowsing.current && !browsing) browseToggle.current?.focus();
    wasBrowsing.current = browsing;
  }, [browsing]);
  const n = slotNumber(slot.slot);
  const sourceColour = colorName(slot.colour);
  const status = presetStatusFor(choice, slot);
  const spool = choice.spool;
  return (
    <div className="space-y-2 rounded-md border border-border p-3" data-slot={n}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <Swatch colour={slot.colour} />
        <span className="font-semibold">Slot {n}</span>
        <span>{[slot.material, slot.subtype && slot.subtype !== slot.material ? slot.subtype : null].filter(Boolean).join(" ") || "Material not stated"}</span>
        {sourceColour && <span className="text-muted-foreground">{sourceColour[0].toUpperCase() + sourceColour.slice(1)}</span>}
        {slot.required_g !== null && (
          <span className="text-muted-foreground">{slot.required_g} g needed{slot.required_source ? ` (${slot.required_source})` : ""}</span>
        )}
        {slot.settings_id && <span className="text-xs text-muted-foreground">now “{slot.settings_id}”</span>}
      </div>

      {slot.candidates.length > 0 ? (
        <div className="space-y-1">
          {slot.close_call && (
            <p className="flex items-start gap-1.5 rounded-md bg-repairable/10 p-2 text-xs text-repairable" data-testid="close-call">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />{COPY.closeCall}
            </p>
          )}
          <ul className="space-y-1" aria-label={`Spool candidates for slot ${n}`}>
            {slot.candidates.map((c) => (
              <CandidateRow key={`${c.provider}:${c.spool_id}`} c={c}
                selected={!!spool && spool.provider === c.provider && String(spool.spool_id) === String(c.spool_id)}
                onChoose={() => dispatch({ type: "chooseSpool", slot: slot.slot, spool: c })} />
            ))}
          </ul>
          {slot.candidate_count > slot.candidates.length && (
            <p className="text-[11px] text-muted-foreground">{slot.candidate_count - slot.candidates.length} more matching spool(s) not shown.</p>
          )}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground" data-testid="no-candidates">{COPY.noCandidates}</p>
      )}

      {loadInventory && (
        <div className="space-y-1">
          {!browsing && (
            <button ref={browseToggle} type="button" aria-expanded={false} className="text-xs text-primary hover:underline" onClick={() => setBrowsing(true)}>
              {INVENTORY_COPY.button}
            </button>
          )}
          {browsing && (
            <SlotInventoryPicker slot={slot.slot} load={loadInventory} onClose={() => setBrowsing(false)}
              onChoose={(c) => { setBrowsing(false); dispatch({ type: "chooseSpool", slot: slot.slot, spool: c }); }} />
          )}
        </div>
      )}

      {spool && (
        <div className="rounded-md bg-muted/40 p-2 text-xs" data-testid="selected-spool">
          <p className="font-medium">{COPY.selectedSpool}{providerLabel ? ` · from ${providerLabel} at selection time` : ""}</p>
          <p className="text-muted-foreground">
            {[spool.vendor, materialText(spool)].filter(Boolean).join(" ")} · #{spool.spool_id}
            {colourWord(spool) ? ` · ${colourWord(spool)}` : ""} — {COPY.notVerified}
          </p>
          <button type="button" className="mt-1 text-primary hover:underline" onClick={() => dispatch({ type: "clearSpool", slot: slot.slot })}>
            Clear spool
          </button>
        </div>
      )}

      {/* The Orca preset */}
      <div className="space-y-1 rounded-md border border-dashed border-border p-2" data-testid="preset-area">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-medium">Orca preset</span>
          {choice.keepOwn ? <span className="text-muted-foreground">Keep project&apos;s filament</span>
            : choice.preset ? <span>{choice.preset.name}{choice.preset.source === "user" && <span className="text-muted-foreground"> — User preset</span>}</span>
            : <span className="text-muted-foreground">Not chosen yet</span>}
          {status && !choice.keepOwn && (choice.preset || spool) && (
            <StatusBadge status={status}
              confirmedByYou={!!choice.preset?.confirmed && (!!choice.preset?.needsSayso || choice.preset?.source === "user")} />
          )}
          {choice.preset?.source === "user" && !choice.keepOwn && <span className="text-[11px] font-semibold text-repairable" data-testid="manual-check">{MANUAL_CHECK}</span>}
          {spool && choice.preset && !choice.keepOwn && (
            <span className="text-[11px] text-muted-foreground" data-testid="match-source">
              {samePreset(choice.preset, spool.mapping)
                ? (MATCH_SOURCE_LABEL[spool.mapping.match_source] ?? spool.mapping.match_source)
                : MATCH_SOURCE_LABEL.manual}
            </span>
          )}
        </div>

        {choice.keepOwn && <p className="text-xs text-muted-foreground" data-testid="keep-own-notice">{KEEP_OWN_NOTICE}</p>}

        {/* A spool decides the colour. Without an Orca preset it does not change the filament preset, and the person is told so. */}
        {spool && !choice.preset && !choice.keepOwn && (
          <p className="flex items-start gap-1.5 text-xs text-repairable" data-testid="spool-without-preset">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{slot.settings_id ? SPOOL_WITHOUT_PRESET : SPOOL_WITHOUT_PRESET_NONE_EXISTING}{!spool.colour ? " This spool has no colour recorded, so nothing about this slot will change." : ""}</span>
          </p>
        )}

        {choice.preset && !choice.preset.confirmed && !choice.keepOwn && (
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-xs text-muted-foreground">{choice.preset.note ?? spool?.mapping.reason}</p>
            <Button size="sm" onClick={() => dispatch({ type: "confirmPreset", slot: slot.slot })}>
              <Check className="h-3.5 w-3.5" /> {choice.preset.needsSayso ? "Confirm this is a U1 preset" : "Confirm this preset"}
            </Button>
          </div>
        )}

        {!choice.preset && !choice.keepOwn && slot.suggestion && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={slot.suggestion.status} />
            <span>Suggested: {slot.suggestion.base_name}</span>
            <span className="text-muted-foreground">{slot.suggestion.reason}</span>
            <Button size="sm" variant="secondary" onClick={() => dispatch({ type: "pickPreset", slot: slot.slot, name: slot.suggestion!.base_name })}>
              Use this preset
            </Button>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 text-xs">
          {presets && presets.available && (
            <button type="button" className="text-primary hover:underline" onClick={() => setPicking((v) => !v)}>
              {choice.preset ? "Choose a different installed preset" : "Choose an installed preset"}
            </button>
          )}
          {!choice.keepOwn && (
            <button type="button" className="text-primary hover:underline" onClick={() => { setPicking(false); dispatch({ type: "keepOwn", slot: slot.slot }); }}>
              Keep project&apos;s filament
            </button>
          )}
          {(choice.preset || choice.keepOwn) && (
            <button type="button" className="text-muted-foreground hover:underline" onClick={() => dispatch({ type: "clearPreset", slot: slot.slot })}>
              Clear preset choice
            </button>
          )}
        </div>
        {picking && presets && presets.available && (
          <PresetPicker list={presets} label={`slot ${n}`} onPick={(row) => {
            setPicking(false);
            dispatch({ type: "pickPreset", slot: slot.slot, name: row.base_name,
              source: row.source === "user" || row.ambiguous ? row.source : undefined, ref: row.ref ?? undefined,
              unproven: row.status === "needs_confirmation", note: row.reason, fingerprint: row.fingerprint });
          }} />
        )}

        {canRemember(choice) && (
          <fieldset className="mt-1 space-y-1 text-xs" data-testid="remember">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={choice.remember !== "off"}
                onChange={(e) => dispatch({ type: "remember", slot: slot.slot, mode: e.target.checked ? "spool" : "off" })} />
              Remember this mapping
            </label>
            {choice.remember !== "off" && (
              <div className="ml-5 space-y-0.5">
                <label className="flex items-center gap-1.5">
                  <input type="radio" name={`remember-${slot.slot}`} checked={choice.remember === "spool"}
                    onChange={() => dispatch({ type: "remember", slot: slot.slot, mode: "spool" })} /> For this spool only
                </label>
                <label className="flex items-center gap-1.5">
                  <input type="radio" name={`remember-${slot.slot}`} checked={choice.remember === "signature"}
                    onChange={() => dispatch({ type: "remember", slot: slot.slot, mode: "signature" })} /> For similar spools
                </label>
                <p className="text-[11px] text-muted-foreground">Saved on this computer only when you prepare.</p>
              </div>
            )}
          </fieldset>
        )}
      </div>
    </div>
  );
}

// --- review and blocked --------------------------------------------------------------------------------

export type ReviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "done"; result: ConversionResult };

export function BlockedPanel({ result, onBack }: { result: ConversionResult; onBack: () => void }) {
  const facts = blockedFacts(result);
  if (!facts) return null;
  return (
    <div className="space-y-2 rounded-md border border-risk/50 bg-risk/5 p-3" role="alert" data-testid="blocked">
      <p className="flex items-center gap-1.5 text-sm font-semibold text-risk"><AlertTriangle className="h-4 w-4" />{COPY.blocked}</p>
      {facts.message && <p className="text-sm">{facts.message}</p>}
      <ul className="space-y-1 text-xs">
        {facts.conflicts.map((c, i) => (
          <li key={i} data-testid="blocked-conflict">
            Slots {c.slots.map(slotNumber).join(", ")} share “{c.preset}” · conflicting: <span className="font-mono">{c.key}</span>
          </li>
        ))}
      </ul>
      {/* The engine's message often already carries its resolution; say it once. */}
      {facts.resolution && !(facts.message ?? "").includes(facts.resolution) && (
        <p className="text-xs text-muted-foreground" data-testid="blocked-resolution">{facts.resolution}</p>
      )}
      <Button size="sm" variant="secondary" onClick={onBack}>{COPY.back}</Button>
    </div>
  );
}

export function ProjectMaterialsFidelity({ summary }: { summary: ProjectMaterialsSummary | undefined }) {
  const lines = summary?.fidelity?.lines ?? [];
  const notes = (summary?.fidelity?.slots ?? []).flatMap((s) => s.discrepancies.map((d) => ({ slot: s.slot, text: d.text, code: d.code })));
  if (!lines.length && !notes.length) return null;
  return (
    <div className="space-y-1 text-xs" data-testid="materials-fidelity">
      <ul className="list-disc space-y-1 pl-5">{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
      {notes.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
          {notes.map((d, i) => <li key={i}>Slot {slotNumber(d.slot)}: {d.text}</li>)}
        </ul>
      )}
    </div>
  );
}

export function ReviewPanel({ review, providerLabel, onPrepare, onBack, busy }: {
  review: ReviewState; providerLabel: string | null; onPrepare: () => void; onBack: () => void; busy?: boolean;
}) {
  if (review.status === "idle") return null;
  if (review.status === "loading") {
    return <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Checking your choices…</p>;
  }
  if (review.status === "error") {
    return (
      <div className="space-y-2 text-sm" role="alert">
        <p className="text-risk">Couldn&apos;t check these choices: {review.error}</p>
        <Button size="sm" variant="secondary" onClick={onBack}>{COPY.back}</Button>
      </div>
    );
  }
  if (review.result.blocked) return <BlockedPanel result={review.result} onBack={onBack} />;
  const summary = review.result.settings_summary?.project_materials;
  return (
    <div className="space-y-2 rounded-md border border-primary/40 bg-primary/5 p-3" data-testid="review">
      <p className="text-sm font-semibold">{COPY.review}</p>
      <ProjectMaterialsFidelity summary={summary} />
      <p className="text-[11px] text-muted-foreground">
        Spool details{providerLabel ? ` are from ${providerLabel} at selection time` : " are what you selected"}; they are not read from the file. Studio never writes them into the project.
      </p>
      <div className="flex gap-2">
        <Button size="sm" onClick={onPrepare} disabled={busy}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{COPY.prepare}</Button>
        <Button size="sm" variant="secondary" onClick={onBack}>{COPY.back}</Button>
      </div>
    </div>
  );
}

// --- the card (pure view) ---------------------------------------------------------------------------------

export interface ViewProps {
  load: { status: "loading" } | { status: "error"; error: string } | { status: "ready" };
  analysis: ProjectMaterialsAnalysis | null;
  presets: MaterialPresetList | null;
  providerLabel: string | null;
  choices: Choices;
  dispatch: (a: ChoiceAction) => void;
  review: ReviewState;
  onReview: () => void;
  onBack: () => void;
  onPrepare: () => void;
  busy?: boolean;
  warning?: string | null;
  loadInventory?: (slot: number) => Promise<MaterialInventory>;
}

export function ProjectMaterialsView(p: ViewProps) {
  const { analysis, choices } = p;
  // A project with no usable filament slots (an STL, a file without project settings, or no slots) gets no
  // picker at all: an empty card would only suggest something is missing.
  if (p.load.status === "ready" && (!analysis || !analysis.supported || (analysis.slots ?? []).length === 0)) return null;
  const selections = buildSelections(choices);
  const pending = unconfirmedSlots(choices);
  const body = (() => {
    if (p.load.status === "loading") {
      return <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> {COPY.loading}</p>;
    }
    if (p.load.status === "error") return <p className="text-sm text-risk" role="alert">Couldn&apos;t read this project&apos;s materials: {p.load.error}</p>;
    if (!analysis) return null;
    return (
      <div className="space-y-3">
        {analysis.catalog && !analysis.catalog.available && (
          <p className="flex items-start gap-1.5 rounded-md bg-risk/10 p-2 text-xs text-risk" data-testid="no-orca">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{COPY.noOrca}
          </p>
        )}
        {analysis.provider && !analysis.provider.available && (
          <p className="flex items-start gap-1.5 rounded-md bg-repairable/10 p-2 text-xs text-repairable" data-testid="provider-down">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{COPY.providerDown}
          </p>
        )}
        {!analysis.provider && <p className="text-xs text-muted-foreground" data-testid="no-provider">{COPY.noProvider}</p>}
        {(analysis.slots ?? []).map((slot) => (
          <SlotRow key={slot.slot} slot={slot} choice={choices[slot.slot] ?? emptyChoice} presets={p.presets}
            providerLabel={p.providerLabel} dispatch={p.dispatch}
            loadInventory={analysis.provider?.available ? p.loadInventory : undefined} />
        ))}
        {p.review.status === "idle" ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={p.onReview} disabled={selections.length === 0 || pending.length > 0}>Review &amp; prepare</Button>
            {selections.length > 0 && <button type="button" className="text-xs text-muted-foreground hover:underline" onClick={() => p.dispatch({ type: "reset" })}>Clear all choices</button>}
            {pending.length > 0 && <span className="text-xs text-repairable" data-testid="confirm-first">{COPY.confirmFirst}</span>}
            {selections.length === 0 && pending.length === 0 && <span className="text-xs text-muted-foreground">Nothing chosen. Prepare works as usual without this.</span>}
          </div>
        ) : (
          <ReviewPanel review={p.review} providerLabel={p.providerLabel} onPrepare={p.onPrepare} onBack={p.onBack} busy={p.busy} />
        )}
        {p.warning && <p className="text-xs text-repairable" role="status">{p.warning}</p>}
      </div>
    );
  })();
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-semibold"><Layers className="h-4 w-4 text-primary" />{COPY.title}</h3>
          <p className="mt-1 text-xs text-muted-foreground">{COPY.subtitle}</p>
        </div>
        {body}
      </CardContent>
    </Card>
  );
}

// --- the card (loads, holds the choices, hands them to Prepare) ----------------------------------------------

interface CardProps {
  path: string;
  mode: PrepareMode;
  /** Called with the confirmed selections once the person has reviewed them and chosen to prepare. Returns the
   *  Prepare result so a remembered mapping is saved only after a copy was really made. */
  onPrepare: (selections: MaterialSelection[]) => void | Promise<ConversionResult | void>;
  /** Lets the parent know whether Project Materials holds choices, so a plain Prepare is not offered beside them. */
  onActiveChange?: (active: boolean) => void;
  busy?: boolean;
}

export function ProjectMaterialsCard({ path, mode, onPrepare, onActiveChange, busy }: CardProps) {
  const provider = useProvider();
  const args = providerArgs(provider);
  const argsKey = JSON.stringify([args.provider, args.provider_url, args.slot_map, args.slot_base, args.provider_key]);
  const [load, setLoad] = useState<ViewProps["load"]>({ status: "loading" });
  const [analysis, setAnalysis] = useState<ProjectMaterialsAnalysis | null>(null);
  const [presets, setPresets] = useState<MaterialPresetList | null>(null);
  const [choices, dispatch] = useReducer(choiceReduce, {} as Choices);
  const [review, setReview] = useState<ReviewState>({ status: "idle" });
  const [warning, setWarning] = useState<string | null>(null);
  const generation = useRef(0);
  const providerLabel = provider.kind !== "none" ? PROVIDERS[provider.kind as Exclude<ProviderKind, "none">]?.label ?? null : null;

  useEffect(() => {
    const gen = ++generation.current;
    setLoad({ status: "loading" });
    setAnalysis(null);
    setPresets(null);
    setReview({ status: "idle" });
    dispatch({ type: "reset" });
    (async () => {
      try {
        const a = await projectMaterials(path, args, 3);
        if (gen !== generation.current) return;
        setAnalysis(a);
        setLoad({ status: "ready" });
        if (a.supported && a.catalog?.available && a.nozzle) {
          try {
            const list = await materialPresets(a.nozzle);
            if (gen === generation.current) setPresets(list);
          } catch { /* the picker simply does not appear; spool suggestions still work */ }
        }
      } catch (e: any) {
        if (gen === generation.current) setLoad({ status: "error", error: String(e?.message ?? e) });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, argsKey]);

  const loadInventory = useCallback((slot: number) => projectMaterialsInventory(path, slot, args),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [path, argsKey]);

  const selections = useMemo(() => buildSelections(choices), [choices]);
  const holding = holdsChoices(choices);
  useEffect(() => { onActiveChange?.(holding); }, [holding, onActiveChange]);
  // Any change to the choices, the preparation mode, the project or the provider invalidates a review: it was
  // computed for exactly those. A review still in flight is discarded too (see the generation check below).
  const reviewGen = useRef(0);
  useEffect(() => {
    reviewGen.current += 1;
    setReview((r) => (r.status === "idle" ? r : { status: "idle" }));
  }, [choices, mode, path, argsKey]);

  async function onReview() {
    const gen = reviewGen.current;
    setReview({ status: "loading" });
    setWarning(null);
    try {
      const result = await convert(path, undefined, mode, true, selections);
      if (gen === reviewGen.current) setReview({ status: "done", result });
    } catch (e: any) {
      if (gen === reviewGen.current) setReview({ status: "error", error: String(e?.message ?? e) });
    }
  }

  const submitting = useRef(false);
  const [preparing, setPreparing] = useState(false);

  async function doPrepare() {
    // One Prepare per click: a second click while one is running, or on a review that has already been used, does nothing.
    if (submitting.current) return;
    submitting.current = true;
    setPreparing(true);
    setWarning(null);
    try {
      let result: ConversionResult | void;
      // The route that owns Prepare shows why it failed (Compatibility renders it whether or not the settings check
      // answered), so a failure is not repeated here and nothing is saved.
      try { result = await onPrepare(selections); }
      catch { return; }
      // A mapping is remembered only once a copy was actually made with it: not when Prepare was blocked or failed.
      if (!result || result.blocked || !result.output_path) return;
      // The review described the copy that now exists. Close it at once, so "Prepare with these choices" cannot be pressed
      // again against it; making another copy takes a fresh review.
      reviewGen.current += 1;
      setReview({ status: "idle" });
      for (const request of mappingRequests(choices, analysis?.nozzle ?? "0.4")) {
        try { await confirmMaterialMapping(request); }
        catch (e: any) { setWarning(`Your copy was made, but a mapping could not be saved (${String(e?.message ?? e)}).`); }
      }
    } finally {
      submitting.current = false;
      setPreparing(false);
    }
  }

  return (
    <ProjectMaterialsView load={load} analysis={analysis} presets={presets} providerLabel={providerLabel} choices={choices}
      dispatch={dispatch} review={review} onReview={onReview} onBack={() => setReview({ status: "idle" })}
      onPrepare={doPrepare} busy={busy || preparing} warning={warning} loadInventory={loadInventory} />
  );
}

export default ProjectMaterialsCard;
