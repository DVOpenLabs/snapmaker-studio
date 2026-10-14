import { describe, it, expect } from "vitest";
// @ts-expect-error The desktop type setup intentionally omits Node declarations; Vitest supplies these APIs.
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
// @ts-expect-error The desktop type setup intentionally omits Node declarations; Vitest supplies these APIs.
import { join, dirname } from "node:path";
// @ts-expect-error The desktop type setup intentionally omits Node declarations; Vitest supplies these APIs.
import { tmpdir } from "node:os";
// @ts-expect-error The desktop type setup intentionally omits Node declarations; Vitest supplies these APIs.
import { spawnSync } from "node:child_process";
// @ts-expect-error The desktop type setup intentionally omits Node declarations; Vitest supplies these APIs.
import { fileURLToPath } from "node:url";
declare const process: any;
import { needsConfirm, confirmCopy, type ControlAction } from "./printerControl";
import { FIDELITY_HEADINGS, fidelityHeadline, statusLabel, targetNote } from "./fidelity";
import type { FidelityReport } from "@/api";
// Vite hands the guide's own JSON back as text; the guide sources live outside this app, so no copy is kept here.
import tasksRaw from "../../../site/guide/content/tasks.json?raw";
import problemsRaw from "../../../site/guide/content/problems.json?raw";
import pathRaw from "../../../site/guide/content/path.json?raw";
import answersRaw from "../../../site/guide/content/answers.json?raw";
import guideRaw from "../../../site/guide/content/guide.json?raw";
import designInsightsRaw from "../routes/DesignInsights.tsx?raw";
import riskSignalsRaw from "../components/PrintRiskSignals.tsx?raw";
import placementCardRaw from "../components/PlacementCard.tsx?raw";
import orcaHandoffRaw from "../components/OrcaHandoff.tsx?raw";
import afterSlicingRaw from "../routes/AfterSlicing.tsx?raw";
import printersRaw from "../routes/Printers.tsx?raw";
import liveWorkspaceRaw from "../routes/LiveWorkspace.tsx?raw";
import postSliceRaw from "./postSlice.ts?raw";
import preflightRaw from "./preflight.ts?raw";
import fidelityRaw from "./fidelity.ts?raw";

// Guard: statements in the user guide (site/guide) that depend on what this app does are checked
// against the app. The expected facts come from the code imported above, not from the guide.
//
// What this establishes: the guide's grouping of printer actions, its quoted prompts, its names for
// the fidelity groups and its advice for unexplained changes agree with the current app code.
// What it cannot establish: that the surrounding prose is well explained, or anything about a
// physical printer or Snapmaker Orca.

