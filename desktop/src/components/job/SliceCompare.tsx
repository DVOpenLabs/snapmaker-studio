import { Link } from "react-router-dom";
import { FlatCards } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { OrcaRoundTrip } from "@/components/OrcaRoundTrip";
import { SettingsReceiptCard } from "@/components/SettingsReceiptCard";
import { SlicedJobCards } from "@/components/SlicedJobCards";
import { useJob } from "@/store/job";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";

/**
 * The returned slice, compared with the project and the U1 copy, inside the same job.
 * The receipt's own comparison and scope note are used as they are; the G-code checks sit
 * beneath it for anyone who wants the detail.
 */
export function SliceCompare({ projectPath, preparedPath }: { projectPath: string; preparedPath: string | null }) {
  const sliced = useSliced((s) => s.path);
  const slicedName = useSliced((s) => s.name);
  const revision = useSliced((s) => s.revision);
  const clear = useSliced((s) => s.clear);
  const preparing = useSession((s) => s.convert.status === "loading");
  // A restored job keeps its prepared copy on record but does not reopen it, so the receipt must say so.
  const hasSavedPrepared = useJob((s) => s.record?.prepared != null);
  const preparedOmitted = !preparedPath && hasSavedPrepared && !preparing;

  return (
    <div className="space-y-4" data-testid="slice-compare">
      {!sliced ? (
        <div className="space-y-3">
          <p className="text-sm font-medium">No slice yet</p>
          <p className="text-sm text-muted-foreground">
            Slice the U1 copy in Snapmaker Orca and export the <code>.gcode</code>. Studio can watch the folder you choose,
            or you can open the file from <Link className="underline" to="/after-slicing">After slicing</Link>.
          </p>
          <FlatCards><OrcaRoundTrip /></FlatCards>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm">
              <span className="text-muted-foreground">Comparing</span>{" "}
              <span className="break-all font-medium" title={sliced}>{slicedName}</span>
            </p>
            <Button size="sm" variant="secondary" onClick={clear}>Choose another file</Button>
          </div>
          <FlatCards>
            <SettingsReceiptCard key={`receipt-${sliced}#${revision}`} original={projectPath} prepared={preparedPath} sliced={sliced}
              revision={revision} preparedOmitted={preparedOmitted} preparing={preparing} />
            <details className="mt-4 rounded-md border border-border">
              <summary className="cursor-pointer rounded-md px-3 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">G-code checks</summary>
              <div className="space-y-4 border-t border-border p-3"><SlicedJobCards path={sliced} projectPath={projectPath} /></div>
            </details>
          </FlatCards>
        </>
      )}
    </div>
  );
}
