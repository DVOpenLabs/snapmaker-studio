import type { JobRecord, JobRole } from "@/lib/jobRecord";

/** One file a workspace checkpoint will track, taken from the job Studio already holds. */
export type TrackedFile = { role: JobRole; name: string; path: string };
export type UnavailableFile = { role: JobRole; reason: string };
export type WorkspacePlan = {
  project: string | null;
  tracked: TrackedFile[];
  unavailable: UnavailableFile[];
  /** False when there is no project to checkpoint; `why` then says so. */
  canSave: boolean;
  why: string | null;
};

const ROLE_LABEL: Record<JobRole, string> = { original: "Original project", prepared: "Prepared copy", sliced: "Sliced output" };
export const roleLabel = (role: JobRole): string => ROLE_LABEL[role];

/**
 * What a real-workspace checkpoint would track. Only files the job record links are listed: a file that is not
 * linked is reported as unavailable with the reason, never invented and never replaced by an empty or sample entry.
 */
export function planWorkspaceCheckpoint(record: JobRecord | null): WorkspacePlan {
  if (!record) {
    return { project: null, tracked: [], unavailable: [], canSave: false,
      why: "No project is open. Prepare one from Creative import (or open a project) and its files appear here." };
  }
  const tracked: TrackedFile[] = [{ role: "original", name: record.original.name, path: record.original.path }];
  const unavailable: UnavailableFile[] = [];
  if (record.prepared) tracked.push({ role: "prepared", name: record.prepared.name, path: record.prepared.path });
  else unavailable.push({ role: "prepared", reason: "No prepared copy is linked to this project yet. Prepare one first (for example in Creative import)." });
  if (record.sliced) tracked.push({ role: "sliced", name: record.sliced.name, path: record.sliced.path });
  else unavailable.push({ role: "sliced", reason: "No sliced file is linked. Studio does not make one; it is linked when you open the G-code your slicer wrote for this project." });
  return { project: record.original.name, tracked, unavailable, canSave: true, why: null };
}

/** The request body for the existing /recovery/checkpoint contract. Paths go to the local service only. */
export function workspaceCheckpointBody(plan: WorkspacePlan, record: JobRecord, expectedRevision: number, jobs: unknown[]) {
  const stage = record.sliced ? "sliced" : record.prepared ? "prepared" : "opened";
  return {
    workspace: { name: record.original.name, stage },
    observations: [],
    files: plan.tracked.map((f) => ({ name: f.name, path: f.path })),
    jobs,
    expected_revision: expectedRevision,
  };
}
