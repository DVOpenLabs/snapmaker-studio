/**
 * Where a job is, read from facts the app already holds — never a second state machine.
 *
 * Five actions, in the order a job meets them. A step is "done" only when the thing
 * it names has happened; a check that found problems is "done, needs review", never
 * a pass. The inputs are copies of existing store values, so nothing here can drift
 * from the stores.
 */

export type StepId = "open" | "check" | "prepare" | "slice" | "compare";
export type StepState = "done" | "review" | "current" | "todo" | "blocked" | "error";

export interface JobFacts {
  /** A project is open in the session. */
  hasProject: boolean;
  doctor: { status: "idle" | "loading" | "done" | "error"; prepareBlocked: boolean; verdict: string | null };
  /** A prepared copy Studio wrote and validated in this session. */
  convert: { status: "idle" | "loading" | "done" | "error"; blocked: boolean; validatedOk: boolean; outputName: string | null };
  /** A sliced G-code is open. */
  hasSliced: boolean;
}

export interface JobStep {
  id: StepId;
  label: string;
  state: StepState;
  /** Screen-reader wording; the visible mark is never colour alone. */
  status: string;
}

export interface NextAction {
  /** Short statement of what comes next. */
  headline: string;
  detail: string;
  /** What the single button does, when there is one. */
  action: { kind: "link" | "scroll" | "retry"; label: string; to?: string; target?: string } | null;
}

const LABEL: Record<StepId, string> = {
  open: "Open project",
  check: "Check",
  prepare: "Prepare copy",
  slice: "Slice in Orca",
  compare: "Compare slice",
};

const STATUS: Record<StepState, string> = {
  done: "done",
  review: "done, needs review",
  current: "current step",
  todo: "not started",
  blocked: "unavailable",
  error: "failed",
};

const problem = (verdict: string | null) => verdict !== null && verdict.toUpperCase() !== "READY";

/** True when a prepared copy exists that Studio wrote and validated in this session. */
export const preparedReady = (f: JobFacts) =>
  f.convert.status === "done" && !f.convert.blocked && f.convert.validatedOk;

/** A copy was written but its own validation did not pass: neither "prepared" nor "nothing happened". */
export const unvalidated = (f: JobFacts) => f.convert.status === "done" && !f.convert.blocked && !f.convert.validatedOk;

export function deriveSteps(f: JobFacts): JobStep[] {
  const open: StepState = f.hasProject ? "done" : "current";

  let check: StepState = "todo";
  if (f.hasProject) {
    if (f.doctor.status === "loading" || f.doctor.status === "idle") check = "current";
    else if (f.doctor.status === "error") check = "error";
    else check = problem(f.doctor.verdict) || f.doctor.prepareBlocked ? "review" : "done";
  }

  let prepare: StepState = "todo";
  if (f.hasProject && f.doctor.prepareBlocked) prepare = "blocked";
  else if (preparedReady(f)) prepare = "done";
  else if (f.convert.status === "loading") prepare = "current";
  else if (f.convert.status === "error" || f.convert.blocked) prepare = "error";
  else if (unvalidated(f)) prepare = "review";
  else if (f.hasProject && (check === "done" || check === "review")) prepare = "current";

  let slice: StepState = "todo";
  if (f.hasSliced) slice = "done";
  else if (preparedReady(f)) slice = "current";

  let compare: StepState = "todo";
  if (f.hasSliced && f.hasProject) compare = "current";

  return ([
    ["open", open], ["check", check], ["prepare", prepare], ["slice", slice], ["compare", compare],
  ] as Array<[StepId, StepState]>).map(([id, state]) => ({ id, label: LABEL[id], state, status: STATUS[state] }));
}

/** The one next action. It names its target and never offers a hand-off before the copy exists. */
export function nextAction(f: JobFacts): NextAction {
  if (!f.hasProject) {
    return { headline: "Open a project", detail: "Studio reads it on this computer.", action: null };
  }
  if (f.doctor.status === "idle" || f.doctor.status === "loading") {
    return { headline: "Checking the project…", detail: "This works without a printer connected.", action: null };
  }
  if (f.doctor.status === "error") {
    return {
      headline: "The check could not finish",
      detail: "Studio could not read this project. Try again, or open it again from Home.",
      action: { kind: "retry", label: "Check again" },
    };
  }
  if (f.doctor.prepareBlocked) {
    return {
      headline: "A prepared copy is not available for this project",
      detail: "Studio would refuse to prepare it. Open the full checks to see why.",
      action: { kind: "link", label: "Open the full checks", to: "/compatibility" },
    };
  }
  if (f.hasSliced) {
    return {
      headline: "Compare the slice with the project",
      detail: "Look at the settings the slicer recorded and what changed.",
      action: { kind: "link", label: "Compare slice", to: "/after-slicing" },
    };
  }
  if (preparedReady(f)) {
    const name = f.convert.outputName;
    return {
      headline: name ? `Open ${name} in Snapmaker Orca` : "Open the prepared copy in Snapmaker Orca",
      detail: "Studio does not slice. Slice in Orca, then bring the G-code back here.",
      action: { kind: "scroll", label: "Go to the Orca step", target: "job-stage-prepared" },
    };
  }
  if (f.convert.status === "loading") {
    return { headline: "Preparing a copy…", detail: "Your original is never changed.", action: null };
  }
  if (f.convert.blocked) {
    return {
      headline: "Studio refused to prepare this project",
      detail: "Nothing was written. Open the full checks to see why.",
      action: { kind: "link", label: "Open the full checks", to: "/compatibility" },
    };
  }
  if (f.convert.status === "error") {
    return {
      headline: "Studio could not confirm a prepared copy",
      detail: "Nothing is offered to Orca. Open the workspace to see what happened and try again.",
      action: { kind: "link", label: "Open the workspace", to: "/workspace" },
    };
  }
  if (unvalidated(f)) {
    return {
      headline: "A copy was written, but its check found issues",
      detail: "Studio did not confirm it, so it is not offered to Orca. Open the workspace to see what remains.",
      action: { kind: "link", label: "Open the workspace", to: "/workspace" },
    };
  }
  return {
    headline: "Prepare a U1 copy",
    detail: "Preparing writes a new copy and never touches your original.",
    // The Prepare button that feeds this job lives in the workspace; Compatibility keeps its own, unlinked result.
    action: { kind: "link", label: "Prepare a copy", to: "/workspace" },
  };
}
