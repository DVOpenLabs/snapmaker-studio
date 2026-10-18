import { useState } from "react";
import { History, Link2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useJob } from "@/store/job";
import { useSession } from "@/store/session";
import { restorable, JOB_ROLES, type FileState, type JobRole, type LinkedFile } from "@/lib/jobRecord";

const LABEL: Record<JobRole, string> = {
  original: "Project",
  prepared: "Prepared copy",
  sliced: "Sliced G-code",
};

const STATE_TEXT: Record<FileState, string> = {
  same: "Unchanged since it was recorded",
  changed: "Changed since it was recorded",
  missing: "Not found where it was",
  unreadable: "Could not be read",
  unverified: "Cannot be confirmed as the same file",
};

const short = (file: LinkedFile) => (file.fingerprint?.sha256 ? file.fingerprint.sha256.slice(0, 8) : null);

/**
 * One job, three files — and what Studio can still vouch for after a restart.
 *
 * Shows which project, prepared copy and sliced G-code belong together. After a
 * restart it offers to reopen them, but only after checking each against the
 * size and hash recorded earlier, and never by preparing, slicing or sending
 * anything again.
 */
export function JobWorkspaceCard() {
  const record = useJob((s) => s.record);
  const phase = useJob((s) => s.phase);
  const check = useJob((s) => s.check);
  const error = useJob((s) => s.error);
  const runCheck = useJob((s) => s.runCheck);
  const restore = useJob((s) => s.restore);
  const forget = useJob((s) => s.forget);
  const project = useSession((s) => s.file);
  const [named, setNamed] = useState<ReadonlySet<JobRole>>(new Set());

  if (!record) return null;

  const resuming = !project;
  const current = project?.path === record.original.path;
  if (!resuming && !current) return null;

  const toggle = (role: JobRole) => {
    const next = new Set(named);
    if (next.has(role)) next.delete(role); else next.add(role);
    setNamed(next);
  };

  // The prepared copy is shown for reference; there is nothing to reopen for it.
  const plan = phase === "done" ? restorable(check, named).filter((role) => role !== "prepared") : [];
  const rows = JOB_ROLES.flatMap((role) => (record[role] ? [{ role, file: record[role] as LinkedFile }] : []));

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              {resuming ? <History className="h-4 w-4" aria-hidden="true" /> : <Link2 className="h-4 w-4" aria-hidden="true" />}
              {resuming ? "Pick up your last job" : "This job"}
            </h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {resuming
                ? "Studio kept which files belonged together. Check them before reopening — files can move or change."
                : "The project, the copy Studio prepared from it and the G-code that came back, kept together."}
            </p>
          </div>
          {resuming && (
            <div className="flex items-center gap-2">
              <Button size="sm" variant="secondary" onClick={() => void runCheck()} disabled={phase === "checking"}>
                {phase === "checking" ? "Checking…" : phase === "done" ? "Check again" : "Check these files"}
              </Button>
              <Button size="sm" variant="ghost" onClick={forget}>Forget this job</Button>
            </div>
          )}
        </div>

        <ul className="flex flex-col gap-2">
          {rows.map(({ role, file }) => {
            const state = phase === "done" ? check[role] : undefined;
            const canName = resuming && (state === "changed" || state === "unverified") && role !== "prepared";
            const unfinished = !file.fingerprint;
            return (
              <li key={role} className="rounded-md border border-border p-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm">
                    <span className="text-muted-foreground">{LABEL[role]}</span>{" "}
                    <span className="break-all font-medium" title={file.path}>{file.name}</span>
                    {role === "prepared" && record.prepared && (
                      <span className="text-muted-foreground"> · {record.prepared.mode} mode</span>
                    )}
                  </p>
                  {short(file) && <code className="text-[11px] text-muted-foreground" title="Start of the file's SHA-256">{short(file)}</code>}
                </div>
                {state && (
                  <p className={`mt-1 text-xs ${state === "same" ? "text-ready" : "text-muted-foreground"}`}>{STATE_TEXT[state]}</p>
                )}
                {!resuming && unfinished && (
                  <p className="mt-1 text-xs text-muted-foreground">Not yet recorded — it cannot be confirmed later until it is.</p>
                )}
                {canName && (
                  <label className="mt-1 flex items-center gap-2 text-xs">
                    <input type="checkbox" checked={named.has(role)} onChange={() => toggle(role)} />
                    {role === "original"
                      ? "Reopen it anyway (the prepared copy and G-code will not be linked to it)"
                      : "Reopen it anyway"}
                  </label>
                )}
              </li>
            );
          })}
        </ul>

        {error && <p className="text-xs text-risk">{error}</p>}

        {resuming && phase === "done" && (
          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm" onClick={() => restore(named)} disabled={plan.length === 0}>
              {plan.length === 0 ? "Nothing to reopen" : `Reopen ${plan.map((r) => LABEL[r].toLowerCase()).join(" and ")}`}
            </Button>
            <p className="text-[11px] text-muted-foreground">
              Reopening only shows these files again. It does not prepare, slice or send anything.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
