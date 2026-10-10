import { describe, it, expect } from "vitest";
import { verdictStatus } from "./simple";

describe("verdictStatus — beginner action labels (advisory, no guarantees)", () => {
  it("maps each verdict to its action phrase", () => {
    expect(verdictStatus("READY").label).toBe("U1 compatible");
    expect(verdictStatus("REPAIRABLE").label).toBe("Needs a fix first");
    expect(verdictStatus("CONVERTIBLE").label).toBe("Can prepare a U1 copy");
    expect(verdictStatus("HIGH_RISK").label).toBe("Review before printing");
  });

  it("a readable file Studio cannot prepare is neither fixable nor compatible", () => {
    const s = verdictStatus("REPAIRABLE", true);
    expect(s.label).toBe("Review in Orca first");
    expect(s.tone).toBe("risk");
    expect(verdictStatus("READY", true).label).toBe("Review in Orca first");
    expect(verdictStatus("HIGH_RISK", true).label).toBe("Review before printing");
    expect(verdictStatus("REPAIRABLE", false).label).toBe("Needs a fix first");
  });

  it("is case-insensitive and tolerates junk", () => {
    expect(verdictStatus("ready").label).toBe("U1 compatible");
    expect(verdictStatus(null).label).toBe("Checking…");
    expect(verdictStatus("weird").label).toBe("Checking…");
  });

  it("never uses guarantee language", () => {
    for (const v of ["READY", "REPAIRABLE", "CONVERTIBLE", "HIGH_RISK"]) {
      const l = verdictStatus(v).label.toLowerCase();
      expect(l).not.toMatch(/guarantee|100%|will print|will succeed/);
    }
  });
});
