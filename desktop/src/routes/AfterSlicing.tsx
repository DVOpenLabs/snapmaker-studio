import { useState } from "react";
import { FileCheck2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SlicedJobCards } from "@/components/SlicedJobCards";
import { OrcaRoundTrip } from "@/components/OrcaRoundTrip";
import { JobWorkspaceCard } from "@/components/JobWorkspaceCard";
import { SettingsReceiptCard } from "@/components/SettingsReceiptCard";
import { useSliced } from "@/store/sliced";
import { useSession } from "@/store/session";
import { useJob } from "@/store/job";
import { POST_SLICE_EXPLAINER } from "@/lib/postSlice";

/**
 * After slicing — the second half of the loop.
 *
 * Studio checks a project, prepares a copy, and hands it to Snapmaker Orca.
 * Orca slices. This is where the result comes back: Studio reads the G-code
 * itself and compares what the printer will actually execute against the
 * printer as it is right now.
 *
 * Studio does not slice, and nothing here sends anything to a printer.
 */
export default function AfterSlicing() {
  const path = useSliced((s) => s.path);
  const name = useSliced((s) => s.name);
  const setSliced = useSliced((s) => s.setSliced);
  const clear = useSliced((s) => s.clear);
  const revision = useSliced((s) => s.revision);
  const project = useSession((s) => s.file);
  const convert = useSession((s) => s.convert);
  // A prepared copy counts only if Studio wrote and validated it in this session.
  const prepared = convert.status === "done" && convert.data && !convert.data.blocked && convert.data.validated_ok
    ? convert.data.output_path : null;
  // A restored job keeps its prepared copy on record but does not reopen it, so the receipt must say so.
  const hasSavedPrepared = useJob((s) => s.record?.prepared != null);
  const preparedOmitted = !prepared && hasSavedPrepared;
  const [typed, setTyped] = useState("");

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="text-lg font-semibold">After slicing</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{POST_SLICE_EXPLAINER}</p>
      </div>

      <JobWorkspaceCard />

      <OrcaRoundTrip />

      {!path && (
        <Card>
          <CardContent className="space-y-4 p-5">
            <div className="flex items-start gap-3">
              <FileCheck2 className="mt-0.5 h-5 w-5 text-muted-foreground" aria-hidden="true" />
              <div>
                <p className="text-sm font-medium">Open the G-code your slicer produced</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Drag the <code>.gcode</code> file onto this window, or paste its full
                  path below. Studio reads it and never changes it.
                </p>
              </div>
            </div>

            <form
              className="flex flex-wrap items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                const value = typed.trim().replace(/^"|"$/g, "");
                if (value) setSliced(value);
              }}
            >
              <input
                type="text"
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                placeholder="C:\\Users\\you\\Downloads\\something_PLA_2h13m.gcode"
                aria-label="Path to a sliced G-code file"
                className="min-w-0 flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
              />
              <Button type="submit" disabled={!typed.trim()}>Check this job</Button>
            </form>

            <p className="text-[11px] text-muted-foreground">
              Studio can also be launched with a <code>.gcode</code> path on its command
              line, which is what a file association or “Open with” does.
            </p>
          </CardContent>
        </Card>
      )}

      {path && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm">
              <span className="text-muted-foreground">Checking</span>{" "}
              <span className="font-medium" title={path}>{name}</span>
              {project && (
                <>
                  {" "}
                  <span className="text-muted-foreground">against the open project</span>{" "}
                  <span className="font-medium">{project.name}</span>
                </>
              )}
            </p>
            <Button variant="secondary" size="sm" onClick={clear}>Choose another file</Button>
          </div>
          {project && <SettingsReceiptCard key={`receipt-${path}#${revision}`} original={project.path} prepared={prepared} sliced={path}
            revision={revision} preparedOmitted={preparedOmitted} />}
          <SlicedJobCards path={path} projectPath={project?.path} />
        </>
      )}
    </div>
  );
}
