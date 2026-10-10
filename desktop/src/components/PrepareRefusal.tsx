/** Why Prepare did not produce a copy. The plain sentence is the message; the engine's raw technical wording, when it
 *  sent any, sits in a collapsed secondary area so a bug report can still quote it. */
export function PrepareRefusal({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error ?? "");
  const details = (error as { details?: unknown } | null)?.details;
  return (
    <div role="alert" data-testid="prepare-refusal">
      <p className="text-sm text-risk">Couldn't prepare a copy: {message}</p>
      {typeof details === "string" && details ? (
        <details className="mt-1 text-xs text-muted-foreground">
          <summary className="cursor-pointer">Technical details</summary>
          <p className="mt-1 break-words" data-testid="prepare-refusal-details">{details}</p>
        </details>
      ) : null}
    </div>
  );
}
