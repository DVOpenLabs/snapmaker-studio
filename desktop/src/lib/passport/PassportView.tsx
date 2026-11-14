import { useEffect, useState } from "react";
import { Fingerprint } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { useJob } from "@/store/job";
import { buildPassport, buildRequest, verifyPassport } from "./api";
import PassportReport from "./PassportReport";
import { belongsToOtherProject, fileFields, reportIsStale, usePassportSession } from "./session";
import type { BuildResponse } from "./types";

const FIELD = "h-9 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50";
const AREA = "min-h-20 w-full rounded-md border border-border bg-card p-2 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-primary/50";

const DIAGNOSTIC_TEXT: Record<string, string> = {
  file_missing: "One of those files was not found.",
  file_unreadable: "One of those files could not be read.",
  bad_role: "A file has a role this passport does not use.",
};

const projectNow = (): string | null => useJob.getState().record?.original.path ?? null;
const nameOf = (path: string | null) => (path ? path.split(/[\\/]/).pop() || path : null);

/** Builds a passport from files on this computer, then checks them against it. The files are only read; nothing is
 *  written, uploaded or sent to a printer. The fields and the report are kept while the application stays open
 *  (memory only), are tied to the project they were made for, and are cleared when a different project is opened. */
export default function PassportView() {
  const session = usePassportSession();
  const { inputs, built, verification, builtFor, notice } = session;
  const record = useJob((state) => state.record);
  const verified = useJob((state) => state.verified);
  const current = record?.original.path ?? null;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const foreign = belongsToOtherProject(session, current);
  useEffect(() => {
    if (foreign) usePassportSession.getState().projectChanged("A different project is open now, so the earlier project's passport and file fields were cleared.");
  }, [foreign, current]);

  const stale = reportIsStale(session);
  const shown = foreign ? null : built;
  const setField = (key: keyof typeof inputs) => (e: { target: { value: string } }) => session.setInput(key, e.target.value, projectNow());

  const check = async (response: BuildResponse) => {
    if (!response.passport) return;
    const gen = usePassportSession.getState().beginVerify();
    const res = await verifyPassport({ passport: response.passport, paths: response.paths });
    // Only the latest check of the report it belongs to may land (an older answer never overwrites a newer one).
    const now = usePassportSession.getState();
    if (res.verification && now.verifySeq === gen && now.built === response) now.setVerification(res.verification);
  };

  const build = async () => {
    setBusy(true); setError(null);
    const startProject = projectNow();
    const snapshot = { ...usePassportSession.getState().inputs };
    usePassportSession.getState().clearBuilt();
    const buildGen = usePassportSession.getState().beginBuild();
    try {
      const response = await buildPassport(buildRequest(fileFields(snapshot), snapshot.recipes, snapshot.mappings));
      // Another project was opened, or a newer build started (also from a re-entered page), while the files were read.
      if (projectNow() !== startProject || usePassportSession.getState().buildSeq !== buildGen) return;
      if (!response.passport) {
        const code = response.diagnostics[0]?.code ?? "";
        setError(DIAGNOSTIC_TEXT[code] ?? "The passport could not be built from those files.");
        return;
      }
      usePassportSession.getState().setBuilt(response, null, startProject, snapshot);
      await check(response);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The passport could not be built.");
    } finally {
      setBusy(false);
    }
  };

  const recheck = async () => {
    if (!built) return;
    setBusy(true); setError(null);
    try { await check(built); } catch (e) {
      setError(e instanceof Error ? e.message : "The check failed.");
    } finally { setBusy(false); }
  };

  const canBuild = inputs.original.trim() !== "" || inputs.prepared.trim() !== "" || inputs.sliced.trim() !== "";
  return (
    <div className="space-y-5 p-6">
      <PageHeader icon={Fingerprint} title="Job passport" subtitle="Record which files a job came from, then check later whether they are still the same bytes. Studio only reads these files." />
      {notice && <p className="text-sm" role="status" data-testid="passport-notice">{notice}</p>}
      <div className="flex flex-wrap items-end gap-2">
        <input className={`${FIELD} w-72`} aria-label="Original file path" placeholder="Original file path" value={inputs.original} onChange={setField("original")} />
        <input className={`${FIELD} w-72`} aria-label="Prepared copy path" placeholder="Prepared copy path (optional)" value={inputs.prepared} onChange={setField("prepared")} />
        <input className={`${FIELD} w-72`} aria-label="Sliced output path" placeholder="Sliced output path (optional)" value={inputs.sliced} onChange={setField("sliced")} />
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">Recipes and material mappings (optional JSON lists)</summary>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <textarea className={AREA} aria-label="Recipes JSON" placeholder="Recipes: a list of virtual_recipe/1 documents" value={inputs.recipes} onChange={setField("recipes")} />
          <textarea className={AREA} aria-label="Material mappings JSON" placeholder='Material mappings: [{"slot_ref":"slot:0","material":"PLA"}]' value={inputs.mappings} onChange={setField("mappings")} />
        </div>
      </details>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" disabled={busy || !record || !verified} onClick={() => record && verified && session.fillFromJob(record)}>Use this job's files</Button>
        <Button size="sm" disabled={busy || !canBuild} onClick={() => void build()}>{busy ? "Working..." : "Build passport"}</Button>
        <Button size="sm" variant="secondary" disabled={busy || !shown} onClick={() => void recheck()}>Check the files again</Button>
      </div>
      {record && !verified && <p className="text-xs text-muted-foreground" data-testid="passport-job-unverified">A saved job ({record.original.name}) is waiting from an earlier session. It has not been reopened or checked in this one, so its files are not offered here.</p>}
      <p className="text-xs text-muted-foreground">You are stating how these files relate. Studio records that as declared by you and checks that each file still has the bytes it had when the passport was built. The fields and report are kept while Studio stays open; they are not saved across a restart.</p>
      {error && <p className="text-sm text-risk" role="alert">{error}</p>}
      {shown?.passport && verification && builtFor && (
        <div className="space-y-2" data-testid="passport-scope">
          <p className="text-xs text-muted-foreground">Built for {builtFor.project ? `project ${nameOf(builtFor.project)}` : "the files entered (no project was open)"}.</p>
          {stale && <p className="text-sm text-risk" role="status" data-testid="passport-stale">The fields changed after this report was built, so it describes the earlier entries. Build the passport again for what is entered now.</p>}
          <div className={stale ? "opacity-60" : undefined}><PassportReport passport={shown.passport} verification={verification} /></div>
        </div>
      )}
    </div>
  );
}
