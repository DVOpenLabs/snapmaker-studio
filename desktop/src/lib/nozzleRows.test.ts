import { describe, expect, it } from "vitest";
import {
  countMismatchNote, diametersForRemove, diametersForSaveAll, diametersForUpdate,
  diametersFromStatus, hasAnyConflict, nozzleActionsVisible, nozzleRows, nozzleSummaryLine,
  rowCountLabel, showsNothingReportedBanner,
} from "./nozzleRows";
import type { NozzleStatus, NozzleToolhead } from "@/api";

function toolhead(overrides: Partial<NozzleToolhead>): NozzleToolhead {
  return {
    toolhead: 0, diameter: null, source: "unknown", confirmed_at: null,
    confirmed: null, conflict: false, out_of_range: false, ...overrides,
  };
}

function status(toolheads: NozzleToolhead[], overrides: Partial<NozzleStatus> = {}): NozzleStatus {
  return {
    host: "u1.local", port: 7125, reachable: true, live: null, live_error: null,
    toolhead_count: toolheads.length, toolhead_count_source: "printer", revision: 1,
    observed_at: "2026-09-01T00:00:00Z", count_mismatch: false, storage_error: null,
    toolheads, ...overrides,
  };
}

describe("nozzleRows", () => {
  it("returns nothing for a null status", () => {
    expect(nozzleRows(null)).toEqual([]);
  });

  it("shows a live printer reading as reported and not removable", () => {
    const rows = nozzleRows(status([toolhead({ toolhead: 0, diameter: 0.4, source: "printer" })]));
    expect(rows[0]).toMatchObject({
      toolhead: 1, diameterLabel: "0.4 mm", sourceLabel: "Printer",
      status: "reported_live", statusLabel: "Reported live", removable: false,
    });
  });

  it("shows a user confirmation as confirmed and removable", () => {
    const rows = nozzleRows(status([
      toolhead({ toolhead: 1, diameter: 0.6, source: "user", confirmed_at: "2026-09-01T00:00:00Z" }),
    ]));
    expect(rows[0].toolhead).toBe(2); // backend 0-based -> display 1-based
    expect(rows[0].status).toBe("confirmed");
    expect(rows[0].sourceLabel).toContain("You");
    expect(rows[0].removable).toBe(true);
    expect(rows[0].removeLabel).toBe("Remove my note");
  });

  it("shows unknown when nothing is known and offers no removal", () => {
    const rows = nozzleRows(status([toolhead({ source: "unknown" })]));
    expect(rows[0].status).toBe("unknown");
    expect(rows[0].statusLabel).toBe("Unknown — tell Studio");
    expect(rows[0].removable).toBe(false);
  });

  it("surfaces a conflict with both values and an update-to-printer action", () => {
    const rows = nozzleRows(status([
      toolhead({ toolhead: 0, diameter: 0.4, confirmed: 0.6, source: "printer", conflict: true }),
    ]));
    expect(rows[0].status).toBe("conflict");
    expect(rows[0].statusLabel).toContain("You noted 0.6 mm");
    expect(rows[0].statusLabel).toContain("printer reports 0.4 mm");
    expect(rows[0].updateLabel).toBe("Update my note to 0.4");
    expect(rows[0].removeLabel).toBe("Remove my note");
  });

  it("keeps an out-of-range note visible only for removal", () => {
    const rows = nozzleRows(status([
      toolhead({ toolhead: 5, confirmed: 0.4, source: "user", out_of_range: true }),
    ]));
    expect(rows[0].status).toBe("out_of_range");
    expect(rows[0].removable).toBe(true);
    expect(rows[0].updateLabel).toBeNull();
  });

  it("detects any conflict across toolheads", () => {
    expect(hasAnyConflict(status([toolhead({ conflict: true })]))).toBe(true);
    expect(hasAnyConflict(status([toolhead({})]))).toBe(false);
    expect(hasAnyConflict(null)).toBe(false);
  });
});

describe("rowCountLabel", () => {
  it("prefers the live list length, labelled from the printer", () => {
    expect(rowCountLabel(status([], { live: [0.4, 0.4] }))).toEqual({
      count: 2, sourceLabel: "counted from your printer",
    });
  });

  it("falls back to the profile toolhead_count when there is no live list", () => {
    expect(rowCountLabel(status([], { live: null, toolhead_count: 4, toolhead_count_source: "profile" })))
      .toEqual({ count: 4, sourceLabel: "from the U1 profile — connect the printer to confirm" });
  });

  it("returns null for a null status", () => {
    expect(rowCountLabel(null)).toBeNull();
  });
});

