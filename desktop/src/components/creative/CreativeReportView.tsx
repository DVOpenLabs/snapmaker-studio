import type { ReactNode } from "react";
import { originSentence, type CreativeInspectResponse } from "@/lib/creativeApi";

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
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-card p-4">
        <p className="text-sm font-medium">{originSentence(report.origin)}</p>
        <p className="mt-1 text-xs text-muted-foreground">{report.advisory}</p>
        <p className="mt-1 text-xs text-muted-foreground">Evidence: fixture-tested. The readers are tested against hand-written files shaped like the published formats, not against captured projects.</p>
      </div>
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
