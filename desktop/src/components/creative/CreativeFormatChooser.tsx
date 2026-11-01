import { CREATIVE_FORMATS, GENERATOR_LABEL, type CreativeFormat, type CreativeFormatInfo } from "@/lib/creativeApi";

const field = "h-9 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50";

/** Format choice. When detection could not decide, the person picks one and is told plainly what is read for it. */
export default function CreativeFormatChooser({ value, onChange, formats, needsChoice }: {
  value: CreativeFormat;
  onChange: (f: CreativeFormat) => void;
  formats: CreativeFormatInfo[];
  needsChoice: boolean;
}) {
  const info = formats.find((f) => f.key === value);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <select className={field} aria-label="Project format" value={value} onChange={(e) => onChange(e.target.value as CreativeFormat)}>
          {CREATIVE_FORMATS.map((f) => <option key={f} value={f}>{f === "auto" ? "Detect from markers and settings" : (GENERATOR_LABEL[f] ?? f)}</option>)}
        </select>
        {needsChoice && value === "auto" && (
          <p className="text-sm text-risk" role="status">Studio could not decide the tool. Choose the format you know this file came from, then inspect again.</p>
        )}
      </div>
      {info && (
        <div className="rounded-lg border border-border bg-card p-3 text-xs" aria-label="Format coverage">
          <p className="font-medium">{info.label}: {info.selection === "manual only" ? "read only when you choose it" : "identified automatically only when its markers are present in the file"}.</p>
          <p className="mt-1 text-muted-foreground">Carrier: {info.carrier}.</p>
          <div className="mt-1 grid gap-2 md:grid-cols-2">
            <div>
              <p className="font-medium">Studio reads</p>
              <ul className="list-disc pl-5">{info.reads.map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
            <div>
              <p className="font-medium">Studio does not read</p>
              <ul className="list-disc pl-5">{info.not_read.map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
          </div>
          {info.identified_by.length === 0 && (
            <p className="mt-1 text-muted-foreground">This format leaves no identifying marker in the file, so Studio cannot confirm the file really came from this tool.</p>
          )}
        </div>
      )}
      {value === "auto" && !needsChoice && (
        <p className="text-xs text-muted-foreground">Studio does not guess the tool: when the markers and settings do not identify it, the origin is reported as unknown.</p>
      )}
    </div>
  );
}