describe("countMismatchNote", () => {
  it("is null unless the backend flagged a mismatch", () => {
    expect(countMismatchNote(status([]))).toBeNull();
    expect(countMismatchNote(status([], { count_mismatch: true }))).not.toBeNull();
  });
});

describe("diametersFromStatus", () => {
  it("returns the stored/confirmed value per position, in toolhead order", () => {
    const s = status([
      toolhead({ toolhead: 1, confirmed: 0.6 }),
      toolhead({ toolhead: 0, confirmed: 0.4 }),
    ]);
    expect(diametersFromStatus(s)).toEqual([0.4, 0.6]);
  });

  it("includes an out-of-range position's stored value rather than dropping it", () => {
    const s = status([
      toolhead({ toolhead: 0, confirmed: 0.4 }),
      toolhead({ toolhead: 1, confirmed: 0.6, out_of_range: true }),
    ]);
    expect(diametersFromStatus(s)).toEqual([0.4, 0.6]);
  });

  it("indexes by TOOLHEAD NUMBER, not row position — a gap (backend omits a null out-of-range row) fills with null, never shifting later values (Opus follow-up)", () => {
    // Backend now omits an out_of_range row whose stored value is null:
    // stored [0.4, 0.4, 0.4, 0.4, null, 0.3] with count 4 arrives EXACTLY as
    // rows for toolheads 0,1,2,3,5 — toolhead 4 has no row at all (this is
    // the real current backend output, per Sol). Mapping the 5 returned rows
    // to sequential array positions would silently shift toolhead 5's 0.3
    // into slot 4.
    const s = status([
      toolhead({ toolhead: 0, confirmed: 0.4 }),
      toolhead({ toolhead: 1, confirmed: 0.4 }),
      toolhead({ toolhead: 2, confirmed: 0.4 }),
      toolhead({ toolhead: 3, confirmed: 0.4 }),
      toolhead({ toolhead: 5, diameter: 0.3, confirmed: 0.3, source: "user", out_of_range: true }),
    ], { toolhead_count: 4, toolhead_count_source: "printer" });
    expect(diametersFromStatus(s)).toEqual([0.4, 0.4, 0.4, 0.4, null, 0.3]);
  });
});

describe("diametersForSaveAll (D3/D7/D10)", () => {
  it("sends the stored value for every position the user didn't touch", () => {
    const s = status([
      toolhead({ toolhead: 0, confirmed: 0.4 }),
      toolhead({ toolhead: 1, confirmed: 0.6 }),
    ]);
    expect(diametersForSaveAll(s, () => "")).toEqual([0.4, 0.6]);
  });

  it("overrides only the position the draft touched", () => {
    const s = status([
      toolhead({ toolhead: 0, confirmed: 0.4 }),
      toolhead({ toolhead: 1, confirmed: 0.6 }),
    ]);
    const draftFor = (t0: number) => (t0 === 1 ? "0.8" : "");
    expect(diametersForSaveAll(s, draftFor)).toEqual([0.4, 0.8]);
  });

  it("turns a 'not_sure' draft choice into null", () => {
    const s = status([toolhead({ toolhead: 0, confirmed: 0.4 })]);
    expect(diametersForSaveAll(s, () => "not_sure")).toEqual([null]);
  });

  it("preserves an out-of-range stored entry when Save is pressed without touching it", () => {
    const s = status([
      toolhead({ toolhead: 0, confirmed: 0.4 }),
      toolhead({ toolhead: 1, confirmed: 0.6, out_of_range: true }),
    ]);
    // Only position 0 was edited; the out-of-range note at position 1 must
    // still be sent, not silently dropped by a save built from a shorter,
    // count-truncated array.
    const draftFor = (t0: number) => (t0 === 0 ? "0.5" : "");
    expect(diametersForSaveAll(s, draftFor)).toEqual([0.5, 0.6]);
  });

  it("keeps every value at its own toolhead number with a gapped status — no value ever moves (Opus follow-up)", () => {
    // Exact current backend shape for stored [0.4,0.4,0.4,0.4,null,0.3] on a
    // 4-toolhead printer: no row at all for toolhead 4 (Sol).
    const s = status([
      toolhead({ toolhead: 0, confirmed: 0.4 }),
      toolhead({ toolhead: 1, confirmed: 0.4 }),
      toolhead({ toolhead: 2, confirmed: 0.4 }),
      toolhead({ toolhead: 3, confirmed: 0.4 }),
      toolhead({ toolhead: 5, diameter: 0.3, confirmed: 0.3, source: "user", out_of_range: true }),
    ], { toolhead_count: 4, toolhead_count_source: "printer" });
    expect(diametersForSaveAll(s, () => "")).toEqual([0.4, 0.4, 0.4, 0.4, null, 0.3]);
  });
});

