import { describe, it, expect } from "vitest";
import type { ReadyNowProject, ReadyNowResult } from "@/api";
import {
  DISPLAY_ORDER, BUCKET_META, groupResults, rowChips, rowStatus, rowActions,
  summarySentence, progressText, confidenceLabel, AMOUNT_CHIP, READY_NOW_FOOTER,
} from "./readyNow";

function row(over: Partial<ReadyNowProject> = {}): ReadyNowProject {
  return {
    path: "C:/m/a.3mf", name: "a.3mf", bucket: "ready_now", top_reason: "Every material it asks for is loaded.",
    top_action: null, confidence: "likely", evidence: [], unknowns: [], colour_notes: [],
    amount_checked: true, slots: [], file_state: "ok", ...over,
  };
}

describe("readyNow display order and labels", () => {
  it("lists the five buckets in the approved order", () => {
    expect(DISPLAY_ORDER.map((b) => BUCKET_META[b].label)).toEqual([
      "Ready now", "One change away", "Needs preparation", "Needs attention", "Can't determine",
    ]);
  });
  it("groups stably, always returning all five sections", () => {
    const rows = [
      row({ path: "1", bucket: "needs_attention" }), row({ path: "2", bucket: "ready_now" }),
      row({ path: "3", bucket: "ready_now" }), row({ path: "4", bucket: "cant_determine" }),
    ];
    const sections = groupResults(rows);
    expect(sections.map((s) => s.bucket)).toEqual(DISPLAY_ORDER);
    expect(sections[0].items.map((r) => r.path)).toEqual(["2", "3"]);   // input (newest-first) order kept
    expect(sections[1].items).toEqual([]);
  });
  it("copes with nothing", () => {
    expect(groupResults(null).every((s) => s.items.length === 0)).toBe(true);
  });
});

describe("wording rules", () => {
  it("never says plain 'ready' when the amount was not checked", () => {
    const r = row({ amount_checked: false });
    expect(rowStatus(r)).toBe("Ready now — amount not checked");
    expect(rowChips(r).map((c) => c.label)).toContain(AMOUNT_CHIP);
  });
  it("says plain 'Ready now' only when the amount was checked", () => {
    const r = row({ amount_checked: true });
    expect(rowStatus(r)).toBe("Ready now");
    expect(rowChips(r)).toEqual([]);
  });
  it("shows a colour chip when there is a colour note", () => {
    const chips = rowChips(row({ colour_notes: ["Right material, different colour"] }));
    expect(chips.map((c) => c.id)).toContain("colour");
  });
  it("the amount chip belongs to ready rows only", () => {
    expect(rowChips(row({ bucket: "cant_determine", amount_checked: false }))).toEqual([]);
  });
  it("labels confidence in words", () => {
    expect(confidenceLabel("unknown")).toBe("Unknown");
    expect(confidenceLabel("likely")).toBe("Likely");
  });
  it("footer is advisory and promises no changes", () => {
    expect(READY_NOW_FOOTER).toMatch(/Advisory only/);
    expect(READY_NOW_FOOTER).toMatch(/does not change your printer, slot mapping or inventory/);
  });
});

describe("actions", () => {
  it("opens any project whose file is fine", () => {
    expect(rowActions(row()).map((a) => a.id)).toEqual(["open"]);
  });
  it("offers preparation only for needs_preparation", () => {
    const acts = rowActions(row({ bucket: "needs_preparation" }));
    expect(acts.map((a) => a.label)).toEqual(["Open project", "Prepare a U1 copy"]);
  });
  it("offers nothing for a missing or unreadable file", () => {
    expect(rowActions(row({ file_state: "missing" }))).toEqual([]);
    expect(rowActions(row({ file_state: "unreadable", bucket: "needs_preparation" }))).toEqual([]);
  });
});

describe("summary and progress", () => {
  const result = (rows: ReadyNowProject[], extra: Partial<ReadyNowResult> = {}): ReadyNowResult =>
    ({ results: rows, ...extra });
  it("summarises counts", () => {
    const s = summarySentence(result([row(), row({ bucket: "needs_attention" })]));
    expect(s).toBe("2 projects checked · 1 ready now · 1 needs attention");
  });
  it("says so when the library was capped", () => {
    expect(summarySentence(result([row()], { scanned: 50, library_total: 80 }))).toContain("newest 50 of 80");
  });
  it("is honest while empty", () => {
    expect(summarySentence(null, true)).toBe("Checking your library…");
    expect(summarySentence(result([]))).toBe("No projects in your library yet.");
  });
  it("reports progress", () => {
    expect(progressText({ done: 3, total: 10 })).toBe("Checked 3 of 10");
    expect(progressText({ done: 0, total: null })).toBe("Reading your library…");
  });
});
