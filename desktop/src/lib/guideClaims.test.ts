import { describe, it, expect } from "vitest";
import { needsConfirm, confirmCopy, type ControlAction } from "./printerControl";
import { FIDELITY_HEADINGS, fidelityHeadline, statusLabel } from "./fidelity";
import type { FidelityReport } from "@/api";
// Vite hands the guide's own JSON back as text; the guide sources live outside this app, so no copy is kept here.
import tasksRaw from "../../../site/guide/content/tasks.json?raw";
import problemsRaw from "../../../site/guide/content/problems.json?raw";

// Guard: statements in the user guide (site/guide) that depend on what this app does are checked
// against the app. The expected facts come from the code imported above, not from the guide.
//
// What this establishes: the guide's grouping of printer actions, its quoted prompts, its names for
// the fidelity groups and its advice for unexplained changes agree with the current app code.
// What it cannot establish: that the surrounding prose is well explained, or anything about a
// physical printer or Snapmaker Orca.

const GUIDE: Record<string, string> = { tasks: tasksRaw, problems: problemsRaw };
function guide(name: string): any {
  return JSON.parse(GUIDE[name]);
}
function strings(v: unknown): string[] {
  if (typeof v === "string") return [v];
  if (Array.isArray(v)) return v.flatMap(strings);
  if (v && typeof v === "object") return Object.values(v).flatMap(strings);
  return [];
}
const task = (id: string) => guide("tasks").tasks.find((t: any) => t.id === id);
const problem = (id: string) => guide("problems").find((p: any) => p.id === id);
const text = (v: unknown) => strings(v).join(" ");

describe("guide: printer controls match the app", () => {
  it("the grouping the guide relies on is still the app's policy", () => {
    const confirming: ControlAction[] = ["start", "cancel", "emergency_stop"];
    const direct: ControlAction[] = ["pause", "resume"];
    for (const a of confirming) expect(needsConfirm(a)).toBe(true);
    for (const a of direct) expect(needsConfirm(a)).toBe(false);
  });

  it("the guide says pause and resume are sent without a second prompt, and does not promise the result", () => {
    const t = task("printer-controls");
    expect(t).toBeTruthy();
    const steps = strings(t.steps);
    const pauseStep = steps.find((s) => /Pause/.test(s) && /Resume/.test(s))!;
    expect(pauseStep).toMatch(/no second prompt/i);
    expect(pauseStep).not.toMatch(/take effect|immediately|instantly/i);
    expect(text(t.success)).not.toMatch(/happens only/i);
  });

  it("each action that asks first is described as asking first, using the app's own prompt text", () => {
    const t = task("printer-controls");
    const steps = text(t.steps);
    expect(steps).toContain(confirmCopy("cancel").title); // "Cancel this print?"
    for (const label of ["Cancel print", "Start this print", "Emergency stop"]) {
      const step = strings(t.steps).find((s) => s.includes(label));
      expect(step, label).toBeTruthy();
      expect(step!).toMatch(/asks/i);
    }
    expect(confirmCopy("emergency_stop").body).toMatch(/firmware restart/i);
    expect(steps).toMatch(/firmware restart/i);
  });
});

describe("guide: fidelity groups match the app", () => {
  it("the guide names the groups exactly as the app does", () => {
    expect(problem("unverified").label).toBe(FIDELITY_HEADINGS.unverified);
    expect(problem("could-not-carry-over").label).toBe(FIDELITY_HEADINGS.notCarried);
  });

  it("unsupported data is described as 'not checked', not as lost", () => {
    const page = text(problem("could-not-carry-over"));
    expect(page).toContain(statusLabel("unsupported")); // "Not checked — Studio can’t read it"
    expect(page).not.toMatch(/carries over only what it can verify/i);
  });

  it("an unexplained change gets the app's own advice: compare with the original in Orca and report", () => {
    const report = {
      available: true,
      summary: "",
      claims: { may_claim_nothing_lost: false },
      unverified: [{}],
    } as unknown as FidelityReport;
    const appAdvice = fidelityHeadline(report);
    // premise: these are the instructions the app itself gives
    expect(appAdvice).toMatch(/Snapmaker Orca/);
    expect(appAdvice).toMatch(/compare it with your original/i);
    expect(appAdvice).toMatch(/report/i);

    const page = text(problem("unverified"));
    expect(page).toMatch(/compare/i);
    expect(page).toMatch(/original/i);
    expect(page).toMatch(/Orca/);
    expect(page).toMatch(/report/i);
    expect(page).not.toMatch(/not an error|nothing is wrong/i);
  });
});
