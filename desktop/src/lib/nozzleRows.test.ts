import { describe, expect, it } from "vitest";
import {
  countMismatchNote, diametersForRemove, diametersForSaveAll, diametersForUpdate,
  diametersFromStatus, hasAnyConflict, nozzleRows, rowCountLabel, showsNothingReportedBanner,
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
