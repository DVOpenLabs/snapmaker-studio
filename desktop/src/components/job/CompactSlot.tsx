import { useEffect, useId, useRef, useState } from "react";
import { AlertTriangle, Check, Info } from "lucide-react";
import SlotInventoryPicker, { INVENTORY_COPY } from "@/components/SlotInventoryPicker";
import { COPY, MANUAL_CHECK, PresetPicker, StatusBadge, Swatch, candidateKey, type SlotRowProps } from "@/components/ProjectMaterialsCard";
import { Button } from "@/components/ui/button";
import { colorName } from "@/lib/plateRemapWizard";
import {
  KEEP_OWN_NOTICE, KEEP_OWN_NOTICE_NONE_EXISTING, SPOOL_FOREIGN_PRESET_HINT, SPOOL_PRESET_CAVEAT, SPOOL_WITHOUT_PRESET,
  SPOOL_WITHOUT_PRESET_NONE_EXISTING, USAGE_COPY, amountText, canRemember, colourWord, isForeignPreset, materialText,
  presetStatusFor, samePreset, savedScope, slotNumber, splitReasons, MATCH_SOURCE_LABEL, type MaterialCandidate, type MaterialReason,
} from "@/lib/projectMaterials";

/**
 * One slot of the job screen's Materials tab, in a line: what the project wants, what is chosen, and one control to
 * choose. The candidates, the installed-preset list, the full inventory and the technical reasons open on request.
 * Everything that is a decision stays on the line itself: a spool that does not match, an unknown amount, a preset that
 * needs the person's say-so, a stale saved mapping. Choices go through the same reducer as the detailed row; nothing
 * is chosen for the person, and opening or closing the panel never changes a choice.
 */