describe("diametersForUpdate / diametersForRemove (D3/D10)", () => {
  it("builds the request body explicitly from status, not from component state", () => {
    const s = status([
      toolhead({ toolhead: 0, confirmed: 0.4 }),
      toolhead({ toolhead: 1, confirmed: 0.6, conflict: true, diameter: 0.4 }),
    ]);
    expect(diametersForUpdate(s, 2, 0.4)).toEqual([0.4, 0.4]);
  });

  it("removes exactly one position, keeping every other stored value", () => {
    const s = status([
      toolhead({ toolhead: 0, confirmed: 0.4 }),
      toolhead({ toolhead: 1, confirmed: 0.6 }),
    ]);
    expect(diametersForRemove(s, 2)).toEqual([0.4, null]);
  });

  it("removing toolhead 6 of a gapped status keeps array length and sends [0.4,0.4,0.4,0.4,null,null] — the gap stays a gap, the removed note doesn't land at the wrong index (Sol follow-up on CodeRabbit PR #41 #2 / Opus follow-up)", () => {
    // Exact current backend shape: an out_of_range position whose stored
    // value is null produces NO row at all — toolhead 4 has no row here,
    // only toolheads 0,1,2,3,5. Popping trailing nulls (an earlier, reverted
    // fix) could delete a NEIGHBOURING toolhead's own stored "not sure"
    // value just because it was also trailing and null, and still couldn't
    // remove a non-trailing out-of-range note at all; simply nulling the
    // targeted index (now correctly toolhead-indexed, so the gap at 4 stays
    // untouched) is sufficient.
    const s = status([
      toolhead({ toolhead: 0, confirmed: 0.4 }),
      toolhead({ toolhead: 1, confirmed: 0.4 }),
      toolhead({ toolhead: 2, confirmed: 0.4 }),
      toolhead({ toolhead: 3, confirmed: 0.4 }),
      toolhead({ toolhead: 5, diameter: 0.3, confirmed: 0.3, source: "user", out_of_range: true }),
    ], { toolhead_count: 4, toolhead_count_source: "printer" });

    expect(diametersForRemove(s, 6)).toEqual([0.4, 0.4, 0.4, 0.4, null, null]);
  });

  it("removes a non-trailing out-of-range note too, keeping array length and every other stored value", () => {
    const s = status([
      toolhead({ toolhead: 0, confirmed: 0.4 }),
      toolhead({ toolhead: 1, confirmed: 0.4 }),
      toolhead({ toolhead: 2, confirmed: 0.4 }),
      toolhead({ toolhead: 3, confirmed: 0.4 }),
      toolhead({ toolhead: 4, confirmed: 0.35, out_of_range: true }),
      toolhead({ toolhead: 5, confirmed: 0.3, out_of_range: true }),
    ], { toolhead_count: 4, toolhead_count_source: "printer" });

    expect(diametersForRemove(s, 5)).toEqual([0.4, 0.4, 0.4, 0.4, null, 0.3]);
  });

  it("Update on a gapped status changes only the targeted toolhead's own index, never shifting a later value (Opus follow-up)", () => {
    // Toolhead 4 has NO row at all (backend omits a null out_of_range row);
    // toolhead 5's row must not be mistaken for "row index 4".
    const s = status([
      toolhead({ toolhead: 0, confirmed: 0.4 }),
      toolhead({ toolhead: 1, confirmed: 0.4 }),
      toolhead({ toolhead: 2, confirmed: 0.4 }),
      toolhead({ toolhead: 3, confirmed: 0.4 }),
      toolhead({ toolhead: 5, diameter: 0.3, confirmed: 0.3, source: "user", out_of_range: true }),
    ], { toolhead_count: 4, toolhead_count_source: "printer" });
    // "Update my note to X" on toolhead 1 (1-based) must only touch index 0.
    expect(diametersForUpdate(s, 1, 0.5)).toEqual([0.5, 0.4, 0.4, 0.4, null, 0.3]);
  });
});

