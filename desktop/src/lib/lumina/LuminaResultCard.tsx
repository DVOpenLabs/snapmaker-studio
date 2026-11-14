import type { LuminaGenerateResponse, LuminaStatusResponse } from "./luminaApi";

/** The generated file, by name only. Studio shows no folder path: the label says which folder. */
export function LuminaResultCard({ result }: { result: LuminaGenerateResponse }) {
  return (
    <div className="space-y-2 rounded-lg border border-border bg-card p-4 text-sm" aria-label="Generated file">
      <p className="font-medium">A new {result.kind} file was saved</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt className="text-muted-foreground">File name</dt><dd className="break-all font-mono text-xs">{result.file_name}</dd>
        <dt className="text-muted-foreground">Kind</dt><dd>{result.kind}</dd>
        <dt className="text-muted-foreground">Size</dt><dd>{result.size_bytes} bytes</dd>
        <dt className="text-muted-foreground">SHA-256</dt><dd className="break-all font-mono text-xs">{result.sha256}</dd>
        <dt className="text-muted-foreground">Saved in</dt><dd>{result.location_label}</dd>
        <dt className="text-muted-foreground">Made by</dt><dd>{result.generated_by}</dd>
        <dt className="text-muted-foreground">Progress and cancel</dt><dd>Unknown: the service does not publish a route Studio can rely on.</dd>
      </dl>
      <p className="text-xs text-muted-foreground">{result.advisory}</p>
      <p className="text-xs text-muted-foreground">Your original image was not changed. Studio does not slice this file; open it in your slicer to review it.</p>
    </div>
  );
}

/** What the identity check said, kept to what was actually read. */
export function LuminaStatusNote({ status }: { status: LuminaStatusResponse }) {
  if (status.status === "ok") {
    return (
      <div className="rounded-lg border border-border bg-card p-3 text-sm" role="status" aria-label="Service check">
        <p className="font-medium">The service answered Studio's identity check (API version {status.api_version ?? "unknown"}).</p>
        <p className="text-xs text-muted-foreground">
          {status.can_generate ? "It offers the routes Studio uses." : "It does not offer every route Studio uses."} {status.note}
        </p>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-border bg-card p-3 text-sm" role="status" aria-label="Service check">
      <p className="font-medium">Unknown: Studio could not confirm this service.</p>
      <p className="text-xs text-muted-foreground">{status.message}</p>
    </div>
  );
}
