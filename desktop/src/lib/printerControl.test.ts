import { describe, it, expect } from "vitest";
import {
  availableActions, needsConfirm, confirmCopy, canStart, toPrintState, confirmStillValid,
} from "./printerControl";

describe("Printer control gating (Phase B safety)", () => {
  it("offline printer blocks ALL controls", () => {
    expect(availableActions("printing", false)).toEqual([]);
    expect(availableActions("standby", false)).toEqual([]);
    expect(canStart("standby", false)).toBe(false);
  });

  it("idle printer can start (and e-stop), not pause/cancel", () => {
    const a = availableActions("standby", true);
    expect(a).toContain("start");
    expect(a).toContain("emergency_stop");
    expect(a).not.toContain("pause");
    expect(a).not.toContain("cancel");
  });

  it("printing → pause + cancel + e-stop, never start", () => {
    const a = availableActions("printing", true);
    expect(a).toEqual(expect.arrayContaining(["pause", "cancel", "emergency_stop"]));
    expect(a).not.toContain("start");
    expect(a).not.toContain("resume");
  });

  it("paused → resume + cancel + e-stop", () => {
    const a = availableActions("paused", true);
    expect(a).toEqual(expect.arrayContaining(["resume", "cancel", "emergency_stop"]));
    expect(a).not.toContain("pause");
  });

  it("start, cancel, emergency-stop REQUIRE confirmation; pause/resume do not", () => {
    expect(needsConfirm("start")).toBe(true);
    expect(needsConfirm("cancel")).toBe(true);
    expect(needsConfirm("emergency_stop")).toBe(true);
    expect(needsConfirm("pause")).toBe(false);
    expect(needsConfirm("resume")).toBe(false);
  });

  it("confirm copy shows filename for start and is non-guaranteeing", () => {
    const c = confirmCopy("start", "cube.gcode");
    expect(c.title).toContain("cube.gcode");
    expect(c.body.toLowerCase()).toContain("clear, loaded, and ready");
    expect(c.body.toLowerCase()).not.toMatch(/guarantee|100%|will succeed/);
  });

  it("cancel + e-stop copy are flagged danger", () => {
    expect(confirmCopy("cancel").danger).toBe(true);
    expect(confirmCopy("emergency_stop").danger).toBe(true);
    expect(confirmCopy("start").danger).toBe(false);
  });

  it("normalizes Moonraker states, unknown for junk", () => {
    expect(toPrintState("Printing")).toBe("printing");
    expect(toPrintState(null)).toBe("unknown");
    expect(toPrintState("weird")).toBe("unknown");
  });
});

describe("confirmation binding", () => {
  const cancel = { id: 1, action: "cancel" as const, host: "printer-a" };

  it("stays valid for the same printer while it still allows the action", () => {
    expect(confirmStillValid(cancel, { host: "printer-a", online: true, printState: "printing" })).toBe(true);
    expect(confirmStillValid(cancel, { host: "printer-a", online: true, printState: "paused" })).toBe(true);
  });

  it("is withdrawn when the connected printer changes or disappears", () => {
    expect(confirmStillValid(cancel, { host: "printer-b", online: true, printState: "printing" })).toBe(false);
    expect(confirmStillValid(cancel, { host: null, online: true, printState: "printing" })).toBe(false);
  });

  it("is withdrawn when the printer stops answering", () => {
    expect(confirmStillValid(cancel, { host: "printer-a", online: false, printState: "printing" })).toBe(false);
  });

  it("is withdrawn when the printer can no longer take that action", () => {
    // the print finished while the prompt was open: there is nothing left to cancel
    expect(confirmStillValid(cancel, { host: "printer-a", online: true, printState: "complete" })).toBe(false);
    // starting needs an idle printer
    const start = { id: 2, action: "start" as const, host: "printer-a", filename: "job.gcode" };
    expect(confirmStillValid(start, { host: "printer-a", online: true, printState: "printing" })).toBe(false);
    expect(confirmStillValid(start, { host: "printer-a", online: true, printState: "standby" })).toBe(true);
  });

  it("emergency stop only needs a reachable printer", () => {
    const stop = { id: 3, action: "emergency_stop" as const, host: "printer-a" };
    expect(confirmStillValid(stop, { host: "printer-a", online: true, printState: "error" })).toBe(true);
    expect(confirmStillValid(stop, { host: "printer-a", online: false, printState: "error" })).toBe(false);
  });
});
