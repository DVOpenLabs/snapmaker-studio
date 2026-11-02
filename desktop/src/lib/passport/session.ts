import { create } from "zustand";
import { useJob } from "@/store/job";
import type { JobRecord } from "@/lib/jobRecord";
import type { BuildResponse, Verification } from "./types";

/**
 * What the Passport page keeps while the application stays open, so leaving the page and coming back does not
 * lose the fields or the report. Memory only: nothing here is written to localStorage or anywhere else, so it
 * does not survive a restart and the page says so.
 */
export interface PassportInputs { original: string; prepared: string; sliced: string; recipes: string; mappings: string }

export const EMPTY_INPUTS: PassportInputs = { original: "", prepared: "", sliced: "", recipes: "", mappings: "" };

interface BuiltFor {
  /** The open project's path when the passport was built (null: no project was open). */
  project: string | null;
  /** Every field exactly as it was when the passport was built (files, recipes, mappings). */
  files: PassportInputs;
}

interface PassportSession {
  inputs: PassportInputs;
  /** The project the entered fields belong to when they were filled from a job (null: typed by hand). */
  fieldsProject: string | null;
  built: BuildResponse | null;
  verification: Verification | null;
  builtFor: BuiltFor | null;
  /** Why the page was cleared (a different project was opened). Shown once. */
  notice: string | null;
  /** Counters so only the latest build, and the latest check of it, may land (also across leaving and re-entering the page). */
  buildSeq: number;
  verifySeq: number;
  beginBuild: () => number;
  beginVerify: () => number;
  /** `project` is the open project when the value was typed: fields are owned by the project they were entered under. */
  setInput: (key: keyof PassportInputs, value: string, project: string | null) => void;
  fillFromJob: (record: JobRecord) => void;
  setBuilt: (built: BuildResponse, verification: Verification | null, project: string | null, files: BuiltFor["files"]) => void;
  setVerification: (verification: Verification) => void;
  clearBuilt: () => void;
  /** A different project was opened: drop the previous project's fields and report. */
  projectChanged: (notice: string) => void;
  dismissNotice: () => void;
  resetForTests: () => void;
}

export const fileFields = (i: PassportInputs) => ({ original: i.original, prepared: i.prepared, sliced: i.sliced });

export const usePassportSession = create<PassportSession>((set, get) => ({
  inputs: EMPTY_INPUTS, fieldsProject: null, built: null, verification: null, builtFor: null, notice: null, buildSeq: 0, verifySeq: 0,
  beginBuild: () => { const n = get().buildSeq + 1; set({ buildSeq: n, verifySeq: get().verifySeq + 1 }); return n; },
  beginVerify: () => { const n = get().verifySeq + 1; set({ verifySeq: n }); return n; },
  setInput: (key, value, project) => set({ inputs: { ...get().inputs, [key]: value }, fieldsProject: project, notice: null }),
  fillFromJob: (record) => set({
    inputs: { ...get().inputs, original: record.original.path, prepared: record.prepared?.path ?? "", sliced: record.sliced?.path ?? "" },
    fieldsProject: record.original.path, notice: null,
  }),
  setBuilt: (built, verification, project, files) => set({ built, verification, builtFor: { project, files }, notice: null }),
  setVerification: (verification) => set({ verification }),
  clearBuilt: () => set({ built: null, verification: null, builtFor: null, buildSeq: get().buildSeq + 1, verifySeq: get().verifySeq + 1 }),
  projectChanged: (notice) => set({ inputs: EMPTY_INPUTS, fieldsProject: null, built: null, verification: null, builtFor: null, notice,
    buildSeq: get().buildSeq + 1, verifySeq: get().verifySeq + 1 }),
  dismissNotice: () => set({ notice: null }),
  resetForTests: () => set({ inputs: EMPTY_INPUTS, fieldsProject: null, built: null, verification: null, builtFor: null, notice: null }),
}));

/** True when the report on screen was built from different fields (files, recipes or mappings) than the ones now entered. */
export function reportIsStale(s: Pick<PassportSession, "built" | "builtFor" | "inputs">): boolean {
  if (!s.built || !s.builtFor) return false;
  const was = s.builtFor.files;
  return (Object.keys(was) as Array<keyof PassportInputs>).some((key) => s.inputs[key] !== was[key]);
}

/**
 * Does the page's content belong to a project other than the one open now? Content that never belonged to a
 * project (typed by hand with none open) is not cleared by one being opened later; content that did is.
 */
export function belongsToOtherProject(s: Pick<PassportSession, "builtFor" | "fieldsProject">, current: string | null): boolean {
  const owners = [s.builtFor?.project ?? null, s.fieldsProject].filter((p): p is string => p !== null);
  return owners.some((owner) => owner !== current);
}

/**
 * The project the page's content belongs to is checked here, not in the view, so a project change that happens while
 * the page is not mounted (A -> B -> A included) still clears it and cancels anything in flight.
 */
let lastProject: string | null = useJob.getState().record?.original.path ?? null;
useJob.subscribe((state) => {
  const current = state.record?.original.path ?? null;
  if (current === lastProject) return;
  lastProject = current;
  const s = usePassportSession.getState();
  const hasContent = s.built !== null || s.fieldsProject !== null;
  if (belongsToOtherProject(s, current)) s.projectChanged("A different project is open now, so the earlier project's passport and file fields were cleared.");
  else if (hasContent) usePassportSession.setState({ buildSeq: s.buildSeq + 1, verifySeq: s.verifySeq + 1 });
});

