import { Link } from "react-router-dom";
import { ArrowRight, CircleDot, FileCheck2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PlacementCard } from "@/components/PlacementCard";
import { PreflightCard } from "@/components/PreflightCard";
import { ColorPlanCard } from "@/components/ColorPlanCard";
import { FidelityCard } from "@/components/FidelityCard";
import { FixLedgerCard } from "@/components/FixLedgerCard";
import { OrcaHandoff } from "@/components/OrcaHandoff";
import { OrcaRoundTrip } from "@/components/OrcaRoundTrip";
import { SlicedJobCards } from "@/components/SlicedJobCards";
import { JobHeader } from "@/components/JobHeader";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";

/**
 * One job, moving through its stages.
 *
 * Studio grew as a set of Doctors, each with its own page, and each of them is
 * genuinely useful — but a person with a model in front of them does not have a
 * "Doctor" problem, they have a *this print* problem, and answering it meant
 * visiting five pages in the right order and knowing what that order was.
 *
 * This is the same work in one place, in the order it actually happens. The
 * individual pages stay exactly where they were: an expert who wants the colour
 * planner on its own still has it, and nothing here hides detail — it just stops
 * requiring navigation to see the shape of the thing.
 */
export default function Cockpit() {
  const project = useSession((s) => s.file);
  const convert = useSession((s) => s.convert);
  const sliced = useSliced((s) => s.path);
  const slicedName = useSliced((s) => s.name);

  // Same test as After slicing and the job header: a copy Studio wrote and validated this session.
  // Behaviour change from before: a blocked or unvalidated result no longer offers the Orca handoff.
  const prepared: string | undefined = convert.status === "done" && convert.data && !convert.data.blocked && convert.data.validated_ok
    ? (convert.data.output_path || convert.data.output) : undefined;

  if (!project) {
    return (
      <div className="flex flex-col gap-5">
        <Header />
        <Card>
          <CardContent className="space-y-2 p-5">
            <p className="text-sm font-medium">Open a model to start</p>
            <p className="text-sm text-muted-foreground">
              Drop an <code>.stl</code> or <code>.3mf</code> onto this window, or open one
              from <Link className="underline" to="/projects">My designs</Link>. Studio reads
              it, checks it against your printer, and stays with the job until it is on the
              plate.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <JobHeader />

      <Stage number={1} title="Before slicing"
             detail="What this project is, and how it compares to the printer Studio can see.">
        <PlacementCard path={project.path} />
        <PreflightCard path={project.path} />
        <ColorPlanCard path={project.path} />
      </Stage>

      <Stage id="job-stage-prepared" number={2} title="Prepared"
             detail="What Studio changed, what survived, and the way back.">
        {prepared ? (
          <>
            <FidelityCard original={project.path} prepared={prepared} />
            <FixLedgerCard source={project.path} output={prepared} />
            <OrcaHandoff outputPath={prepared} />
          </>
        ) : (
          <Card>
            <CardContent className="space-y-2 p-5">
              <p className="text-sm">Nothing prepared yet.</p>
              <p className="text-sm text-muted-foreground">
                Preparing writes a new copy and never touches your original. Do it from{" "}
                <Link className="underline" to="/workspace">the workspace</Link>, and the
                result appears here.
              </p>
            </CardContent>
          </Card>
        )}
      </Stage>

      <Stage number={3} title="After slicing"
             detail="Snapmaker Orca slices. Studio picks the result back up and checks what the printer will actually do.">
        <OrcaRoundTrip />
        {sliced ? (
          <>
            <SlicedJobCards path={sliced} projectPath={project.path} />
          </>
        ) : (
          <Card>
            <CardContent className="space-y-2 p-5">
              <p className="text-sm">No sliced job yet.</p>
              <p className="text-sm text-muted-foreground">
                Slice the prepared copy in Snapmaker Orca. If you told Studio where Orca
                saves its exports, the job appears here on its own — otherwise open it from{" "}
                <Link className="underline" to="/after-slicing">After Slicing</Link>.
              </p>
            </CardContent>
          </Card>
        )}
      </Stage>

      {sliced && (
        <p className="text-xs text-muted-foreground">
          Checking <span className="font-medium">{slicedName}</span>. Studio does not slice
          and never sends anything on its own.
        </p>
      )}
    </div>
  );
}

function Header({ name }: { name?: string }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <FileCheck2 className="h-5 w-5" aria-hidden="true" />
          {name ? `This print — ${name}` : "This print"}
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          One job, from the file you downloaded to the moment it is ready to send. Every
          stage is also its own page if you would rather work that way.
        </p>
      </div>
      <Button asChild variant="secondary" size="sm">
        <Link to="/compatibility">
          Open the full checks <ArrowRight className="ml-1.5 h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      </Button>
    </div>
  );
}

function Stage({ id, number, title, detail, children }: {
  id?: string; number: number; title: string; detail: string; children: React.ReactNode;
}) {
  return (
    <section id={id} tabIndex={id ? -1 : undefined} aria-label={`${number}. ${title}`} className="flex flex-col gap-3 outline-none">
      <div className="flex items-start gap-2">
        <CircleDot className="mt-0.5 h-4 w-4 text-muted-foreground" aria-hidden="true" />
        <div>
          <h3 className="text-sm font-semibold">
            <span className="text-muted-foreground">{number}. </span>{title}
          </h3>
          <p className="text-xs text-muted-foreground">{detail}</p>
        </div>
      </div>
      <div className="flex flex-col gap-4 border-l border-border pl-5">{children}</div>
    </section>
  );
}
