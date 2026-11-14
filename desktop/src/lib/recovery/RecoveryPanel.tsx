import type { RestoreResult } from "./api";
import { fileLine, jobLine, monitorLines, needsAttention, summaryLines } from "./describe";

/** Presentational restore preview. Pure of state so it renders to static markup in tests. */
export function RestorePreview({ data }: { data: RestoreResult | null }) {
  if (!data) return <p className="text-sm text-muted-foreground">Reading the last checkpoint.</p>;
  if (data.missing_checkpoint) return <p className="text-sm">No checkpoint saved yet.</p>;
  const changed = data.files.filter(needsAttention);
  return <div className="space-y-2 text-sm" data-testid="restore-preview">
    <p>Last checkpoint: {data.checkpointed_at ?? "time unavailable"} · revision {data.revision}</p>
    <h3 className="font-medium">Restore preview</h3>
    {data.files.length === 0 ? <p>No tracked files in this checkpoint.</p> : <ul className="list-disc pl-5">
      {data.files.map((file, i) => <li key={`${file.name}-${i}`} className={needsAttention(file) ? "text-amber-700" : undefined}>{fileLine(file)}</li>)}
    </ul>}
    {changed.length > 0 && <p>{changed.length} file(s) changed or missing: review them before continuing.</p>}
    {data.jobs.map((job) => <p key={job.job_id}>{jobLine(job)}</p>)}
    {data.legacy_job?.files?.map((file) => <p key={file.role}>Imported earlier {file.role}: {file.name} (matched by filename only, unverified)</p>)}
    {summaryLines(data).map((line) => <p key={line} className="text-amber-700">{line}</p>)}
  </div>;
}

export function MonitorSummary({ read }: { read: Parameters<typeof monitorLines>[0] | null }) {
  if (!read) return null;
  return <div className="text-sm" data-testid="monitor-summary">{monitorLines(read).map((line) => <p key={line}>{line}</p>)}</div>;
}
