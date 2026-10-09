import { useEffect, useRef, useState } from "react";
import { Loader2, RotateCw } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { loadScene, sceneErrorText } from "@/lib/scene";
import { useTheme } from "@/store/theme";
import { createSceneViewer } from "./defaultViewport";
import { CAMERA_PRESETS, SLOPE_LABEL } from "./readOnlyViewport";
import { CREDIT_SECTIONS, SLICERX_CREDIT } from "./credits";
import { SceneController, type ViewerState } from "./sceneController";

const STAGE_TEXT: Record<string, string> = {
  reading: "Reading the file",
  parsing: "Reading the model",
  encoding: "Preparing the view",
};

export function progressText(p: ViewerState["progress"]): string {
  if (!p) return "Starting the 3D view";
  if (p.state === "queued") return "Waiting for the engine";
  const stage = p.stage ? STAGE_TEXT[p.stage] : "Working";
  // Never "100%": the job is still working until it reports done, so the figure stops at 99 and disappears when complete.
  return p.completed !== null && p.total && p.completed < p.total ? `${stage} (${Math.min(99, Math.round((p.completed / p.total) * 100))}%)` : stage;
}

const TONE_TEXT = { placement: "Placement note", size: "Size note" } as const;
const TONE_CLASS = {
  placement: "border-risk text-risk",
  size: "border-repairable text-repairable",
} as const;

const EMPTY: ViewerState = {
  phase: "idle", progress: null, error: null, model: null, revision: null, graphics: "none", graphicsNote: null,
  selectedId: null, preset: "bed", slope: false,
};

