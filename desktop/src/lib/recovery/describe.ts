import type { RecoveryFile, RestoreResult } from "./api";

const FILE_STATE_TEXT: Record<string, string> = {
  same: "unchanged since the checkpoint",
  changed: "changed since the checkpoint",
  missing: "missing from its recorded location",
  unreadable: "could not be read",
  unverified: "no recorded fingerprint to compare",
};

export function fileStateText(state: string): string {
  return FILE_STATE_TEXT[state] ?? "state unknown";
}

/** A file is worth a second look unless its bytes are unchanged. */
export function needsAttention(file: RecoveryFile): boolean {
  return file.state !== "same";
}

export function fileLine(file: RecoveryFile): string {
  return `${file.name}: ${fileStateText(file.state)}. Matched by filename only (unverified).`;
}

export function jobLine(job: RestoreResult["jobs"][number]): string {
  return job.state === "interrupted"
    ? `Job ${job.job_id} was interrupted. It was recorded, not resumed.`
    : `Job ${job.job_id}: ${job.state}. Nothing was replayed.`;
}

export function summaryLines(data: RestoreResult): string[] {
  const lines: string[] = [];
  const attention = data.files.filter(needsAttention).length;
  if (data.files.length) lines.push(`${attention} of ${data.files.length} tracked files differ from the checkpoint or could not be compared.`);
  if (data.observations.length) lines.push(`${data.observations.length} restored observations are historical. Re-read them before relying on them.`);
  lines.push("Historical, re-read needed. A restored view never supports loadout conclusions.");
  return lines;
}

export function monitorLines(read: { print_state?: string; filename?: string | null; association?: string; note?: string; camera?: { state: string } }): string[] {
  return [
    `Printer state reported: ${read.print_state ?? "unknown"}`,
    `Filename reported: ${read.filename ?? "unknown"} (match to a local file: ${read.association ?? "unknown"})`,
    `Camera: ${read.camera?.state ?? "unknown"}`,
    ...(read.note ? [read.note] : []),
  ];
}
