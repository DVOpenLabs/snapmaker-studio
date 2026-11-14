import type { ReactNode } from "react";
import { factLines, GENERATOR_LABEL, originSentence, type CreativeInspectResponse } from "@/lib/creativeApi";

function Section({ title, note, children }: { title: string; note: string; children: ReactNode }) {
  return (
    <section className="space-y-1 rounded-lg border border-border bg-card p-4">
      <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
      <p className="text-xs text-muted-foreground">{note}</p>
      {children}
    </section>
  );
}

function NameList({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return <ul className="list-disc space-y-0.5 pl-5 font-mono text-xs">{items.map((i) => <li key={i}>{i}</li>)}</ul>;
}

/** What Studio read from one project file: understood, kept untouched, could not interpret. Advisory only. */
export default function CreativeReportView({ report }: { report: CreativeInspectResponse }) {
  const { source } = report;
  const facts = Object.values(report.facts ?? {}).flatMap((f) => factLines(f));
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-card p-4">
        <p className="text-sm font-medium">{originSentence(report.origin)}</p>
        <p className="mt-1 text-xs text-muted-foreground">{report.advisory}</p>
        <p className="mt-1 text-xs text-muted-foreground">Evidence: fixture-tested. The readers are tested against hand-written files shaped like the published formats, not against captured projects.</p>
      </div>
      {report.explanation && (
        <section className="space-y-2 rounded-lg border border-border bg-card p-4" aria-label="Why the origin is not decided">
          <h3 className="text-sm font-semibold tracking-tight">{report.explanation.kind === "ambiguous_origin" ? "Studio cannot tell which tool wrote this" : "Studio does not recognise this file's tool"}</h3>
          <p className="text-sm"><span className="font-medium">What Studio saw.</span> {report.explanation.seen}</p>
          <p className="text-sm"><span className="font-medium">What is not supported.</span> {report.explanation.not_supported}</p>
          <div className="text-sm"><span className="font-medium">What to do.</span>
            <ul className="list-disc pl-5">{report.explanation.what_to_do.map((w) => <li key={w}>{w}</li>)}</ul>
          </div>
        </section>
      )}
      {facts.length > 0 && (
        <Section title="What Studio read" note="Facts read directly from the file, nothing inferred.">
          {Object.entries(report.facts ?? {}).map(([gen, f]) => (
            <div key={gen} className="space-y-0.5">
              {Object.keys(report.facts ?? {}).length > 1 && <p className="text-xs font-medium">{GENERATOR_LABEL[gen] ?? gen}</p>}
              <ul className="list-disc space-y-0.5 pl-5 text-sm">{factLines(f).map((l) => <li key={l}>{l}</li>)}</ul>
            </div>
          ))}
        </Section>
      )}
      {(report.format_info ?? []).map((info) => (
        <Section key={info.key} title={`${info.label}: what is and is not read`} note={info.selection === "manual only" ? "This format has no identifying marker, so it is read only when you choose it." : `Identified by: ${info.identified_by.join("; ")}`}>
          <div className="grid gap-3 md:grid-cols-2">
            <div><p className="text-xs font-medium">Read</p><NameList items={info.reads} empty="Nothing." /></div>
            <div><p className="text-xs font-medium">Not read</p><NameList items={info.not_read} empty="Nothing listed." /></div>
          </div>
        </Section>
      ))}
      <div className="grid gap-4 lg:grid-cols-3">
        <Section title="Understood" note="Settings Studio read and can name.">
          <NameList items={report.understood} empty="Nothing in this file matched a documented setting." />
        </Section>
        <Section title="Kept untouched" note="Parts and settings Studio carries by name and fingerprint without interpreting them.">
          <NameList items={report.passed_through.map((p) => `${p.name} (${p.sha256.slice(0, 8)})`)} empty="Nothing else in this file." />
        </Section>
        <Section title="Could not interpret" note="Present or expected, but Studio does not know what it means.">
          <NameList items={[...report.could_not_interpret, ...report.missing.map((m) => `${m} (expected, not found)`),
            ...report.diagnostics.map((d) => `note: ${d}`)]} empty="Nothing was left uninterpreted." />
        </Section>
      </div>
      <Section title="Simulated recipes" note="Mixed-colour rows read from the project. They are a description only; Studio does not run them.">
        {report.recipes.length === 0 ? <p className="text-sm text-muted-foreground">No recipes in this file.</p> : (
          <ul className="space-y-1 text-sm">
            {report.recipes.map((r) => (
              <li key={r.recipe_id}>
                <span className="font-mono text-xs">{r.recipe_id}</span>: {r.components.length} source slots
                {" "}(ratios not stated). Simulated{r.execution_supported === false ? "; execution not supported" : ""}.
              </li>
            ))}
          </ul>
        )}
        {report.physical_slots_needed !== null && (
          <p className="text-xs text-muted-foreground">Distinct project slots referenced: {report.physical_slots_needed}. This is not a statement about your loaded filament.</p>
        )}
      </Section>
      <div className="rounded-lg border border-border bg-card p-4 text-xs">
        <p>
          {source.unchanged
            ? "Original unchanged: the file fingerprint is identical before and after inspection."
            : "The file fingerprint differs between the two reads. Something outside Studio changed the file while it was being inspected."}
        </p>
        <p className="mt-1 font-mono text-muted-foreground">
          {source.name}, {source.size_bytes} bytes. before {source.sha256_before.slice(0, 16)}, after {source.sha256_after.slice(0, 16)}
        </p>
      </div>
    </div>
  );
}