/** A read-only 3D view of the opened project, with the engine's placement and size notes. Never edits anything. */
export default function ProjectScenePanel({ path, wide = false }: { path: string; wide?: boolean }) {
  const theme = useTheme((s) => s.theme);
  const themeRef = useRef(theme);
  themeRef.current = theme;
  const hostRef = useRef<HTMLDivElement>(null);
  const controllerRef = useRef<SceneController | null>(null);
  const [view, setView] = useState<ViewerState>(EMPTY);

  // One controller per effect: StrictMode's mount, cleanup, mount makes two, and the first is fully disposed.
  useEffect(() => {
    const controller = new SceneController({ load: loadScene, viewportFactory: createSceneViewer, theme: themeRef.current });
    controllerRef.current = controller;
    const off = controller.subscribe(() => setView(controller.getState()));
    controller.setHost(hostRef.current);
    controller.setPath(path);
    return () => {
      off();
      controller.dispose();
      if (controllerRef.current === controller) controllerRef.current = null;
    };
  }, [path]);

  useEffect(() => { controllerRef.current?.setTheme(theme); }, [theme]);

  const c = () => controllerRef.current;
  const model = view.model;
  const noGraphics = view.graphics === "unavailable" || view.graphics === "lost";

  return (
    <Card data-testid="project-scene">
      <CardContent className="min-w-0 space-y-3 p-4">
        <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-base font-semibold">3D view of this project</h3>
          <p className="text-xs text-muted-foreground">
            Read-only: Studio never moves or changes your model here.{model ? ` ${model.summary}.` : ""}
          </p>
        </div>

        <div className={cn("grid gap-3", wide && view.phase === "shown" ? "lg:grid-cols-[minmax(0,1fr)_20rem]" : "")}>
          <div className="min-w-0 space-y-2">
            <div className="relative aspect-[4/3] min-h-[220px] w-full overflow-hidden rounded-md border border-border bg-muted">
              <div ref={hostRef} className="absolute inset-0" data-testid="scene-host" />
              {view.phase === "loading" && (
                <p role="status" className="absolute inset-0 flex items-center justify-center gap-2 p-4 text-center text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {progressText(view.progress)}
                </p>
              )}
              {view.phase === "failed" && view.error && (
                <div role="alert" className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-card p-4 text-center text-sm">
                  <span>{sceneErrorText(view.error)}</span>
                  <Button type="button" size="sm" variant="secondary" onClick={() => c()?.retryLoad()}>
                    <RotateCw className="h-3.5 w-3.5" aria-hidden="true" /> Try again
                  </Button>
                </div>
              )}
              {noGraphics && view.phase === "shown" && (
                <div role="alert" className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-card p-4 text-center text-sm">
                  <p>
                    {view.graphics === "lost"
                      ? "The 3D drawing stopped (the graphics connection was lost)."
                      : "3D graphics are not available on this computer right now."}{" "}
                    The object list and notes still work.
                  </p>
                  <Button type="button" size="sm" variant="secondary" onClick={() => c()?.startGraphics()}>
                    <RotateCw className="h-3.5 w-3.5" aria-hidden="true" /> Retry 3D view
                  </Button>
                </div>
              )}
            </div>
            {view.graphicsNote && <p role="status" className="text-xs text-muted-foreground">{view.graphicsNote}</p>}

            <div role="group" aria-label="Camera views" className="flex flex-wrap gap-1.5">
              {CAMERA_PRESETS.map((p) => (
                <Button key={p.id} type="button" size="sm" variant="secondary" className="h-auto min-h-8 whitespace-normal py-1" disabled={view.graphics !== "working"} onClick={() => c()?.setCamera(p.id)}>
                  {p.label}
                </Button>
              ))}
              <Button
                type="button" size="sm" variant="secondary" disabled={view.graphics !== "working"} aria-pressed={view.slope}
                aria-describedby="scene-slope-label" className={cn("h-auto min-h-8 whitespace-normal py-1", view.slope && "border-primary text-primary")}
                onClick={() => c()?.setSlope(!view.slope)}
              >
                Slope view
              </Button>
            </div>
            <p id="scene-slope-label" className={cn("text-xs text-muted-foreground", !view.slope && "sr-only")}>{SLOPE_LABEL}</p>
          </div>

          {view.phase === "shown" && model && (
            <div className="min-w-0 space-y-3 text-sm">
              <section aria-labelledby="scene-objects">
                <h4 id="scene-objects" className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Objects</h4>
                {model.objects.length === 0 ? (
                  <p className="text-muted-foreground">This file lists no objects to show.</p>
                ) : (
                  <ul className="max-h-56 space-y-1 overflow-auto pr-1">
                    {model.objects.map((o) => (
                      <li key={o.id}>
                        <button
                          type="button" aria-pressed={view.selectedId === o.id} disabled={!o.hasGeometry}
                          onClick={() => c()?.selectFromList(view.selectedId === o.id ? null : o.id)}
                          className={cn(
                            "flex w-full flex-wrap items-center justify-between gap-x-2 rounded-md border border-border px-2 py-1.5 text-left hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
                            view.selectedId === o.id && "border-primary bg-muted",
                          )}
                        >
                          <span className="min-w-0 break-words font-medium">{o.label}</span>
                          <span className="min-w-0 break-words text-xs text-muted-foreground">{o.roleText}, {o.plateText}</span>
                          {o.tone && (
                            <span className={cn("rounded border px-1.5 text-xs", TONE_CLASS[o.tone])}>{TONE_TEXT[o.tone]}</span>
                          )}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section aria-labelledby="scene-findings">
                <h4 id="scene-findings" className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Notes from Studio’s checks</h4>
                {model.findings.length === 0 ? (
                  <p className="text-muted-foreground">Studio made no placement or size notes for this project.</p>
                ) : (
                  <ul className="space-y-1">
                    {model.findings.map((f) => (
                      <li key={f.id}>
                        {f.projectLevel ? (
                          <p className={cn("break-words rounded-md border px-2 py-1.5", TONE_CLASS[f.tone])}>{f.text}</p>
                        ) : (
                          <button
                            type="button" onClick={() => c()?.selectFromList(f.selectId)}
                            className={cn("w-full break-words rounded-md border px-2 py-1.5 text-left hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", TONE_CLASS[f.tone])}
                          >
                            {f.text}
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                {model.gate.enabled && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    On the model, red marks a placement note and amber a size note. The bed outline turns orange for a placement note.
                    Studio keeps a {Number(model.marginMm.toFixed(2))} mm margin inside the bed edge.
                  </p>
                )}
              </section>

              {model.limitations.length > 0 && (
                <section aria-labelledby="scene-limits">
                  <h4 id="scene-limits" className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">What this view cannot tell you</h4>
                  <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                    {model.limitations.map((t) => <li key={t}>{t}</li>)}
                  </ul>
                </section>
              )}
              {model.partial && (
                <p className="text-xs text-muted-foreground">Studio could not learn everything it needs from this file, so the view may be incomplete.</p>
              )}
            </div>
          )}
        </div>
        <div className="space-y-1 text-xs text-muted-foreground">
          <p>Review placement and supports in Snapmaker Orca.</p>
          <p>3D view: {SLICERX_CREDIT}</p>
          <details>
            <summary className="cursor-pointer rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Licenses for the 3D view</summary>
            <div className="mt-2 space-y-3">
              {CREDIT_SECTIONS.map((s) => (
                <section key={s.title} aria-label={s.title}>
                  <h4 className="font-semibold">{s.title}</h4>
                  <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded border border-border p-2 text-[11px]">{s.text}</pre>
                </section>
              ))}
            </div>
          </details>
        </div>
      </CardContent>
    </Card>
  );
}
