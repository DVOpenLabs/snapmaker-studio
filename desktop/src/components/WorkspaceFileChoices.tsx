import { Button } from "@/components/ui/button";
import { useJob } from "@/store/job";
import type { JobRole } from "@/lib/jobRecord";

const labels: Record<JobRole, string> = { original: "Project", prepared: "Prepared copy", sliced: "Sliced output" };
const roles: JobRole[] = ["original", "prepared", "sliced"];

/** Explicitly copies a linked path into a tool. Does not read, prepare, compare or adopt a file. */
export default function WorkspaceFileChoices({ extensions, onChoose, disabled = false, label = "Use a file from this job" }: {
  extensions: readonly string[]; onChoose: (path: string) => void; disabled?: boolean; label?: string;
}) {
  const record = useJob(s => s.record);
  const verified = useJob(s => s.verified);
  const entries = roles.flatMap(role => {
    const file = record?.[role];
    return file && extensions.some(ext => file.path.toLowerCase().endsWith("." + ext.toLowerCase())) ? [{ role, file }] : [];
  });
  return <section aria-label={label} className="space-y-2 rounded-md border border-border p-3">
    <h2 className="text-sm font-medium">{label}</h2>
    {!record ? <p className="text-xs text-muted-foreground">Open a project first. You can still choose a file below.</p>
      : !verified ? <p role="status" className="text-xs text-muted-foreground">This saved job has not been reopened or checked in this session. Its files are not offered here.</p>
      : entries.length === 0 ? <p className="text-xs text-muted-foreground">No compatible file is linked to this job yet.</p>
      : <><div className="flex flex-wrap gap-2">{entries.map(({ role, file }) => <Button key={role} variant="secondary" size="sm" disabled={disabled} onClick={() => onChoose(file.path)}>{labels[role]}: {file.name}</Button>)}</div>
        <p className="text-xs text-muted-foreground">Select a file, then use this tool's action below. The tool reads its current bytes; a linked name is not a fresh file check.</p></>}
  </section>;
}
