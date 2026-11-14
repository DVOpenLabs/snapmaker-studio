import { useEffect, useRef, useState } from "react";
import { Fingerprint } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { buildPassport, buildRequest, verifyPassport } from "./api";
import PassportReport from "./PassportReport";
import type { BuildResponse, Verification } from "./types";

const FIELD = "h-9 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50";
const AREA = "min-h-20 w-full rounded-md border border-border bg-card p-2 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-primary/50";

const DIAGNOSTIC_TEXT: Record<string, string> = {
  file_missing: "One of those files was not found.",
  file_unreadable: "One of those files could not be read.",
  bad_role: "A file has a role this passport does not use.",
};

/** Builds a passport from files on this computer, then checks them against it. The files are
 *  only read; nothing is written, uploaded or sent to a printer. */
export default function PassportView() {
  const [original, setOriginal] = useState("");
  const [prepared, setPrepared] = useState("");
  const [sliced, setSliced] = useState("");
  const [recipes, setRecipes] = useState("");
  const [mappings, setMappings] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [built, setBuilt] = useState<BuildResponse | null>(null);
  const [verification, setVerification] = useState<Verification | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const check = async (response: BuildResponse) => {
    if (!response.passport) return;
    const res = await verifyPassport({ passport: response.passport, paths: response.paths });
    if (alive.current) setVerification(res.verification);
  };

  const build = async () => {
    setBusy(true); setError(null); setBuilt(null); setVerification(null);
    try {
      const response = await buildPassport(buildRequest({ original, prepared, sliced }, recipes, mappings));
      if (!alive.current) return;
      if (!response.passport) {
        const code = response.diagnostics[0]?.code ?? "";
        setError(DIAGNOSTIC_TEXT[code] ?? "The passport could not be built from those files.");
        return;
      }
      setBuilt(response);
      await check(response);
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : "The passport could not be built.");
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const recheck = async () => {
    if (!built) return;
    setBusy(true); setError(null);
    try { await check(built); } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : "The check failed.");
    } finally { if (alive.current) setBusy(false); }
  };

  return (
    <div className="space-y-5 p-6">
      <PageHeader icon={Fingerprint} title="Job passport" subtitle="Record which files a job came from, then check later whether they are still the same bytes. Studio only reads these files." />
      <div className="flex flex-wrap items-end gap-2">
        <input className={`${FIELD} w-72`} aria-label="Original file path" placeholder="Original file path" value={original} onChange={(e) => setOriginal(e.target.value)} />
        <input className={`${FIELD} w-72`} aria-label="Prepared copy path" placeholder="Prepared copy path (optional)" value={prepared} onChange={(e) => setPrepared(e.target.value)} />
        <input className={`${FIELD} w-72`} aria-label="Sliced output path" placeholder="Sliced output path (optional)" value={sliced} onChange={(e) => setSliced(e.target.value)} />
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">Recipes and material mappings (optional JSON lists)</summary>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <textarea className={AREA} aria-label="Recipes JSON" placeholder="Recipes: a list of virtual_recipe/1 documents" value={recipes} onChange={(e) => setRecipes(e.target.value)} />
          <textarea className={AREA} aria-label="Material mappings JSON" placeholder='Material mappings: [{"slot_ref":"slot:0","material":"PLA"}]' value={mappings} onChange={(e) => setMappings(e.target.value)} />
        </div>
      </details>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={busy || (original.trim() === "" && prepared.trim() === "" && sliced.trim() === "")} onClick={() => void build()}>{busy ? "Working..." : "Build passport"}</Button>
        <Button size="sm" variant="secondary" disabled={busy || !built} onClick={() => void recheck()}>Check the files again</Button>
      </div>
      <p className="text-xs text-muted-foreground">You are stating how these files relate. Studio records that as declared by you and checks that each file still has the bytes it had when the passport was built.</p>
      {error && <p className="text-sm text-risk" role="alert">{error}</p>}
      {built?.passport && verification && <PassportReport passport={built.passport} verification={verification} />}
    </div>
  );
}
