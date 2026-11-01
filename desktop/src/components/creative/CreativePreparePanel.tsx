import type { ReactNode } from "react";
import { comparisonBuckets, type CreativePrepareResponse, type CreativeVerification } from "@/lib/creativeApi";

function Box({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="space-y-1 rounded-lg border border-border bg-card p-4">
      <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
      {children}
    </section>
  );
}

/** Members kept, changed, dropped and added between the original and the new copy, by part name and content hash. */
export function ExportVerification({ verification, lossNotes }: { verification: CreativeVerification; lossNotes: string[] }) {
  if (!verification.opens_as_zip) {
    return <Box title="Export verification"><p className="text-sm text-risk" role="alert">The exported file could not be re-read: {verification.problem ?? "unknown problem"}. Nothing can be said about what it kept.</p></Box>;
  }
  const paint = verification.per_face_paint;
  return (
    <Box title="Export verification" note={`The new file opens as a 3MF archive with ${verification.members?.length ?? 0} parts. This compares part names and content fingerprints only; it does not show how the copy slices or prints.`}>
      <div className="grid gap-3 md:grid-cols-4">
        {comparisonBuckets(verification).map((b) => (
          <div key={b.key} aria-label={b.title}>
            <p className="text-xs font-medium">{b.title} ({b.items.length})</p>
            <p className="text-xs text-muted-foreground">{b.note}</p>
            {b.items.length === 0
              ? <p className="text-xs text-muted-foreground">None.</p>
              : <ul className="list-disc pl-5 break-all font-mono text-xs">{b.items.map((i) => <li key={i}>{i}</li>)}</ul>}
          </div>
        ))}
      </div>
      {paint && paint.original_triangles !== null && paint.exported_triangles !== null && (
        <p className="text-xs">Per-face paint: {paint.original_triangles} painted triangle(s) in the original, {paint.exported_triangles} in the copy.</p>
      )}
      {verification.settings && (
        <p className="text-xs">Project settings: {verification.settings.removed_keys.length} removed, {verification.settings.changed_keys.length} changed, {verification.settings.added_key_count} added.</p>
      )}
      <ul className="list-disc pl-5 text-xs text-muted-foreground">{lossNotes.map((n) => <li key={n}>{n}</li>)}</ul>
    </Box>
  );
}

/** Result of "Prepare a U1 copy": either an explanation of why nothing was written, or the verified new file. */
export default function CreativePreparePanel({ result }: { result: CreativePrepareResponse }) {
  if (!result.prepared) {
    const r = result.refusal;
    return (
      <section className="space-y-2 rounded-lg border border-border bg-card p-4" aria-label="Prepare refusal">
        <h3 className="text-sm font-semibold tracking-tight">No copy was written</h3>
        <p className="text-sm"><span className="font-medium">What Studio saw.</span> {r.seen}</p>
        <p className="text-sm"><span className="font-medium">What is not supported.</span> {r.not_supported}</p>
        <div className="text-sm"><span className="font-medium">What to do.</span>
          <ul className="list-disc pl-5">{r.what_to_do.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
        {r.problems && r.problems.length > 0 && (
          <div className="text-xs"><p className="font-medium">What the check found</p>
            <ul className="list-disc pl-5 font-mono">{r.problems.map((p) => <li key={p}>{p}</li>)}</ul>
          </div>
        )}
        <p className="text-xs text-muted-foreground">{result.advisory}</p>
      </section>
    );
  }
  const unchanged = result.original.original_unchanged;
  return (
    <div className="space-y-4" aria-label="Prepare result">
      <Box title="A new file was written" note={result.advisory}>
        <p className="text-sm">Copy: <span className="font-mono text-xs">{result.output.name}</span></p>
        <p className="text-xs text-muted-foreground">Saved in: {result.output.location_label}.{result.output.in_source_folder ? " This is the same folder as the original, because you chose it." : " It is not next to the original."}</p>
        <p className="text-xs text-muted-foreground">Review it in Snapmaker Orca before slicing. Studio does not slice.</p>
      </Box>
      <ExportVerification verification={result.verification} lossNotes={result.loss_notes} />
      <div className="rounded-lg border border-border bg-card p-4 text-xs">
        <p>{unchanged
          ? "Original unchanged: its fingerprint is identical before and after Prepare."
          : "The original's fingerprint differs between the two reads. Something outside Studio changed the file while it was being prepared."}</p>
        <p className="mt-1 font-mono text-muted-foreground">{result.original.name}. before {result.original.sha256_before.slice(0, 16)}, after {result.original.sha256_after.slice(0, 16)}</p>
      </div>
    </div>
  );
}
