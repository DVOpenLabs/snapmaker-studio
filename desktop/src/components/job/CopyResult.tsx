import { AlertTriangle, CheckCircle2, Copy, FileCheck2 } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { FlatCards } from "@/components/ui/card";
import { FidelityCard } from "@/components/FidelityCard";
import { FixLedgerCard } from "@/components/FixLedgerCard";
import { PrepareRefusal } from "@/components/PrepareRefusal";
import { PrepareSettingsSummary } from "@/components/PrepareSettingsSummary";
import { BlockedPanel, ProjectMaterialsFidelity } from "@/components/ProjectMaterialsCard";
import { useToast } from "@/store/toast";
import type { PrepareMode } from "@/api";
import type { PrepareController } from "@/hooks/usePrepare";

/** Where the copy is, as a person would say it: the folder name and the file. */
export function whereItIs(path: string): { name: string; folder: string } {
  const parts = path.split(/[\\/]/).filter(Boolean);
  const name = parts.pop() ?? path;
  return { name, folder: parts.length ? parts[parts.length - 1] : "" };
}

/**
 * What Create U1 copy produced: the file, where it is, what changed, and what could not be checked.
 * Success is read from the shared session (the one place that only accepts a validated copy of the
 * open project); a refusal or failure is read from this screen's own Prepare.
 */
export function CopyResult({ projectPath, prepared, unvalidatedPath, ctl, onPrepareRecommended, onCreateAnother }: {
  projectPath: string;
  /** The validated copy in the shared session, if any. */
  prepared: { path: string; name: string; summary: any; mode: PrepareMode } | null;
  /** A copy was written but its own validation did not pass. */
  unvalidatedPath: string | null;
  ctl: PrepareController;
  onPrepareRecommended?: () => void;
  /** Make another copy with the settings now chosen. Absent while material choices wait for their review. */
  onCreateAnother?: () => void;
}) {
  const showToast = useToast((s) => s.show);
  const copyPath = async (p: string) => {
    try { await navigator.clipboard.writeText(p); showToast("Copied the file's location."); } catch { /* clipboard unavailable */ }
  };
  const result = ctl.result;

  if (ctl.error) return <PrepareRefusal error={ctl.error} />;
  if (result?.blocked) return <BlockedPanel result={result} onBack={ctl.clearResult} />;
  if (result && !result.blocked && !result.output_path) {
    return (
      <p className="text-sm text-risk" role="alert" data-testid="prepare-no-file">
        Prepare finished but no copy was written, so there is nothing to open. Nothing was changed.
      </p>
    );
  }
  if (unvalidatedPath && !prepared) {
    return (
      <div className="space-y-3" data-testid="copy-unvalidated">
        <p className="flex items-start gap-2 text-sm font-medium">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-risk" aria-hidden="true" />
          A copy was written, but its check found issues.
        </p>
        <p className="text-sm text-muted-foreground">
          Studio did not confirm it, so it is not offered to Snapmaker Orca. Your original was not changed.
        </p>
        <FlatCards><FixLedgerCard source={projectPath} output={unvalidatedPath} /></FlatCards>
      </div>
    );
  }
  if (!prepared) return null;

  const where = whereItIs(prepared.path);
  return (
    <div className="space-y-4" data-testid="copy-result">
      <div className="space-y-1">
        <p className="flex items-center gap-2 text-sm font-semibold text-ready">
          <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> U1 copy created
        </p>
        <p className="flex items-start gap-2 text-sm">
          <FileCheck2 className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="min-w-0">
            <span className="break-all font-medium" title={prepared.path} data-testid="copy-name">{prepared.name}</span>
            {where.folder && <span className="block text-xs text-muted-foreground">in the folder <span className="font-medium text-foreground">{where.folder}</span></span>}
          </span>
        </p>
        <p className="text-xs text-muted-foreground">A new file. Your original was not changed.</p>
      </div>

      <p className="flex items-start gap-1.5 rounded-md border border-doctor-cost/40 bg-doctor-cost/5 p-2 text-xs text-muted-foreground">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-doctor-cost" aria-hidden="true" />
        Layout is not verified. This checks the U1 profile copy, not object placement. Review the project in
        Snapmaker Orca before slicing: for a project made for a larger printer an object may sit outside a
        plate, and Arrange all plates did not fix that in our test.
      </p>

      <ProjectMaterialsFidelity summary={prepared.summary?.project_materials} />

      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={() => copyPath(prepared.path)}>
          <Copy className="h-4 w-4" aria-hidden="true" /> Copy location
        </Button>
        {onCreateAnother && <Button size="sm" variant="ghost" onClick={onCreateAnother}>Create another copy</Button>}
        <Button size="sm" variant="ghost" asChild>
          <Link to="/doctor/project">Run Project Doctor</Link>
        </Button>
      </div>

      <FlatCards>
        <div className="space-y-2">
          {prepared.summary && (
            <Disclosure title="Review changes">
              <PrepareSettingsSummary summary={prepared.summary} mode={prepared.mode} isStl={false} onPrepareRecommended={onPrepareRecommended} />
            </Disclosure>
          )}
          <Disclosure title="What survived"><FidelityCard original={projectPath} prepared={prepared.path} /></Disclosure>
          <Disclosure title="What Studio did"><FixLedgerCard source={projectPath} output={prepared.path} /></Disclosure>
        </div>
      </FlatCards>
      <p className="text-[11px] text-muted-foreground">Advisory, not a print-success guarantee. Studio does not slice; Orca does.</p>
    </div>
  );
}

function Disclosure({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="group rounded-md border border-border">
      <summary className="cursor-pointer rounded-md px-3 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{title}</summary>
      <div className="border-t border-border p-3">{children}</div>
    </details>
  );
}
