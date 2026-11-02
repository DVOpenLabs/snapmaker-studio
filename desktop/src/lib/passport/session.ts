import { create } from "zustand";
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
  /** The file fields exactly as they were when it was built. */
  files: Pick<PassportInputs, "original" | "prepared" | "sliced">;
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
  setInput: (key: keyof PassportInputs, value: string) => void;
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
  inputs: EMPTY_INPUTS, fieldsProject: null, built: null, verification: null, builtFor: null, notice: null,
  setInput: (key, value) => set({ inputs: { ...get().inputs, [key]: value }, notice: null }),
  fillFromJob: (record) => set({
    inputs: { ...get().inputs, original: record.original.path, prepared: record.prepared?.path ?? "", sliced: record.sliced?.path ?? "" },
    fieldsProject: record.original.path, notice: null,
  }),
  setBuilt: (built, verification, project, files) => set({ built, verification, builtFor: { project, files }, notice: null }),
  setVerification: (verification) => set({ verification }),
  clearBuilt: () => set({ built: null, verification: null, builtFor: null }),
  projectChanged: (notice) => set({ inputs: EMPTY_INPUTS, fieldsProject: null, built: null, verification: null, builtFor: null, notice }),
  dismissNotice: () => set({ notice: null }),
  resetForTests: () => set({ inputs: EMPTY_INPUTS, fieldsProject: null, built: null, verification: null, builtFor: null, notice: null }),
}));

/** True when the report on screen was built from different file fields than the ones now entered. */
export function reportIsStale(s: Pick<PassportSession, "built" | "builtFor" | "inputs">): boolean {
  if (!s.built || !s.builtFor) return false;
  const now = fileFields(s.inputs);
  return now.original !== s.builtFor.files.original || now.prepared !== s.builtFor.files.prepared || now.sliced !== s.builtFor.files.sliced;
}

/**
 * Does the page's content belong to a project other than the one open now? Content that never belonged to a
 * project (typed by hand with none open) is not cleared by one being opened later; content that did is.
 */
export function belongsToOtherProject(s: Pick<PassportSession, "builtFor" | "fieldsProject">, current: string | null): boolean {
  const owners = [s.builtFor?.project ?? null, s.fieldsProject].filter((p): p is string => p !== null);
  return owners.some((owner) => owner !== current);
}
