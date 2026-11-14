import { describe, expect, it } from "vitest";
import { settingNote } from "./settingNotes";

const change = (extra: Record<string, unknown>) => ({ key: "k", old: "a", new: "b", ...extra });

describe("settingNote", () => {
  it("prefers the engine's explanation", () => {
    expect(settingNote(change({ reason: "short", explanation: "Because the importer says so." }))).toEqual({ note: "Because the importer says so.", source: null, kind: null });
  });

  it("falls back to a specific reason", () => {
    expect(settingNote(change({ reason: "the creator left the brim on automatic" }))).toEqual({ note: "the creator left the brim on automatic", source: null, kind: null });
  });

  it("says nothing when the reason only restates that the setting changed", () => {
    for (const reason of [
      "changed only for U1 compatibility",
      "carried over to U1 toolheads (values preserved)",
      "available with the recommended U1 profile",
      "U1 machine profile setting applied",
      "U1 project identity normalized",
      "U1 compatibility clamp: -1 → 5",
    ]) expect(settingNote(change({ reason }))).toBeNull();
  });

  it("says nothing when there is no reason at all", () => {
    expect(settingNote(change({}))).toBeNull();
    expect(settingNote(change({ reason: "  ", explanation: " " }))).toBeNull();
  });

  it("keeps an honest 'not reported' reason, because that is itself a statement of what Studio does not know", () => {
    expect(settingNote(change({ reason: "change was not reported by the repair pipeline" }))).toEqual({ note: "change was not reported by the repair pipeline", source: null, kind: null });
  });

  it("returns source and kind with the same note record", () => {
    expect(settingNote(change({ explanation: "It was outside the range.", source: "Studio's valid range for this setting", kind: "engine" }))).toEqual({
      note: "It was outside the range.", source: "Studio's valid range for this setting", kind: "engine",
    });
  });
});