describe("showsNothingReportedBanner (D4)", () => {
  it("is false for a null status", () => {
    expect(showsNothingReportedBanner(null)).toBe(false);
  });

  it("is true when the printer is unreachable, even though rows still exist (profile count)", () => {
    const s = status(
      [toolhead({ toolhead: 0 }), toolhead({ toolhead: 1 })],
      { reachable: false },
    );
    expect(showsNothingReportedBanner(s)).toBe(true);
    // The banner is additive — it never means there are no rows to show (D4).
    expect(nozzleRows(s).length).toBe(2);
  });

  it("is true when every row is unknown even though the printer answered", () => {
    const s = status([toolhead({ toolhead: 0 }), toolhead({ toolhead: 1 })], { reachable: true });
    expect(showsNothingReportedBanner(s)).toBe(true);
  });

  it("is false once at least one row is reported, confirmed, or in conflict", () => {
    const s = status([toolhead({ toolhead: 0, diameter: 0.4, source: "printer" })], { reachable: true });
    expect(showsNothingReportedBanner(s)).toBe(false);
  });

  it("is false when live_error is 'not_checked' — not yet probed is not 'nothing reported' (N12)", () => {
    // A fresh confirm/clear response (backend R4-B1) is reachable:false with
    // live_error:"not_checked" for the brief window before the controller's
    // own follow-up live fetch lands — that must never flash the "no nozzle
    // size reported by this printer" banner on a printer that IS reachable.
    const s = status(
      [toolhead({ toolhead: 0, source: "user", confirmed: 0.4 })],
      { reachable: false, live_error: "not_checked" },
    );
    expect(showsNothingReportedBanner(s)).toBe(false);
  });

  it("is still true for a genuinely unreachable printer (live_error is something else)", () => {
    const s = status([toolhead({ toolhead: 0 })], { reachable: false, live_error: "unreachable" });
    expect(showsNothingReportedBanner(s)).toBe(true);
  });
});

describe("nozzleSummaryLine (CodeRabbit PR #41 #4: honest source attribution)", () => {
  it("says 'not reported' with no printer/settings verb when no rows exist", () => {
    expect(nozzleSummaryLine(null)).toBe("Nozzle sizes: not reported");
  });

  it("never attributes unknown values to the printer — offline, all-unknown case", () => {
    const s = status([toolhead({ toolhead: 0 }), toolhead({ toolhead: 1 })], { reachable: false });
    expect(nozzleSummaryLine(s)).toBe("Nozzle sizes: not reported — confirm in Settings");
  });

  it("says 'from printer' only when EVERY shown size is reported_live", () => {
    const s = status([
      toolhead({ toolhead: 0, diameter: 0.4, source: "printer" }),
      toolhead({ toolhead: 1, diameter: 0.4, source: "printer" }),
    ]);
    expect(nozzleSummaryLine(s)).toBe("Nozzles: 0.4 mm, 0.4 mm · from printer");
  });

  it("says 'from you' only when every shown size is user-confirmed", () => {
    const s = status([
      toolhead({ toolhead: 0, diameter: 0.4, source: "user", confirmed: 0.4, confirmed_at: "2026-09-01T00:00:00Z" }),
    ]);
    expect(nozzleSummaryLine(s)).toBe("Nozzle: 0.4 mm · from you");
  });

  it("describes a genuine mix honestly instead of picking one source", () => {
    const s = status([
      toolhead({ toolhead: 0, diameter: 0.4, source: "printer" }),
      toolhead({ toolhead: 1, diameter: 0.6, source: "user", confirmed: 0.6, confirmed_at: "2026-09-01T00:00:00Z" }),
    ]);
    expect(nozzleSummaryLine(s)).toBe("Nozzles: 0.4 mm, 0.6 mm · some from printer, some from you");
  });

  it("still leads with the conflict wording when any row conflicts", () => {
    const s = status([
      toolhead({ toolhead: 0, diameter: 0.4, confirmed: 0.6, source: "printer", conflict: true }),
    ]);
    expect(nozzleSummaryLine(s)).toBe("Nozzle: 0.4 mm · conflict — printer wins");
  });

  it("excludes out_of_range rows entirely from the Printer Hub line (Opus P2 follow-up)", () => {
    const s = status([
      toolhead({ toolhead: 0, diameter: 0.4, source: "printer" }),
      toolhead({ toolhead: 1, confirmed: 0.3, out_of_range: true }),
    ]);
    // Only the in-range, live-reported toolhead is described — the
    // out-of-range leftover note never appears on this line at all (it's
    // still visible, and removable, in the Settings table).
    expect(nozzleSummaryLine(s)).toBe("Nozzle: 0.4 mm · from printer");
  });

  it("never says 'from unknown' in a mix — says 'some not reported' instead (Opus P1 follow-up)", () => {
    const s = status([
      toolhead({ toolhead: 0, diameter: 0.4, source: "printer" }),
      toolhead({ toolhead: 1 }), // unknown
    ]);
    expect(nozzleSummaryLine(s)).toBe("Nozzles: 0.4 mm, — · some from printer, some not reported");
  });

  it("falls back to plain 'not reported' when every row is out_of_range (nothing left to describe)", () => {
    const s = status([
      toolhead({ toolhead: 0, confirmed: 0.3, out_of_range: true }),
      toolhead({ toolhead: 1, confirmed: 0.4, out_of_range: true }),
    ]);
    expect(nozzleSummaryLine(s)).toBe("Nozzle sizes: not reported");
  });
});

