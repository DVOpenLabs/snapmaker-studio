import { Link } from "react-router-dom";
import { AlertTriangle, ArrowRight, Check, Circle, CircleDot, FileCheck2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";
import { deriveSteps, nextAction, type JobFacts, type StepState } from "@/lib/jobProgress";

const MARK: Record<StepState, typeof Check> = {
  done: Check, review: AlertTriangle, current: CircleDot, todo: Circle, blocked: XCircle, error: XCircle,
};

/** Facts the job header reads, taken straight from the existing stores. */
export function useJobFacts(): JobFacts {
  const project = useSession((s) => s.file);
  const doctor = useSession((s) => s.doctor);
  const convert = useSession((s) => s.convert);
  const sliced = useSliced((s) => s.path);
  return {
    hasProject: !!project,
    doctor: {
      status: doctor.status,
      prepareBlocked: !!doctor.data?.prepare_blocked,
      verdict: typeof doctor.data?.verdict === "string" ? doctor.data.verdict : null,
    },
    convert: {
      status: convert.status,
      blocked: !!convert.data?.blocked,
      validatedOk: !!convert.data?.validated_ok,
      outputName: convert.data?.output_name ?? null,
    },
    hasSliced: !!sliced,
  };
}

/**
 * The job at a glance: which project, where it is, and the one thing to do next.
 * Everything is derived from existing state; nothing here keeps its own.
 */
export function JobHeader() {
  const project = useSession((s) => s.file);
  const runDoctor = useSession((s) => s.runDoctor);
  const facts = useJobFacts();
  // A re-check bumps the shared request generation, so it would drop an in-flight prepare or preview.
  const previewLoading = useSession((s) => s.preview.status === "loading");
  if (!project) return null;

  const steps = deriveSteps(facts);
  const next = nextAction(facts);

  const goTo = (id: string) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({ block: "start" });
    el.focus({ preventScroll: true });
  };

  return (
    <section aria-labelledby="job-title" className="rounded-lg border border-border bg-card p-4 sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">This job</p>
        {/* The full checks stay one click away; not repeated when the next action already is that link. */}
        {next.action?.to !== "/compatibility" && (
          <Button asChild variant="ghost" size="sm" className="-mr-2">
            <Link to="/compatibility">Open the full checks <ArrowRight className="ml-1.5 h-3.5 w-3.5" aria-hidden="true" /></Link>
          </Button>
        )}
      </div>
      <h2 id="job-title" className="mt-0.5 flex min-w-0 items-start gap-2 text-lg font-semibold">
        <FileCheck2 className="mt-1 h-5 w-5 shrink-0" aria-hidden="true" />
        <span className="break-all" title={project.path}>{project.name}</span>
      </h2>

      <ol aria-label="Job progress" className="mt-4 flex flex-wrap gap-x-5 gap-y-2">
        {steps.map((step) => {
          const Icon = MARK[step.state];
          const tone = step.state === "done" ? "text-ready"
            : step.state === "review" || step.state === "error" || step.state === "blocked" ? "text-risk"
            : step.state === "current" ? "text-primary" : "text-muted-foreground";
          return (
            <li key={step.id} aria-current={step.state === "current" ? "step" : undefined}
                className={`flex items-center gap-1.5 text-sm ${step.state === "current" ? "font-semibold" : ""}`}>
              <Icon className={`h-4 w-4 shrink-0 ${tone}`} aria-hidden="true" />
              <span>{step.label}</span>
              {/* Words, not just a mark: the state is never colour alone. */}
              {step.state === "review" && <span className="text-xs font-normal text-muted-foreground">needs review</span>}
              {step.state === "blocked" && <span className="text-xs font-normal text-muted-foreground">unavailable</span>}
              {step.state === "error" && <span className="text-xs font-normal text-muted-foreground">failed</span>}
              <span className="sr-only">: {step.status}</span>
            </li>
          );
        })}
      </ol>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-md bg-muted/40 p-3" role="status">
        <div className="min-w-0">
          <p className="text-sm font-semibold"><span className="text-muted-foreground">Next: </span><span className="break-words">{next.headline}</span></p>
          <p className="mt-0.5 text-xs text-muted-foreground">{next.detail}</p>
        </div>
        {next.action?.kind === "link" && next.action.to && (
          <Button asChild size="sm">
            <Link to={next.action.to}>{next.action.label} <ArrowRight className="ml-1.5 h-3.5 w-3.5" aria-hidden="true" /></Link>
          </Button>
        )}
        {next.action?.kind === "scroll" && next.action.target && (
          <Button size="sm" onClick={() => goTo(next.action!.target!)}>{next.action.label}</Button>
        )}
        {next.action?.kind === "retry" && (
          <Button size="sm" disabled={facts.convert.status === "loading" || previewLoading} onClick={() => void runDoctor()}>{next.action.label}</Button>
        )}
      </div>
    </section>
  );
}