const GUIDE: Record<string, string> = { tasks: tasksRaw, problems: problemsRaw, path: pathRaw };
function guide(name: string): any {
  return JSON.parse(GUIDE[name]);
}
function strings(v: unknown): string[] {
  if (typeof v === "string") return [v];
  if (Array.isArray(v)) return v.flatMap(strings);
  if (v && typeof v === "object") return Object.values(v).flatMap(strings);
  return [];
}
export function checkNextActionLabels(answers: Array<{ nextAction: { label: string } }>, appSource: string): void {
  const labels = new Set<string>();
  for (const match of appSource.matchAll(/"([^"\n]+)"/g)) labels.add(match[1]);
  for (const match of appSource.matchAll(/>\s*([^<>{}\n]+?)\s*</g)) labels.add(match[1].trim());
  for (const answer of answers) expect(labels.has(answer.nextAction.label), answer.nextAction.label).toBe(true);
}
const task = (id: string) => guide("tasks").tasks.find((t: any) => t.id === id);
const problem = (id: string) => guide("problems").find((p: any) => p.id === id);
const text = (v: unknown) => strings(v).join(" ");
type GuideFact = { id: string; derive: string; tokens: string[] };
const APP_FACTS: Record<string, GuideFact> = {
  "kept-orca": { id: "kept-reachability", derive: "app:desktop/src/lib/fidelity.ts#FIDELITY_HEADINGS", tokens: ["reached the copy", "read any note on the row"] },
};
// Real resolution: load the module under vitest and check it exports the name. Comments, strings and near-miss names do not count.
const appModules = import.meta.glob(["/src/**/*.{ts,tsx}", "!/src/**/*.test.*"]) as Record<string, () => Promise<Record<string, unknown>>>;
export async function appExports(file: string, symbol: string): Promise<boolean> {
  const load = appModules["/" + file.replace(/^desktop\//, "")];
  if (!load) return false;
  return Object.prototype.hasOwnProperty.call(await load(), symbol);
}
export async function checkAppAnswerFacts(answers: Array<{ id: string; requiredFacts: GuideFact[] }>, sourceRoot: string, pageText: string): Promise<void> {
  const appAnswers = answers.filter((a) => a.requiredFacts.some((f) => f.derive.startsWith("app:")));
  expect(new Set(Object.keys(APP_FACTS))).toEqual(new Set(appAnswers.map((a) => a.id)));
  for (const answer of appAnswers) {
    expect(answer.requiredFacts).toHaveLength(1);
    const fact = answer.requiredFacts[0];
    expect(fact).toEqual(APP_FACTS[answer.id]);
    const [, value] = fact.derive.split(":");
    const [file, fragment] = value.split("#");
    expect(readFileSync(join(sourceRoot, file), "utf8").length).toBeGreaterThan(0);
    expect(await appExports(file, fragment)).toBe(true);
    for (const token of fact.tokens) expect(pageText).toContain(token);
  }
}

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

describe("guide: golden answers have app-code assertions", () => {
  it("covers the app-derived answers", () => {
    /** This proves code-to-manifest coverage only; it cannot establish prose clarity, source fitness, honest dates, physical behavior, paraphrased overclaims, or screen-reader behavior. */
    const answers = JSON.parse(answersRaw).answers as Array<{ id: string; requiredFacts: Array<{ derive: string }> }>;
    const expected = new Set(["setting-why", "size-or-placement", "kept-orca", "unknown-compatible", "sliced-for-u1", "original-unchanged", "print-success"]);
    expect(new Set(answers.map((a) => a.id))).toEqual(expected);
    const facts = new Set(answers.flatMap((a) => a.requiredFacts.map((f) => `${a.id}:${f.derive}`)));
    expect(facts.size).toBe(7);
    expect(facts.has("kept-orca:app:desktop/src/lib/fidelity.ts#FIDELITY_HEADINGS")).toBe(true);
    expect(facts.has("print-success:backend:success_predict.findings")).toBe(true);
    const app = [designInsightsRaw, riskSignalsRaw, placementCardRaw, orcaHandoffRaw, afterSlicingRaw, printersRaw, liveWorkspaceRaw].join("\n");
    for (const label of ["Print risk signals", "Move onto the plate", "Open in Snapmaker Orca", "Check this job", "Printer Hub"]) expect(app).toContain(label);
    expect(fidelityRaw).toContain("FIDELITY_HEADINGS");
    expect(postSliceRaw).toContain("export function unknownCount");
    expect(preflightRaw).toContain("resultLabel");
    expect(text(problem("looks-right"))).not.toContain("Print risk signals");
    expect(text(guide("path"))).toContain("gives no percentage");
    expect(riskSignalsRaw).toMatch(/findings\.signals[\s\S]*What to do:[\s\S]*Studio did not check:/);
    expect(riskSignalsRaw).toContain("Print risk signals");
    expect([designInsightsRaw, riskSignalsRaw].join(" ")).not.toMatch(/Print readiness|likelihood|\.band\b|Likely to print/);
  });

  it("resolves every app derive and checks the app-owned assertion table", async () => {
    /** Resolution and table coverage cannot establish prose clarity, source fitness, honest dates, physical behavior, paraphrased overclaims, or screen-reader behavior. */
    const answers = JSON.parse(answersRaw).answers as Array<{ id: string; requiredFacts: GuideFact[] }>;
    const appAnswers = answers.filter((a) => a.requiredFacts.some((f) => f.derive.startsWith("app:")));
    await checkAppAnswerFacts(answers, join(dirname(fileURLToPath(import.meta.url)), "../../.."), text(guide("path")));
    const appFacts = new Set<string>();
    for (const answer of appAnswers) {
      const fact = answer.requiredFacts[0];
      const expected = APP_FACTS[answer.id];
      expect({ id: fact.id, derive: fact.derive, tokens: fact.tokens }).toEqual(expected);
      const [, value] = fact.derive.split(":");
      const [file, fragment] = value.split("#");
      expect(fragment).toBeTruthy();
      expect(await appExports(file, fragment)).toBe(true);
      expect(FIDELITY_HEADINGS.kept).toBe("What stayed the same");
      expect(text(guide("path"))).toEqual(expect.stringContaining(fact.tokens[0]));
      expect(text(guide("path"))).toEqual(expect.stringContaining(fact.tokens[1]));
      appFacts.add(fact.id);
    }
    expect(appFacts).toEqual(new Set(Object.values(APP_FACTS).map((f) => f.id)));
    expect(new Set(answers.map((a) => a.id))).toEqual(new Set(["setting-why", "size-or-placement", "kept-orca", "unknown-compatible", "sliced-for-u1", "original-unchanged", "print-success"]));
  });

  it("rejects a fresh manifest whose app derive was changed", async () => {
    /** This mutation checks binding only; it cannot establish prose clarity, source fitness, dates, physical behavior, paraphrased overclaims, or screen-reader behavior. */
    const answers = JSON.parse(answersRaw).answers as Array<{ id: string; requiredFacts: GuideFact[] }>;
    const mutated = JSON.parse(JSON.stringify(answers)) as Array<{ id: string; requiredFacts: GuideFact[] }>;
    mutated.find((a) => a.id === "kept-orca")!.requiredFacts[0].derive = "app:desktop/src/lib/fidelity.ts#status";
    await expect(checkAppAnswerFacts(mutated, join(dirname(fileURLToPath(import.meta.url)), "../../.."), text(guide("path")))).rejects.toThrow();
    mutated.find((a) => a.id === "kept-orca")!.requiredFacts[0].derive = "app:desktop/src/lib/fidelity.ts#FIDELITY_HEADING";
    await expect(checkAppAnswerFacts(mutated, join(dirname(fileURLToPath(import.meta.url)), "../../.."), text(guide("path")))).rejects.toThrow();
  });

  it("resolves app symbols by really importing the module", async () => {
    /** Resolution checks that a name is exported; it cannot establish that the export is the right evidence for a guide claim. */
    expect(await appExports("desktop/src/lib/fidelity.ts", "FIDELITY_HEADINGS")).toBe(true);
    expect(await appExports("desktop/src/lib/fidelity.ts", "FIDELITY_HEADING")).toBe(false);
    expect(await appExports("desktop/src/lib/fidelity.ts", "toString")).toBe(false);
    expect(await appExports("desktop/src/lib/no_such_file.ts", "FIDELITY_HEADINGS")).toBe(false);
  });

  it("checks exact next-action labels and built anchors", () => {
    /** Literal-label and anchor checks cannot establish prose clarity, source fitness, honest dates, physical behavior, paraphrased overclaims, or screen-reader behavior. */
    const answers = JSON.parse(answersRaw).answers as Array<{ id: string; nextAction: { label: string; ref: string } }>;
    const app = [designInsightsRaw, riskSignalsRaw, placementCardRaw, orcaHandoffRaw, afterSlicingRaw, printersRaw, liveWorkspaceRaw].join("\n");
    checkNextActionLabels(answers, app);
    expect(answers.find((a) => a.id === "print-success")!.nextAction.label).toBe("Print risk signals");
    const html = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../../..", "site/guide/public/index.html"), "utf8");
    for (const answer of answers) if (answer.nextAction.ref.startsWith("#")) expect(html).toContain(`id="${answer.nextAction.ref.slice(1)}"`);
  });

  it("rejects a shortened next-action label from a fresh valid manifest", () => {
    /** This mutation check cannot establish prose clarity, source fitness, honest dates, physical behavior, paraphrased overclaims, or screen-reader behavior. */
    const answers = JSON.parse(answersRaw).answers as Array<{ nextAction: { label: string } }>;
    const mutated = answers.map((answer) => ({ ...answer, nextAction: { ...answer.nextAction } }));
    mutated.find((answer) => answer.nextAction.label === "Check this job")!.nextAction.label = "Check";
    expect(() => checkNextActionLabels(mutated, [designInsightsRaw, riskSignalsRaw, placementCardRaw, orcaHandoffRaw, afterSlicingRaw, printersRaw, liveWorkspaceRaw].join("\n"))).toThrow();
  });

  it("checks both guide and desktop version branches without changing the built guide", () => {
    const guideRoot = join(dirname(fileURLToPath(import.meta.url)), "../../..", "site/guide");
    const html = readFileSync(join(guideRoot, "public/index.html"), "utf8");
    const guideVersion = JSON.parse(guideRaw).site.version as string;
    expect(html).toContain(`v${guideVersion}`);
    const temp = mkdtempSync(join(tmpdir(), "guide-version-"));
    try {
      const config = join(temp, "tauri.conf.json");
      const run = (version: string) => {
        writeFileSync(config, JSON.stringify({ version }));
        return spawnSync("node", [join(guideRoot, "tools/check.mjs")], { cwd: guideRoot, env: { ...process.env, SNAPSTUDIO_TAURI_CONF: config }, encoding: "utf8" });
      };
      const match = run(guideVersion);
      expect(match.status).toBe(0);
      expect(match.stdout + match.stderr).not.toContain("WARNING  guide and desktop versions differ");
      const mismatch = run("9.9.9");
      expect(mismatch.status).toBe(0);
      expect(mismatch.stdout + mismatch.stderr).toContain("WARNING  guide and desktop versions differ");
    } finally { rmSync(temp, { recursive: true, force: true }); }
  });
});