describe("nozzleActionsVisible (v1.2.0 release polish: hide Save/Remove-all when there's nothing to do)", () => {
  it("keeps the actions visible when printer data is unavailable (status null)", () => {
    expect(nozzleActionsVisible(null, false)).toBe(true);
  });

  it("hides them when every row is reported_live, no confirmation/conflict/out-of-range exists, and no draft is pending", () => {
    const s = status([
      toolhead({ toolhead: 0, diameter: 0.4, source: "printer" }),
      toolhead({ toolhead: 1, diameter: 0.6, source: "printer" }),
    ]);
    expect(nozzleActionsVisible(s, false)).toBe(false);
  });

  it("keeps them visible when a row is reported_live but still carries a stored confirmation that happens to agree (no conflict flagged)", () => {
    // deriveRow classifies this as "reported_live" (source === "printer" wins
    // the display), but a stored confirmation still exists underneath — if
    // the printer goes offline later that confirmation becomes meaningful
    // again, so Remove-all must still be reachable.
    const s = status([
      toolhead({ toolhead: 0, diameter: 0.4, source: "printer", confirmed: 0.4 }),
    ]);
    expect(nozzleActionsVisible(s, false)).toBe(true);
  });

  it("keeps them visible when any row is a conflict", () => {
    const s = status([
      toolhead({ toolhead: 0, diameter: 0.4, source: "printer" }),
      toolhead({ toolhead: 1, diameter: 0.4, confirmed: 0.6, source: "printer", conflict: true }),
    ]);
    expect(nozzleActionsVisible(s, false)).toBe(true);
  });

  it("keeps them visible when any row is out-of-range", () => {
    const s = status([
      toolhead({ toolhead: 0, diameter: 0.4, source: "printer" }),
      toolhead({ toolhead: 1, confirmed: 0.3, source: "user", out_of_range: true }),
    ]);
    expect(nozzleActionsVisible(s, false)).toBe(true);
  });

  it("keeps them visible when any row is editable (not reported_live) — e.g. unknown or user-confirmed", () => {
    const unknownRow = status([
      toolhead({ toolhead: 0, diameter: 0.4, source: "printer" }),
      toolhead({ toolhead: 1 }), // unknown
    ]);
    expect(nozzleActionsVisible(unknownRow, false)).toBe(true);

    const confirmedRow = status([
      toolhead({ toolhead: 0, diameter: 0.6, source: "user", confirmed: 0.6 }),
    ]);
    expect(nozzleActionsVisible(confirmedRow, false)).toBe(true);
  });

  it("keeps them visible whenever a draft is pending, even if the status alone would hide them", () => {
    const s = status([
      toolhead({ toolhead: 0, diameter: 0.4, source: "printer" }),
    ]);
    expect(nozzleActionsVisible(s, true)).toBe(true);
  });
});
