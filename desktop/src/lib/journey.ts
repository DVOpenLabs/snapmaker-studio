/**
 * The one journey a selected job follows, read from facts the app already holds.
 *
 * Five stages in the order a person meets them. Nothing here keeps state: every input is
 * a copy of a store value or a screen fact, so the journey cannot drift from what is true.
 * A stage is "done" only when the thing it names has happened, and the primary action never
 * offers a hand-off before the copy it hands off exists.
 */

export type StageId = "open" | "materials" | "copy" | "orca" | "compare";
export type StageState = "done" | "current" | "todo" | "blocked" | "review" | "error";

export interface JourneyFacts {
  hasProject: boolean;
  /** The project check (Doctor) in the shared session. */
  check: { status: "idle" | "loading" | "done" | "error"; prepareBlocked: boolean };
  /** Spool or preset choices are held and waiting for their review. */
  materialsHolding: boolean;
  /** A preparation is running. */
  preparing: boolean;
  /** The last Prepare was refused, failed, or wrote nothing. */
  prepareFailed: boolean;
  /** A copy Studio wrote and validated for this project in this session. */
  prepared: boolean;
  /** A copy was written but its own validation did not pass. */
  unvalidated: boolean;
  /** A sliced G-code is open. */
  hasSliced: boolean;
}

export interface Stage {
  id: StageId;
  label: string;
  state: StageState;
  /** Screen-reader wording; the visible mark is never colour alone. */
  status: string;
}

export type PrimaryKind = "none" | "create" | "review-materials" | "open-orca" | "compare" | "retry-check";

export interface Primary {
  kind: PrimaryKind;
  label: string;
  /** Why the action is unavailable, when it is shown disabled. */
  disabledReason?: string;
}

export interface Journey {
  stages: Stage[];
  current: StageId;
  primary: Primary;
}

export const STAGE_LABEL: Record<StageId, string> = {
  open: "Open project",
  materials: "Choose materials",
  copy: "Create U1 copy",
  orca: "Open in Orca",
  compare: "Compare slice",
};

const STATUS: Record<StageState, string> = {
  done: "done",
  current: "current step",
  todo: "not started",
  blocked: "unavailable",
  review: "done, needs review",
  error: "failed",
};

export function deriveJourney(f: JourneyFacts): Journey {
  const open: StageState = f.hasProject ? "done" : "current";
  const closed = f.hasProject && f.check.prepareBlocked;
  const checking = f.hasProject && (f.check.status === "idle" || f.check.status === "loading");

  // Materials are optional: Prepare works without them, so this stage is "done" once the copy exists
  // (made with or without choices) and "current" only while the person holds choices. Otherwise the copy is the one current step.
  let materials: StageState = "todo";
  if (closed) materials = "blocked";
  else if (f.hasProject && (f.prepared || f.unvalidated || f.hasSliced)) materials = "done";
  else if (f.hasProject && f.materialsHolding) materials = "current";

  let copy: StageState = "todo";
  if (closed) copy = "blocked";
  else if (f.preparing) copy = "current";
  else if (f.prepared) copy = "done";
  else if (f.prepareFailed) copy = "error";
  else if (f.unvalidated) copy = "review";
  else if (f.hasProject && !checking && f.check.status !== "error") copy = f.materialsHolding ? "todo" : "current";

  let orca: StageState = "todo";
  if (f.hasSliced) orca = "done";
  else if (f.prepared) orca = "current";

  const compare: StageState = f.hasSliced && f.hasProject ? "current" : "todo";

  const stages: Stage[] = ([
    ["open", open], ["materials", materials], ["copy", copy], ["orca", orca], ["compare", compare],
  ] as Array<[StageId, StageState]>).map(([id, state]) => ({ id, label: STAGE_LABEL[id], state, status: id === "materials" && state === "todo" ? "optional, not started" : STATUS[state] }));

  const current: StageId = f.hasSliced && f.hasProject ? "compare"
    : f.prepared ? "orca"
    : !f.hasProject ? "open"
    : f.materialsHolding && !f.preparing ? "materials"
    : "copy";

  return { stages, current, primary: primaryFor(f, closed, checking) };
}

function primaryFor(f: JourneyFacts, closed: boolean, checking: boolean): Primary {
  if (!f.hasProject) return { kind: "none", label: STAGE_LABEL.open };
  if (f.check.status === "error") return { kind: "retry-check", label: "Check again" };
  if (f.hasSliced) return { kind: "compare", label: STAGE_LABEL.compare };
  if (f.prepared && !closed) return { kind: "open-orca", label: STAGE_LABEL.orca };
  if (closed) return { kind: "none", label: STAGE_LABEL.copy, disabledReason: "Studio cannot prepare a U1 copy of this project." };
  if (f.preparing) return { kind: "create", label: STAGE_LABEL.copy, disabledReason: "Creating the copy…" };
  if (f.materialsHolding) return { kind: "review-materials", label: "Review materials" };
  if (checking) return { kind: "create", label: STAGE_LABEL.copy, disabledReason: "Checking the project…" };
  return { kind: "create", label: STAGE_LABEL.copy };
}
