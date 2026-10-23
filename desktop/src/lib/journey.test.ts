import { describe, expect, it } from "vitest";
import { deriveJourney, type JourneyFacts } from "@/lib/journey";

const base: JourneyFacts = {
  hasProject: true,
  check: { status: "done", prepareBlocked: false },
  materialsHolding: false, preparing: false, prepareFailed: false,
  prepared: false, unvalidated: false, hasSliced: false,
};
const states = (f: Partial<JourneyFacts>) =>
  Object.fromEntries(deriveJourney({ ...base, ...f }).stages.map((s) => [s.id, s.state]));

describe("journey stages", () => {
  it("names the five stages in order", () => {
    expect(deriveJourney(base).stages.map((s) => s.label)).toEqual([
      "Open project", "Choose materials", "Create U1 copy", "Open in Orca", "Compare slice",
    ]);
  });

  it("with nothing open, only Open project is current and there is no action", () => {
    const j = deriveJourney({ ...base, hasProject: false });
    expect(j.current).toBe("open");
    expect(j.primary.kind).toBe("none");
    expect(states({ hasProject: false }).copy).toBe("todo");
  });

  it("only one stage is current: materials are optional until choices are held", () => {
    expect(states({}).materials).toBe("todo");
    expect(deriveJourney(base).stages.find((s) => s.id === "materials")!.status).toBe("optional, not started");
    expect(states({}).copy).toBe("current");
    expect(states({ materialsHolding: true })).toMatchObject({ materials: "current", copy: "todo" });
  });

  it("a checked project offers exactly one primary action: Create U1 copy", () => {
    const j = deriveJourney(base);
    expect(j.current).toBe("copy");
    expect(j.primary).toEqual({ kind: "create", label: "Create U1 copy" });
  });

  it("holding material choices makes reviewing them the primary action, not a second Create", () => {
    const j = deriveJourney({ ...base, materialsHolding: true });
    expect(j.current).toBe("materials");
    expect(j.primary).toMatchObject({ kind: "review-materials", label: "Review materials" });
  });

  it("does not offer Create before the check has settled", () => {
    for (const status of ["idle", "loading"] as const) {
      const j = deriveJourney({ ...base, check: { status, prepareBlocked: false } });
      expect(j.primary.disabledReason).toBeTruthy();
    }
  });

  it("a failed check offers to check again and does not call the copy step current", () => {
    const j = deriveJourney({ ...base, check: { status: "error", prepareBlocked: false } });
    expect(j.primary.kind).toBe("retry-check");
    expect(states({ check: { status: "error", prepareBlocked: false } }).copy).toBe("todo");
  });

  it("a project Studio would refuse is blocked, with the reason", () => {
    const f = { check: { status: "done" as const, prepareBlocked: true } };
    const s = states(f);
    expect(s.copy).toBe("blocked");
    expect(s.materials).toBe("blocked");
    expect(deriveJourney({ ...base, ...f }).primary.disabledReason).toMatch(/cannot prepare/);
  });

  it("a validated copy moves to Open in Orca; the hand-off is never offered earlier", () => {
    expect(deriveJourney(base).primary.kind).not.toBe("open-orca");
    const j = deriveJourney({ ...base, prepared: true });
    expect(j.current).toBe("orca");
    expect(j.primary.kind).toBe("open-orca");
    expect(states({ prepared: true })).toMatchObject({ materials: "done", copy: "done", orca: "current", compare: "todo" });
  });

  it("a copy written but not validated is a review, not a hand-off", () => {
    const j = deriveJourney({ ...base, unvalidated: true });
    expect(j.primary.kind).toBe("create");
    expect(states({ unvalidated: true }).copy).toBe("review");
  });

  it("a refused or failed Prepare is an error, not progress", () => {
    expect(states({ prepareFailed: true }).copy).toBe("error");
  });

  it("while preparing, the copy step is current and the action is disabled", () => {
    const j = deriveJourney({ ...base, preparing: true });
    expect(j.stages.find((s) => s.id === "copy")!.state).toBe("current");
    expect(j.primary.disabledReason).toBeTruthy();
  });

  it("a sliced G-code makes Compare slice current", () => {
    const j = deriveJourney({ ...base, prepared: true, hasSliced: true });
    expect(j.current).toBe("compare");
    expect(j.primary.kind).toBe("compare");
    expect(states({ prepared: true, hasSliced: true })).toMatchObject({ orca: "done", compare: "current" });
  });

  it("a sliced file without an open project is not a comparison", () => {
    expect(states({ hasProject: false, hasSliced: true }).compare).toBe("todo");
  });

  it("a copy never puts Open in Orca forward for a project Studio now says it cannot prepare", () => {
    const j = deriveJourney({ ...base, prepared: true, check: { status: "done", prepareBlocked: true } });
    expect(j.primary.kind).toBe("none");
  });
});
