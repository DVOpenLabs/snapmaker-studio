import { describe, expect, it } from "vitest";
import { printerBadge } from "./printerBadge";

const ready = { healthy: true, klippy_state: "ready" };

describe("printerBadge", () => {
  it("says Healthy only with ready firmware and no listed concerns", () => {
    expect(printerBadge({ diag: ready, drivers: ["No problems found in firmware state or recent history."] })).toEqual({ label: "Healthy", ok: true });
    expect(printerBadge({ diag: ready, drivers: [] })).toEqual({ label: "Healthy", ok: true });
  });
  it("never says Healthy while the health card lists a failed-print concern (ready firmware, no warning)", () => {
    const b = printerBadge({ diag: ready, drivers: ["1 of the last 5 prints failed"] });
    expect(b).toEqual({ label: "See concerns", ok: false });
  });
  it("never says Healthy with a firmware warning either, and keeps the firmware state when it is not ready", () => {
    expect(printerBadge({ diag: ready, drivers: ["1 firmware warning"] })?.label).not.toBe("Healthy");
    expect(printerBadge({ diag: { healthy: false, klippy_state: "shutdown" }, drivers: [] })).toEqual({ label: "shutdown", ok: false });
    expect(printerBadge({ diag: { healthy: false, klippy_state: "shutdown" }, drivers: ["x failed"] })?.label).toBe("shutdown");
  });
  it("shows nothing before diagnostics arrive", () => expect(printerBadge({ diag: undefined, drivers: ["1 of the last 5 prints failed"] })).toBeNull());
});
