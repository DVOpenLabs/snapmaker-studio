import { describe, expect, it } from "vitest";
import {
  KEEP_OWN_NOTICE, amountText, blockedFacts, buildSelections, canRemember, choiceReduce, emptyChoice, filterPresets,
  mappingRequests, presetStatusFor, unconfirmedSlots,
  type Choices, type MaterialCandidate,
} from "./projectMaterials";
import { candidate, mapping, slot } from "./projectMaterials.fixtures";

const PROVEN = mapping({ status: "proven", match_source: "saved_spool", preset_name: "Snapmaker PLA Matte @U1", base_name: "Snapmaker PLA Matte @U1", reason: "" });
const NAMED = mapping({ status: "needs_confirmation", match_source: "exact_name", preset_name: "Snapmaker PLA Matte @U1", base_name: "Snapmaker PLA Matte @U1",
  reason: "The provider names this installed preset. Confirm it to use it and to remember it." });

describe("choices", () => {
  it("starts with nothing chosen and builds no request", () => {
    expect(buildSelections({})).toEqual([]);
    expect(unconfirmedSlots({})).toEqual([]);
  });

  it("choosing a spool with a remembered, proven mapping offers its preset as already confirmed", () => {
    const s = choiceReduce({}, { type: "chooseSpool", slot: 0, spool: candidate({ mapping: PROVEN }) });
    expect(s[0].preset).toEqual({ name: "Snapmaker PLA Matte @U1", confirmed: true });
    expect(presetStatusFor(s[0], slot())).toBe("proven");
  });

  it("a preset the provider merely names waits for the person; a spool with no match gets none", () => {
    const named = choiceReduce({}, { type: "chooseSpool", slot: 0, spool: candidate({ mapping: NAMED }) });
    expect(named[0].preset).toEqual({ name: "Snapmaker PLA Matte @U1", confirmed: false });
    expect(unconfirmedSlots(named)).toEqual([0]);
    expect(buildSelections(named)[0].preset).toBeNull();            // not sent until confirmed
    const none = choiceReduce({}, { type: "chooseSpool", slot: 0, spool: candidate() });
    expect(none[0].preset).toBeNull();
    // an ambiguous match has no preset name at all and is never picked for the person
    const ambiguous = choiceReduce({}, { type: "chooseSpool", slot: 0, spool: candidate({
      mapping: mapping({ status: "needs_confirmation", match_source: "exact_name", candidates: ["A @U1", "a @U1"] }) }) });
    expect(ambiguous[0].preset).toBeNull();
  });

  it("confirming, picking from the installed list, and clearing", () => {
    let s: Choices = choiceReduce({}, { type: "chooseSpool", slot: 0, spool: candidate({ mapping: NAMED }) });
    s = choiceReduce(s, { type: "confirmPreset", slot: 0 });
    expect(unconfirmedSlots(s)).toEqual([]);
    expect(buildSelections(s)[0].preset).toBe("Snapmaker PLA Matte @U1");
    s = choiceReduce(s, { type: "pickPreset", slot: 0, name: "Snapmaker PLA SnapSpeed @U1" });
    expect(s[0].preset).toEqual({ name: "Snapmaker PLA SnapSpeed @U1", confirmed: true });
    s = choiceReduce(s, { type: "clearPreset", slot: 0 });
    expect(s[0].preset).toBeNull();
    expect(choiceReduce({}, { type: "confirmPreset", slot: 3 })).toEqual({});     // nothing to confirm
  });

  it("the request carries the preset, the spool colour and the spool's identity fields", () => {
    let s: Choices = choiceReduce({}, { type: "chooseSpool", slot: 1, spool: candidate({ mapping: PROVEN, slicer_filament: "Generic PLA" }) });
    expect(buildSelections(s)).toEqual([{
      slot: 1, preset: "Snapmaker PLA Matte @U1", colour: "#FF0000",
      spool: { provider: "spoolease", id: "124", vendor: "Yoopai", material: "PLA", subtype: "Matte", colour: "#FF0000",
               color_name: "red", slicer_filament: "Generic PLA" },
    }]);
    // nothing about remaining weight or the provider's address is in the request
    const text = JSON.stringify(buildSelections(s));
    expect(text).not.toMatch(/remaining|412|url|key|token/i);
  });

  it("Keep project's filament sends no preset; a chosen spool still brings its colour", () => {
    let s: Choices = choiceReduce({}, { type: "keepOwn", slot: 0 });
    expect(buildSelections(s)).toEqual([]);
    s = choiceReduce(s, { type: "chooseSpool", slot: 0, spool: candidate({ mapping: PROVEN }) });
    s = choiceReduce(s, { type: "keepOwn", slot: 0 });
    expect(s[0].keepOwn).toBe(true);
    expect(buildSelections(s)).toEqual([expect.objectContaining({ slot: 0, preset: null, colour: "#FF0000" })]);
    expect(unconfirmedSlots(s)).toEqual([]);
    expect(KEEP_OWN_NOTICE).toBe(
      "Studio keeps the project's existing filament identity. If Snapmaker Orca does not recognize that preset, Orca may treat it as a Customized Preset and rename it.");
  });

  it("clearing the spool keeps only a preset the person already confirmed", () => {
    let s: Choices = choiceReduce({}, { type: "chooseSpool", slot: 0, spool: candidate({ mapping: NAMED }) });
    s = choiceReduce(s, { type: "clearSpool", slot: 0 });
    expect(s[0].spool).toBeNull() ; expect(s[0].preset).toBeNull();
    s = choiceReduce({}, { type: "chooseSpool", slot: 0, spool: candidate({ mapping: PROVEN }) });
    s = choiceReduce(s, { type: "clearSpool", slot: 0 });
    expect(s[0].preset?.confirmed).toBe(true);
  });

  it("reset clears every slot", () => {
    const s = choiceReduce({ 0: { ...emptyChoice, keepOwn: true } }, { type: "reset" });
    expect(s).toEqual({});
  });
});

