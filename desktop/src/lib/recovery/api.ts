import { callExt } from "@/lib/extApi";

export type FileState = "same" | "changed" | "missing" | "unreadable" | "unverified";
export type RecoveryFile = { name: string; state: FileState | string; association: "unverified" };
export type LegacyJob = { files?: Array<{ role: string; name: string; association?: string }> } | null;
export type RestoreResult = {
  missing_checkpoint: boolean; revision: number; checkpointed_at?: string;
  workspace: { name?: string } & Record<string, unknown>; files: RecoveryFile[];
  jobs: Array<{ job_id: string; state: string; replayed: boolean }>;
  observations: Array<{ historical: boolean; usable_for_loadout: boolean }>;
  fresh_read_required: boolean; legacy_job?: LegacyJob;
};
export type MonitoringRead = {
  status: string; print_state?: string; filename?: string | null; association?: string; note?: string;
  camera?: { state: string };
  reconciliation?: { state: string; events: Array<{ kind: string; from: string; to: string }>; source: string };
};
export type HistoryRead = {
  status: string; association?: string; note?: string;
  last_job: { filename: string | null; outcome: string } | null;
};

/** Accept only an integer port in the range the backend monitoring route allows. */
export function isValidPort(value: string): boolean {
  if (!/^\d+$/.test(value)) return false;
  const port = Number(value);
  return Number.isInteger(port) && port >= 1 && port <= 65535;
}

export const saveCheckpoint = (body: unknown) => callExt<{ revision: number; checkpointed_at: string; file_count: number }>(
  "/recovery/checkpoint", body, "Could not save the checkpoint");
export const restoreCheckpoint = () => callExt<RestoreResult>("/recovery/restore", {}, "Could not read the checkpoint");
export const readMonitoring = (host: string, port: string, previousState?: string) => callExt<MonitoringRead>(
  "/monitoring/read", { host, port: Number(port || 7125), ...(previousState ? { previous_state: previousState } : {}) },
  "Could not read the printer status");
export const readHistory = (host: string, port: string) => callExt<HistoryRead>(
  "/monitoring/history", { host, port: Number(port || 7125) }, "Could not read the last job");

/** One-way bridge from the legacy job store. The backend keeps an imported snapshot; nothing is written back. */
export function legacyJobSnapshot(): unknown[] {
  try {
    const raw = window.localStorage.getItem("snapstudio.job.v1");
    if (!raw) return [];
    const job = JSON.parse(raw);
    return job && typeof job === "object" ? [{ legacy_record: job }] : [];
  } catch { return []; }
}