export function CompactSlotRow({ slot, choice, presets, providerLabel, dispatch, loadInventory, onForget, forgetDisabled }: SlotRowProps) {
  const [open, setOpen] = useState(false);
  const [picking, setPicking] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const panel = useId();
  const browseToggle = useRef<HTMLButtonElement>(null);
  const wasBrowsing = useRef(false);
  // The list unmounts when it closes; focus goes back to the control that opened it.
  useEffect(() => {
    if (wasBrowsing.current && !browsing) browseToggle.current?.focus();
    wasBrowsing.current = browsing;
  }, [browsing]);

  const n = slotNumber(slot.slot);
  const spool = choice.spool;
  const status = presetStatusFor(choice, slot);
  const sourceColour = colorName(slot.colour);
  const material = [slot.material, slot.subtype && slot.subtype !== slot.material ? slot.subtype : null].filter(Boolean).join(" ") || "Material not stated";
  const chosen = !!spool || !!choice.preset || choice.keepOwn;
  const spoolName = spool
    ? [colourWord(spool), [spool.vendor, materialText(spool)].filter(Boolean).join(" "), `#${spool.spool_id}`].filter(Boolean).join(" · ")
    : null;
  const presetName = choice.keepOwn ? "Keeps the project's filament" : choice.preset ? choice.preset.name : null;
  // The preset-confirmation reason is the engine's state at selection time; the confirmation block below follows the person's own choice.
  const spoolFlags = spool ? splitReasons(spool).decision.filter((r) => r.code !== "preset_needs_confirmation") : [];

  return (
    <div className="space-y-1.5 rounded-md border border-border p-2.5" data-slot={n} data-compact>
      <div className="flex items-start gap-2">
        <span className="mt-0.5"><Swatch colour={slot.colour} /></span>
        <div className="min-w-0 flex-1 text-sm">
          <p className="font-medium">
            Slot {n}{" "}
            <span className="font-normal text-muted-foreground">
              · {material}{sourceColour ? ` · ${sourceColour[0].toUpperCase() + sourceColour.slice(1)}` : ""}
              {slot.required_g !== null ? ` · ${slot.required_g} g needed${slot.required_source ? ` (${slot.required_source})` : ""}` : ""}
            </span>
          </p>
          <p className="text-xs text-muted-foreground" data-testid="slot-choice">
            {spoolName ? <span className="text-foreground">{spoolName}</span> : "No spool chosen"}
            {" · "}
            {presetName ? <span className="text-foreground">{presetName}</span> : "No Orca preset yet"}
            {status && !choice.keepOwn && (choice.preset || spool) && (
              <>{" "}<StatusBadge status={status}
                confirmedByYou={!!choice.preset?.confirmed && (!!choice.preset?.needsSayso || choice.preset?.source === "user")} /></>
            )}
            {slot.close_call && (
              <> <span className="rounded-full bg-repairable/15 px-2 py-px text-[11px] font-semibold text-repairable-text" data-testid="close-call">Close call</span></>
            )}
          </p>
        </div>
        <button type="button" aria-expanded={open} aria-controls={open ? panel : undefined} data-testid="slot-toggle"
          aria-label={`${chosen ? "Change" : "Choose"} materials for slot ${n}`}
          onClick={() => { if (open) { setBrowsing(false); setPicking(false); } setOpen((v) => !v); }}
          className="shrink-0 rounded-md border border-border px-2.5 py-1 text-xs font-medium hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
          {open ? "Done" : chosen ? "Change" : "Choose"}
        </button>
      </div>

      {/* What needs a decision stays on the line, open or closed. */}
      {slot.usage && slot.usage.verdict !== "referenced" && (
        <p className="text-[11px] text-muted-foreground" data-testid="slot-usage" data-verdict={slot.usage.verdict}>{USAGE_COPY[slot.usage.verdict]}</p>
      )}
      {spoolFlags.length > 0 && <Flags reasons={spoolFlags} testId="spool-flags" />}
      {spool?.mapping.stale && <p className="text-xs font-medium text-repairable" data-testid="stale-mapping">{COPY.stale}</p>}
      {choice.preset?.source === "user" && !choice.keepOwn && (
        <p className="text-xs font-medium text-repairable" data-testid="manual-check">{MANUAL_CHECK}</p>
      )}
      {choice.preset && !choice.preset.confirmed && !choice.keepOwn && (
        <div data-testid="needs-confirmation">
          <div className="flex items-center gap-2">
            <p className="min-w-0 flex-1 text-xs text-repairable-text">This preset needs your confirmation.</p>
            <Button size="sm" onClick={() => dispatch({ type: "confirmPreset", slot: slot.slot })}>
              <Check className="h-3.5 w-3.5" aria-hidden="true" /> {choice.preset.needsSayso ? "Confirm this is a U1 preset" : "Confirm this preset"}
            </Button>
          </div>
          {choice.preset.needsSayso && (choice.preset.note ?? spool?.mapping.reason) && (
            <p className="text-[11px] text-muted-foreground" data-testid="sayso-note">{choice.preset.note ?? spool?.mapping.reason}</p>
          )}
          {!choice.preset.needsSayso && (choice.preset.note ?? spool?.mapping.reason) && (
            <details className="text-[11px] text-muted-foreground"><summary className="cursor-pointer select-none">Why</summary>
              <p className="mt-1">{choice.preset.note ?? spool?.mapping.reason}</p></details>
          )}
        </div>
      )}
      {!choice.preset && !choice.keepOwn && slot.suggestion && (
        <div data-testid="suggestion">
          <div className="flex items-center gap-2 text-xs">
            <span className="min-w-0 flex-1">Suggested preset: <span className="font-medium">{slot.suggestion.base_name}</span> <StatusBadge status={slot.suggestion.status} /></span>
            <Button size="sm" variant="secondary" onClick={() => dispatch({ type: "pickPreset", slot: slot.slot, name: slot.suggestion!.base_name })}>
              Use this preset
            </Button>
          </div>
          {slot.suggestion.reason && (
            <details className="text-[11px] text-muted-foreground"><summary className="cursor-pointer select-none">Why this suggestion</summary>
              <p className="mt-1">{slot.suggestion.reason}</p></details>
          )}
        </div>
      )}
      {spool && !choice.preset && !choice.keepOwn && (
        <div className="flex items-start gap-1.5 text-xs text-repairable" data-testid="spool-without-preset">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <div>
            {slot.settings_id ? SPOOL_WITHOUT_PRESET : SPOOL_WITHOUT_PRESET_NONE_EXISTING}
            {!spool.colour ? " This spool has no colour recorded, so nothing about this slot will change." : ""}
            {slot.settings_id && isForeignPreset(slot.settings_id) && (
              <span className="mt-0.5 block font-medium" data-testid="foreign-preset">
                The project&apos;s preset, &ldquo;{slot.settings_id}&rdquo;, looks like another printer&apos;s. Choosing a spool does not choose a preset: open Change to pick an installed one.
              </span>
            )}
            {slot.settings_id && (
              <details className="mt-0.5 text-[11px] text-muted-foreground"><summary className="cursor-pointer select-none">More</summary>
                <span className="mt-1 block">{SPOOL_PRESET_CAVEAT}{isForeignPreset(slot.settings_id) ? ` ${SPOOL_FOREIGN_PRESET_HINT}` : ""}</span></details>
            )}
          </div>
        </div>
      )}
      {choice.keepOwn && (
        <p className="text-xs text-muted-foreground" data-testid="keep-own-notice">{slot.settings_id ? KEEP_OWN_NOTICE : KEEP_OWN_NOTICE_NONE_EXISTING}</p>
      )}

      {open && (
        <div id={panel} className="space-y-2 border-t border-border pt-2" data-testid="slot-panel">
          {slot.close_call && (
            <p className="flex items-start gap-1.5 text-xs text-repairable-text" data-testid="close-call-note">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{COPY.closeCall}
            </p>
          )}
          {slot.settings_id && <p className="text-[11px] text-muted-foreground" data-testid="project-preset">The project now names &ldquo;{slot.settings_id}&rdquo; for this slot.</p>}
          {slot.candidates.length > 0 ? (
            <ul className="m-0 list-none space-y-1.5 p-0" aria-label={`Spool candidates for slot ${n}`}>
              {slot.candidates.map((c) => (
                <CompactCandidate key={candidateKey(c)} c={c}
                  selected={!!spool && spool.provider === c.provider && String(spool.spool_id) === String(c.spool_id)}
                  onChoose={() => dispatch({ type: "chooseSpool", slot: slot.slot, spool: c })}
                  onForget={onForget ? (opener) => onForget(c, opener) : undefined} forgetDisabled={forgetDisabled} />
              ))}
            </ul>
          ) : <p className="text-xs text-muted-foreground" data-testid="no-candidates">{COPY.noCandidates}</p>}
          {slot.candidate_count > slot.candidates.length && (
            <p className="text-[11px] text-muted-foreground">{slot.candidate_count - slot.candidates.length} more matching spool(s) not shown.</p>
          )}

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {loadInventory && !browsing && (
              <button ref={browseToggle} type="button" className="text-primary hover:underline" onClick={() => setBrowsing(true)}>{INVENTORY_COPY.button}</button>
            )}
            {presets && presets.available && (
              <button type="button" className="text-primary hover:underline" aria-expanded={picking} onClick={() => setPicking((v) => !v)}>
                {choice.preset ? "Choose a different installed preset" : "Choose an installed preset"}
              </button>
            )}
            {!choice.keepOwn && (
              <button type="button" className="text-primary hover:underline" onClick={() => { setPicking(false); dispatch({ type: "keepOwn", slot: slot.slot }); }}>
                Keep project&apos;s filament
              </button>
            )}
            {spool && <button type="button" className="text-muted-foreground hover:underline" onClick={() => dispatch({ type: "clearSpool", slot: slot.slot })}>Clear spool</button>}
            {(choice.preset || choice.keepOwn) && (
              <button type="button" className="text-muted-foreground hover:underline" onClick={() => dispatch({ type: "clearPreset", slot: slot.slot })}>Clear preset choice</button>
            )}
          </div>
          {browsing && loadInventory && (
            <SlotInventoryPicker slot={slot.slot} load={loadInventory} onClose={() => setBrowsing(false)}
              onChoose={(c) => { setBrowsing(false); dispatch({ type: "chooseSpool", slot: slot.slot, spool: c }); }} />
          )}
          {picking && presets && presets.available && (
            <PresetPicker list={presets} label={`slot ${n}`} onPick={(row) => {
              setPicking(false);
              dispatch({ type: "pickPreset", slot: slot.slot, name: row.base_name,
                source: row.source === "user" || row.ambiguous ? row.source : undefined, ref: row.ref ?? undefined,
                unproven: row.status === "needs_confirmation", note: row.reason, fingerprint: row.fingerprint });
            }} />
          )}
          {canRemember(choice) && (
            <fieldset className="space-y-1 text-xs" data-testid="remember">
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
          {spool && (
            <details className="text-[11px] text-muted-foreground" data-testid="selected-spool">
              <summary className="cursor-pointer select-none">About the chosen spool</summary>
              <p className="mt-1">
                {COPY.selectedSpool}{providerLabel ? ` · from ${providerLabel} at selection time` : ""}. {COPY.notVerified}
                {choice.preset && !choice.keepOwn && (
                  <> Preset source: {samePreset(choice.preset, spool.mapping)
                    ? (MATCH_SOURCE_LABEL[spool.mapping.match_source] ?? spool.mapping.match_source)
                    : MATCH_SOURCE_LABEL.manual}.</>
                )}
              </p>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function Flags({ reasons, testId }: { reasons: MaterialReason[]; testId?: string }) {
  return (
    <ul className="m-0 list-none space-y-0.5 p-0 text-xs text-repairable" data-testid={testId}>
      {reasons.map((r, i) => (
        <li key={`${r.code}-${i}`} className="flex items-start gap-1.5">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />{r.text}
        </li>
      ))}
    </ul>
  );
}

function CompactCandidate({ c, selected, onChoose, onForget, forgetDisabled }: {
  c: MaterialCandidate; selected: boolean; onChoose: () => void;
  onForget?: (opener: HTMLButtonElement) => void; forgetDisabled?: boolean;
}) {
  const { decision, detail } = splitReasons(c);
  const saved = savedScope(c);
  const colour = colourWord(c);
  const name = [c.vendor, materialText(c)].filter(Boolean).join(" ");
  const needsSayso = (c.warnings ?? []).filter((w) => w.requires_confirmation);
  return (
    <li className="space-y-0.5">
      <button type="button" aria-pressed={selected} onClick={onChoose} data-candidate-key={candidateKey(c)}
        className={`flex w-full flex-wrap items-center gap-x-2 gap-y-0.5 rounded-md border p-2 text-left text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring ${selected ? "border-primary bg-primary/5" : "border-border hover:bg-muted/50"}`}>
        <Swatch colour={c.colour} />
        {colour && <span className="font-medium">{colour}</span>}
        <span>{name}</span>
        <span className="text-muted-foreground">#{c.spool_id}</span>
        <span className="text-muted-foreground">{amountText(c)}</span>
        <StatusBadge status={c.mapping.status} confirmedByYou={c.mapping.status === "proven" && c.mapping.proof === "user_confirmed"} />
        {c.mapping.stale && <span className="rounded-full bg-repairable/15 px-2 py-px text-[11px] font-semibold text-repairable">{COPY.stale}</span>}
      </button>
      {(decision.length > 0 || needsSayso.length > 0) && (
        <div className="pl-2">
          <Flags reasons={[...decision, ...needsSayso.map((w): MaterialReason => ({ code: w.code, text: w.text }))]} />
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 pl-2">
        <details className="text-[11px] text-muted-foreground">
          <summary className="cursor-pointer select-none">Why this match</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {detail.map((r, i) => <li key={`${r.code}-${i}`}>{r.text}</li>)}
            {c.mapping.reason && c.mapping.status !== "proven" && !c.reasons.some((r) => r.text.includes(c.mapping.reason)) && <li>{c.mapping.reason}</li>}
          </ul>
        </details>
        {saved && onForget && (
          <button type="button" disabled={forgetDisabled} data-testid="forget-mapping"
            aria-label={`Forget saved mapping${saved === "signature" ? " (similar spools)" : ""} for ${name} #${c.spool_id}`}
            className="text-[11px] text-primary hover:underline disabled:opacity-50" onClick={(e) => onForget(e.currentTarget)}>
            {saved === "signature" ? "Forget saved mapping (similar spools)" : "Forget saved mapping"}
          </button>
        )}
      </div>
    </li>
  );
}
