import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, FolderSearch, HelpCircle, Loader2, RefreshCw, XCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { watchFolder } from "@/api";
import type { WatchCandidate, WatchResult } from "@/api";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";
import { useWatch } from "@/store/watch";
import { observeSliced } from "@/store/job";
import { ProvenanceNote, verdictLabel, verdictTone } from "@/components/ProvenanceNote";

const POLL_MS = 5000;

/**
 * The last manual step, removed.
 *
 * Snapmaker Orca writes its export somewhere. Studio watches that one folder —
 * chosen by the user, never guessed — while this page is open, and picks up a
 * finished job when it appears. It offers a file only once it can see the slicer
 * has stopped writing it, and it only opens one automatically when the evidence
 * actually ties it to the project in hand. Anything less certain is a list to
 * choose from, not a decision made on the user's behalf.
 *
 * Studio still does not slice, and nothing here leaves the machine — sending a
 * sliced job to the printer is Printer Hub's job, and only when the user says so.
 */
export function OrcaRoundTrip() {
  const folder = useWatch((s) => s.folder);
  const setFolder = useWatch((s) => s.setFolder);
  const autoOpen = useWatch((s) => s.autoOpen);
  const setAutoOpen = useWatch((s) => s.setAutoOpen);
  const project = useSession((s) => s.file);
  const setSliced = useSliced((s) => s.setSliced);
  const openPath = useSliced((s) => s.path);

  const [typed, setTyped] = useState(folder ?? "");
  const [answer, setAnswer] = useState<{ folder: string; project: string | undefined; data: WatchResult } | null>(null);
  const [busy, setBusy] = useState(false);
  const opened = useRef<string | null>(null);
  // Each look takes a ticket. A reply counts only if its ticket is still the
  // newest, so a slow answer about project A, a folder since changed, or a page
  // since left can never be applied to whatever is open now.
  const ticket = useRef(0);
  // The question currently being asked, so the timer does not stack a second scan on
  // a slow first one (and starve it of ever being the newest).
  const inFlight = useRef<string | null>(null);

  const look = useCallback((fromTimer = false) => {
    if (!folder) return;
    const key = `${folder}|${project?.path ?? ""}`;
    if (fromTimer && inFlight.current === key) return;
    inFlight.current = key;
    const mine = ++ticket.current;
    const asked = { folder, project: project?.path };
    setBusy(true);
    watchFolder(folder, project?.path)
      .then((data) => { if (ticket.current === mine) setAnswer({ ...asked, data }); })
      .catch(() => { if (ticket.current === mine) setAnswer(null); })
      .finally(() => { if (ticket.current === mine) { setBusy(false); inFlight.current = null; } });
  }, [folder, project?.path]);

  // Invalidate whatever is in flight when the question changes or the page goes.
  useEffect(() => () => { ticket.current += 1; inFlight.current = null; setAnswer(null); }, [folder, project?.path]);

  // An answer is shown only while it is still about the current folder and project.
  const result = answer && answer.folder === folder && answer.project === project?.path ? answer.data : null;

  useEffect(() => {
    if (!folder) return;
    look();
    const timer = window.setInterval(() => look(true), POLL_MS);
    return () => window.clearInterval(timer);
  }, [folder, look]);

  // Open the match by itself only when Studio is sure whose it is.
  useEffect(() => {
    if (!autoOpen || !result?.best) return;
    if (result.best === openPath || result.best === opened.current) return;
    opened.current = result.best;
    setSliced(result.best);
  }, [autoOpen, result, openPath, setSliced]);

  // The open job's path may now hold a different, finished export.
  useEffect(() => {
    if (!openPath || !result) return;
    for (const c of result.candidates ?? []) {
      if (c.path === openPath) {
        void observeSliced({ path: c.path, size_bytes: c.size_bytes, age_seconds: c.age_seconds, complete: c.complete, verdict: c.provenance?.verdict });
      }
    }
  }, [result, openPath]);

  if (!folder) {
    return (
      <Card>
        <CardContent className="space-y-3 p-5">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <FolderSearch className="h-4 w-4" aria-hidden="true" />
              Pick up sliced jobs automatically
            </h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Tell Studio where Snapmaker Orca saves its exports, once. It looks there
              while this page is open — nowhere else, and never on its own in the
              background.
            </p>
          </div>
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              const value = typed.trim().replace(/^"|"$/g, "");
              if (value) setFolder(value);
            }}
          >
            <input
              type="text"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              placeholder="C:\\Users\\you\\Documents\\Snapmaker Orca\\output"
              aria-label="Folder where your slicer saves G-code"
              className="min-w-0 flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
            />
            <Button type="submit" disabled={!typed.trim()}>Watch this folder</Button>
          </form>
        </CardContent>
      </Card>
    );
  }

  const candidates = result?.candidates ?? [];

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    : <FolderSearch className="h-4 w-4" aria-hidden="true" />}
              Watching for sliced jobs
            </h3>
            <p className="mt-0.5 break-all text-xs text-muted-foreground">{folder}</p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => look()} disabled={busy}>
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
              Look now
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setFolder(null)}>Change folder</Button>
          </div>
        </div>

        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={autoOpen}
            onChange={(event) => setAutoOpen(event.target.checked)}
          />
          Open a job automatically when Studio is sure it came from this project
        </label>

        {result?.error && <p className="text-xs text-risk">{result.error}</p>}
        {result?.summary && <p className="text-sm text-muted-foreground">{result.summary}</p>}

        {candidates.length > 0 && (
          <ul className="flex flex-col gap-2">
            {candidates.map((candidate) => (
              <CandidateRow
                key={candidate.path}
                candidate={candidate}
                open={candidate.path === openPath}
                onOpen={() => setSliced(candidate.path)}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function CandidateRow({ candidate, open, onOpen }: {
  candidate: WatchCandidate; open: boolean; onOpen: () => void;
}) {
  const verdict = candidate.provenance?.verdict;
  const tone = verdictTone(verdict);
  const Icon = tone === "ready" ? CheckCircle2 : tone === "risk" ? XCircle : HelpCircle;
  const border = tone === "ready" ? "border-ready/40" : tone === "risk" ? "border-risk/40" : "border-border";

  return (
    <li className={`rounded-md border ${border} p-2.5`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-sm font-medium">
          <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="break-all">{candidate.name}</span>
        </p>
        {candidate.complete ? (
          <Button size="sm" variant={open ? "ghost" : "secondary"} onClick={onOpen} disabled={open}>
            {open ? "Open" : "Check this one"}
          </Button>
        ) : (
          <span className="text-[11px] text-muted-foreground">{candidate.state}</span>
        )}
      </div>

      {candidate.job && candidate.complete && (
        <p className="mt-1 text-xs text-muted-foreground">
          {[candidate.job.printer_model,
            candidate.job.layer_count ? `${candidate.job.layer_count} layers` : null,
            candidate.job.total_g != null ? `${candidate.job.total_g} g` : null]
            .filter(Boolean).join(" · ")}
        </p>
      )}

      {candidate.provenance && (
        <div className="mt-1">
          <ProvenanceNote result={candidate.provenance} compact />
        </div>
      )}
    </li>
  );
}
