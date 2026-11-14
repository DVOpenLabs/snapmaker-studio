import { describe, expect, it } from "vitest";
import { deriveSteps, nextAction, preparedReady, type JobFacts } from "@/lib/jobProgress";

const base: JobFacts = {
  hasProject: true,
  doctor: { status: "done", prepareBlocked: false, verdict: "READY" },
  convert: { status: "idle", blocked: false, validatedOk: false, outputName: null },
  hasSliced: false,
};
const facts = (over: Partial<Omit<JobFacts, "doctor" | "convert">> & { doctor?: Partial<JobFacts["doctor"]>; convert?: Partial<JobFacts["convert"]> }): JobFacts => ({
  ...base, ...over, doctor: { ...base.doctor, ...over.doctor }, convert: { ...base.convert, ...over.convert },
});
const states = (f: JobFacts) => Object.fromEntries(deriveSteps(f).map((s) => [s.id, s.state]));

describe("job progress is derived from established facts", () => {
  it("names five actions, in order", () => {
    expect(deriveSteps(base).map((s) => s.label)).toEqual(["Open project", "Check", "Prepare copy", "Slice in Orca", "Compare slice"]);
  });

  it("a project that is open and clean has Prepare as the one current step", () => {
    expect(states(base)).toEqual({ open: "done", check: "done", prepare: "current", slice: "todo", compare: "todo" });
  });

  it("a check with findings is done-but-needs-review, never a plain pass", () => {
    const check = deriveSteps(facts({ doctor: { verdict: "REPAIRABLE" } })).find((s) => s.id === "check")!;
    expect(check.state).toBe("review");
    expect(check.status).toBe("done, needs review");
  });

  it("a step is not done until it has happened", () => {
    expect(states(facts({ doctor: { status: "loading" } }))).toMatchObject({ check: "current", prepare: "todo" });
    expect(states(facts({ hasProject: false }))).toMatchObject({ open: "current", check: "todo" });
  });

  it("a failed check is failed, and a blocked project cannot be prepared", () => {
    expect(states(facts({ doctor: { status: "error" } })).check).toBe("error");
    expect(states(facts({ doctor: { prepareBlocked: true } })).prepare).toBe("blocked");
  });

  it("Slice in Orca is current only once a validated copy exists", () => {
    expect(states(base).slice).toBe("todo");
    const ready = facts({ convert: { status: "done", validatedOk: true, outputName: "p_U1.3mf" } });
    expect(states(ready)).toMatchObject({ prepare: "done", slice: "current" });
    expect(states(facts({ convert: { status: "done", validatedOk: false } })).slice).toBe("todo");
    expect(states(facts({ convert: { status: "done", validatedOk: true, blocked: true } })).prepare).toBe("error");
  });

  it("an open slice completes the Orca step and makes comparing current", () => {
    expect(states(facts({ hasSliced: true }))).toMatchObject({ slice: "done", compare: "current" });
  });
});

describe("the one next action", () => {
  it("offers no Orca handoff before a validated copy exists", () => {
    for (const f of [
      base,
      facts({ convert: { status: "loading" } }),
      facts({ convert: { status: "done", validatedOk: false } }),
      facts({ convert: { status: "done", validatedOk: true, blocked: true } }),
    ]) {
      expect(nextAction(f).action?.kind).not.toBe("scroll");
      expect(nextAction(f).headline).not.toMatch(/Orca/);
    }
  });

  it("names the actual copy once it exists", () => {
    const next = nextAction(facts({ convert: { status: "done", validatedOk: true, outputName: "benchy_U1.3mf" } }));
    expect(next.headline).toBe("Open benchy_U1.3mf in Snapmaker Orca");
    expect(next.action).toMatchObject({ kind: "scroll", target: "job-stage-prepared" });
  });

  it("checking and preparing do not wait for a printer", () => {
    expect(nextAction(facts({ doctor: { status: "loading" } })).detail).toMatch(/without a printer/);
    expect(nextAction(base).action).toMatchObject({ kind: "link", to: "/workspace" });
  });

  it("a failed check offers a retry; a blocked project explains instead of offering Prepare", () => {
    expect(nextAction(facts({ doctor: { status: "error" } })).action?.kind).toBe("retry");
    const blocked = nextAction(facts({ doctor: { prepareBlocked: true } }));
    expect(blocked.headline).toMatch(/not available/);
    expect(blocked.action?.label).not.toMatch(/^Prepare/);
  });

  it("a copy that was written but failed its own check is not \"nothing prepared\" and is not offered to Orca", () => {
    const f = facts({ convert: { status: "done", validatedOk: false, blocked: false, outputName: "x_U1.3mf" } });
    expect(states(f).prepare).toBe("review");
    expect(states(f).slice).toBe("todo");
    const next = nextAction(f);
    expect(next.headline).toBe("A copy was written, but its check found issues");
    expect(next.headline).not.toMatch(/Prepare a U1 copy|Orca/);
    expect(next.action).toMatchObject({ to: "/workspace" });
  });

  it("a failed request does not claim that nothing was written; a refusal does", () => {
    const failed = nextAction(facts({ convert: { status: "error" } }));
    expect(failed.headline).toBe("Studio could not confirm a prepared copy");
    expect(failed.detail).not.toMatch(/Nothing was written/);
    expect(nextAction(facts({ convert: { status: "done", blocked: true } })).detail).toMatch(/Nothing was written/);
  });

  it("an open slice points at comparing it", () => {
    expect(nextAction(facts({ hasSliced: true })).action).toMatchObject({ to: "/after-slicing" });
  });

  it("preparedReady matches the eligibility used elsewhere", () => {
    expect(preparedReady(facts({ convert: { status: "done", validatedOk: true } }))).toBe(true);
    expect(preparedReady(facts({ convert: { status: "done", validatedOk: true, blocked: true } }))).toBe(false);
    expect(preparedReady(facts({ convert: { status: "error", validatedOk: true } }))).toBe(false);
  });
});
