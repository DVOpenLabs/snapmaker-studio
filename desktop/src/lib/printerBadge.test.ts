import { describe, expect, it } from "vitest";
import { printerBadge } from "./printerBadge";
import real from "./printerHealth.real.json";

const ready = { healthy: true, klippy_state: "ready" };
type Health = { available: boolean; drivers: string[]; conditions: { id: string; text: string }[]; verdict: string };
const cases = real as unknown as Record<string, Health>;

describe("printerBadge", () => {
  it("says Healthy only with ready firmware and no concerns", () => {
    expect(printerBadge({ diag: ready, concerns: 0 })).toEqual({ label: "Healthy", ok: true });
  });
  it("never says Healthy with concerns (ready firmware, no firmware warning, one failed print)", () => {
    expect(printerBadge({ diag: ready, concerns: 1 })).toEqual({ label: "See concerns", ok: false });
  });
  it("keeps the firmware state when it is not ready", () => {
    expect(printerBadge({ diag: { healthy: false, klippy_state: "shutdown" }, concerns: 0 })).toEqual({ label: "shutdown", ok: false });
    expect(printerBadge({ diag: { healthy: false, klippy_state: "shutdown" }, concerns: 2 })?.label).toBe("shutdown");
  });
  it("shows nothing before diagnostics arrive", () => expect(printerBadge({ diag: undefined, concerns: 3 })).toBeNull());
});

// The chip, the health card and the report's printer line all count `conditions`. These are REAL health results
// (written by the backend's own formatter; a backend test fails if the file drifts from it).
describe("chip and health card agree on real health results", () => {
  for (const [name, h] of Object.entries(cases)) {
    it(`${name}: one card line per condition, and the chip follows the same count`, () => {
      const concerns = h.conditions.length;
      const lines = h.drivers.filter((d) => !/no problems found/i.test(d));
      expect(lines).toEqual(h.conditions.map((c) => c.text));
      const badge = printerBadge({ diag: ready, concerns });
      if (concerns === 0) expect(badge?.label).toBe("Healthy");
      else expect(badge?.label).not.toBe("Healthy");
      expect(/nothing concerning/i.test(h.verdict)).toBe(concerns === 0);
    });
  }
  it("failure history with a streak is ONE line, not two", () => {
    const both = cases["failures-and-firmware-warning"];
    expect(both.conditions.map((c) => c.id)).toEqual(["printer-failure-history", "firmware-warning"]);
    expect(both.conditions[0].text).toMatch(/8 of the last 10 prints failed; 6 prints failed in a row/);
  });
});
