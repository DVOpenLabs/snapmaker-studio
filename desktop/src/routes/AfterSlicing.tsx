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
import { Link } from "react-router-dom";

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
  // A re-preparation in flight is not an omission: the new copy joins the comparison once validated.
  const preparing = convert.status === "loading";
  const preparedOmitted = !prepared && hasSavedPrepared && !preparing;
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
              <span className="break-all font-medium" title={path}>{name}</span>
              {project && (
                <>
                  {" "}
                  <span className="text-muted-foreground">against the open project</span>{" "}
                  <span className="break-all font-medium">{project.name}</span>
                </>
              )}
            </p>
            <Button variant="secondary" size="sm" onClick={clear}>Choose another file</Button>
          </div>
          {project && <SettingsReceiptCard key={`receipt-${path}#${revision}`} original={project.path} prepared={prepared} sliced={path}
            revision={revision} preparedOmitted={preparedOmitted} preparing={preparing} />}
          <KeptSeparate />
          <SlicedJobCards path={path} projectPath={project?.path} />
        </>
      )}
    </div>
  );
}

const SEPARATE: Array<{ title: string; text: string; to?: string; link?: string }> = [
  { title: "Printer connection", text: "Not needed to read a slice. Checked in Printer Hub.", to: "/printers", link: "Printer Hub" },
  { title: "Project compatibility", text: "Whether the G-code is this project, and whether the profile fits the U1: the cards below." },
  { title: "Settings comparison", text: "Declared values only: the receipt above." },
  { title: "Print readiness", text: "Not decided by the receipt. Sending is always your confirmed choice." },
];

/** Four different questions, each answered somewhere else; none of them stands in for another. */
function KeptSeparate() {
  return (
    <section aria-labelledby="kept-separate" className="rounded-md border border-border p-3">
      <h3 id="kept-separate" className="text-xs font-semibold">Four separate questions</h3>
      <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2">
        {SEPARATE.map((item) => (
          <div key={item.title} className="min-w-0">
            <dt className="text-xs font-medium">{item.title}</dt>
            <dd className="text-xs text-muted-foreground">
              {item.text}{" "}
              {item.to && <Link to={item.to} className="underline">{item.link}</Link>}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
