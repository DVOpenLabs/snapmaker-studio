import { describe, expect, it } from "vitest";
import {
  buildSpoolSaveBody, hasErrors, remainingLabel, validateColor, validateSpoolForm, validateUsedG,
  validateWeight, type SpoolSaveDraft,
} from "./spoolForm";

function draft(overrides: Partial<SpoolSaveDraft> = {}): SpoolSaveDraft {
  return {
    material: "PLA", subtype: "", color: "", colorTouched: false, vendor: "",
    startingG: "", startingGTouched: false, remainingG: "", remainingGTouched: false,
    notes: "", ...overrides,
  };
}

describe("validateColor", () => {
  it("never resends an untouched colour", () => {
    expect(validateColor(undefined, false)).toEqual({ ok: true, send: undefined });
    expect(validateColor("legacy free text", false)).toEqual({ ok: true, send: undefined });
  });

  it("clears when touched and left empty", () => {
    expect(validateColor("", true)).toEqual({ ok: true, send: "" });
  });

  it("normalises a hex colour to uppercase with a leading #", () => {
    expect(validateColor("1a2b3c", true)).toEqual({ ok: true, send: "#1A2B3C" });
    expect(validateColor("#1a2b3c", true)).toEqual({ ok: true, send: "#1A2B3C" });
  });

  it("rejects a malformed colour", () => {
    const r = validateColor("notacolour", true);
    expect(r.ok).toBe(false);
  });
});

describe("validateWeight", () => {
  it("treats an empty string as no weight recorded", () => {
    expect(validateWeight("")).toEqual({ ok: true, value: null });
  });

  it("accepts the bounds", () => {
    expect(validateWeight("0")).toEqual({ ok: true, value: 0 });
    expect(validateWeight("10000")).toEqual({ ok: true, value: 10000 });
  });

  it("rejects out-of-range and non-numeric values", () => {
    expect(validateWeight("-1").ok).toBe(false);
    expect(validateWeight("10001").ok).toBe(false);
    expect(validateWeight("abc").ok).toBe(false);
  });
});

describe("validateUsedG", () => {
  it("requires a positive amount", () => {
    expect(validateUsedG("").ok).toBe(false);
    expect(validateUsedG("0").ok).toBe(false);
    expect(validateUsedG("10001").ok).toBe(false);
  });

  it("accepts a value in (0, 10000]", () => {
    expect(validateUsedG("50")).toEqual({ ok: true, value: 50 });
    expect(validateUsedG("10000")).toEqual({ ok: true, value: 10000 });
  });
});

describe("validateSpoolForm", () => {
  it("requires a material", () => {
    const errors = validateSpoolForm({
      material: "  ", color: undefined, colorTouched: false, startingG: "", remainingG: "",
    });
    expect(errors.material).toBeDefined();
    expect(hasErrors(errors)).toBe(true);
  });

  it("passes with just a material and no other fields touched", () => {
    const errors = validateSpoolForm({
      material: "PLA", color: undefined, colorTouched: false, startingG: "", remainingG: "",
    });
    expect(hasErrors(errors)).toBe(false);
  });

  it("collects weight and colour errors together", () => {
    const errors = validateSpoolForm({
      material: "PLA", color: "nope", colorTouched: true, startingG: "-5", remainingG: "99999",
    });
    expect(errors.color).toBeDefined();
    expect(errors.startingG).toBeDefined();
    expect(errors.remainingG).toBeDefined();
  });
});

describe("remainingLabel", () => {
  it("says when nothing was recorded", () => {
    expect(remainingLabel(null, "unknown")).toBe("no weight recorded");
  });

  it("labels a directly entered figure as entered by you (not estimated)", () => {
    expect(remainingLabel(320, "user_confirmed")).toBe("320 g · entered by you");
  });

  it("labels a figure worked out from 'Record filament used' as estimated (not entered by you)", () => {
    expect(remainingLabel(280, "derived")).toBe("280 g · estimated from what you recorded");
  });

  it("labels a provider's own measurement as tracked, not entered or estimated", () => {
    expect(remainingLabel(150, "tracked")).toBe("150 g · tracked by your provider");
  });

  it("appends the as-of date when given", () => {
    expect(remainingLabel(320, "user_confirmed", "2026-09-12T00:00:00Z"))
      .toMatch(/^320 g · entered by you · \d/);
    expect(remainingLabel(280, "derived", "2026-09-12T00:00:00Z"))
      .toMatch(/^280 g · estimated from what you recorded · \d/);
  });

  it("omits the date suffix when none is given", () => {
    expect(remainingLabel(320, "user_confirmed")).not.toContain(" · 1");
  });
});

describe("buildSpoolSaveBody", () => {
  it("always sends the text fields, trimmed", () => {
    const body = buildSpoolSaveBody(draft({ material: "  PLA  ", vendor: " Acme " }));
    expect(body.material).toBe("PLA");
    expect(body.vendor).toBe("Acme");
  });

  it("omits both weights when neither was touched", () => {
    const body = buildSpoolSaveBody(draft({ startingG: "100", remainingG: "50" }));
    expect("starting_g" in body).toBe(false);
    expect("remaining_g" in body).toBe(false);
  });

  it("sends remaining_g only when the user touched that field", () => {
    const body = buildSpoolSaveBody(draft({ remainingG: "200", remainingGTouched: true }));
    expect(body.remaining_g).toBe(200);
    expect("starting_g" in body).toBe(false);
  });

  it("sends starting_g only when the user touched that field, independent of remaining_g", () => {
    const body = buildSpoolSaveBody(draft({ startingG: "1000", startingGTouched: true }));
    expect(body.starting_g).toBe(1000);
    expect("remaining_g" in body).toBe(false);
  });

  it("omits colour when untouched, even if the row has a legacy free-text colour", () => {
    const body = buildSpoolSaveBody(draft({ color: "sort of blue", colorTouched: false }));
    expect("color" in body).toBe(false);
  });

  it("sends a cleared colour as an empty string when touched", () => {
    const body = buildSpoolSaveBody(draft({ color: "", colorTouched: true }));
    expect(body.color).toBe("");
  });

  it("sends an empty string (not null) when the user touched and then emptied remaining_g (CodeRabbit PR #41 #3)", () => {
    // Backend contract: "" clears a weight; null/missing preserves it. Before
    // this fix, an emptied-but-touched field sent `null`, which the backend
    // treats as "preserve" — the row kept showing the old weight forever.
    const body = buildSpoolSaveBody(draft({ remainingG: "", remainingGTouched: true }));
    expect(body.remaining_g).toBe("");
  });

  it("sends an empty string (not null) when the user touched and then emptied starting_g", () => {
    const body = buildSpoolSaveBody(draft({ startingG: "", startingGTouched: true }));
    expect(body.starting_g).toBe("");
  });

  it("still sends the numeric value when a touched weight has one", () => {
    const body = buildSpoolSaveBody(draft({ remainingG: "320", remainingGTouched: true }));
    expect(body.remaining_g).toBe(320);
  });
});