describe("remember this mapping", () => {
  const chosen = (over: Partial<MaterialCandidate> = {}, name = "Snapmaker PLA SnapSpeed @U1"): Choices =>
    choiceReduce(choiceReduce({}, { type: "chooseSpool", slot: 0, spool: candidate(over) }), { type: "pickPreset", slot: 0, name });

  it("is offered for a confirmed spool/preset pair, never for keep-own or an unconfirmed preset", () => {
    expect(canRemember(chosen()[0])).toBe(true);
    expect(canRemember(emptyChoice)).toBe(false);
    expect(canRemember(choiceReduce(chosen(), { type: "keepOwn", slot: 0 })[0])).toBe(false);
    expect(canRemember(choiceReduce({}, { type: "chooseSpool", slot: 0, spool: candidate({ mapping: NAMED }) })[0])).toBe(false);
  });

  it("is not offered again for a mapping that is already saved for exactly that preset", () => {
    const same = choiceReduce({}, { type: "chooseSpool", slot: 0, spool: candidate({ mapping: PROVEN }) });
    expect(canRemember(same[0])).toBe(false);
    expect(canRemember(chosen({ mapping: PROVEN }, "Snapmaker PLA SnapSpeed @U1")[0])).toBe(true);   // a different preset
  });

  it("saves nothing unless the person ticked it", () => {
    expect(mappingRequests(chosen(), "0.4")).toEqual([]);
  });

  it("for this spool only, and for similar spools", () => {
    const spoolOnly = choiceReduce(chosen(), { type: "remember", slot: 0, mode: "spool" });
    expect(mappingRequests(spoolOnly, "0.4")).toEqual([{
      scope: "spool", provider: "spoolease", spool_id: "124", preset: "Snapmaker PLA SnapSpeed @U1", nozzle: "0.4", origin: "manual" }]);
    const similar = choiceReduce(chosen(), { type: "remember", slot: 0, mode: "signature" });
    expect(mappingRequests(similar, "0.4")).toEqual([{
      scope: "signature", provider: "spoolease", vendor: "Yoopai", material: "PLA", subtype: "Matte",
      preset: "Snapmaker PLA SnapSpeed @U1", nozzle: "0.4", origin: "manual" }]);
  });

  it("a name the provider supplied and the person confirmed is saved as such", () => {
    let s = choiceReduce({}, { type: "chooseSpool", slot: 0, spool: candidate({ mapping: NAMED }) });
    s = choiceReduce(choiceReduce(s, { type: "confirmPreset", slot: 0 }), { type: "remember", slot: 0, mode: "spool" });
    expect(mappingRequests(s, "0.4")[0].origin).toBe("exact_name");
  });

  it("changing the preset or the spool turns Remember off again", () => {
    let s = choiceReduce(chosen(), { type: "remember", slot: 0, mode: "spool" });
    s = choiceReduce(s, { type: "pickPreset", slot: 0, name: "Generic PETG @U1" });
    expect(s[0].remember).toBe("off");
  });
});

describe("display helpers", () => {
  it("amount uses the spool list's words", () => {
    expect(amountText({ remaining_g: 412, remaining_quality: "tracked" })).toBe("412 g tracked");
    expect(amountText({ remaining_g: 250, remaining_quality: "derived" })).toBe("250 g estimated");
    expect(amountText({ remaining_g: null, remaining_quality: null })).toBe("weight unknown");
  });

  it("filters the installed presets by every word typed", () => {
    const presets = [
      { base_name: "Snapmaker PLA Matte @U1", preset_name: "Snapmaker PLA Matte @U1", vendor: "Snapmaker", filament_type: "PLA", fingerprint: "a" },
      { base_name: "Generic PETG @U1", preset_name: "Generic PETG @U1 0.4 nozzle", vendor: "Generic", filament_type: "PETG", fingerprint: "b" },
    ];
    expect(filterPresets(presets, "").length).toBe(2);
    expect(filterPresets(presets, "matte pla").map((p) => p.base_name)).toEqual(["Snapmaker PLA Matte @U1"]);
    expect(filterPresets(presets, "petg generic").map((p) => p.base_name)).toEqual(["Generic PETG @U1"]);
    expect(filterPresets(presets, "nylon")).toEqual([]);
  });

  it("blocked facts are the engine's own words and nothing more", () => {
    expect(blockedFacts({ blocked: false })).toBeNull();
    const facts = blockedFacts({ blocked: true, errors: ["Prepare stopped: x"], settings_summary: { project_materials: { guard: {
      applies: true, blocking: true, shared: [], warnings: [], resolution: "Pick different presets.",
      conflicts: [{ key: "filament_vendor", preset: "P @U1", slots: [0, 1], declared_in: [0], values: {} }] } } } });
    expect(facts).toEqual({ message: "Prepare stopped: x", resolution: "Pick different presets.",
      conflicts: [{ key: "filament_vendor", preset: "P @U1", slots: [0, 1], declared_in: [0], values: {} }] });
  });
});
