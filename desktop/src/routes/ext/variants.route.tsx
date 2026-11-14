import { useState, type ReactNode } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { GitCompareArrows } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/layout";
import { compareVariants, type VariantOutput, type VariantReport } from "@/lib/variantsApi";

const filters = [{ name: "Sliced outputs", extensions: ["3mf", "gcode", "g", "gco"] }];

function StatusValue({ status, children }: { status: string; children: ReactNode }) {
  return <span><span className="font-medium">{children}</span> <span className="text-xs text-muted-foreground">({status})</span></span>;
}

function OutputCard({ output, name }: { output: VariantOutput; name: string }) {
  return <Card>
    <CardHeader><CardTitle>{name} <span className="text-sm font-normal text-muted-foreground">· {output.format.toUpperCase()}</span></CardTitle>
      <p className="text-xs text-muted-foreground">Artifact {output.artifact.artifact_id.slice(0, 20)}… · {output.freshness}</p>
    </CardHeader>
    <CardContent className="space-y-2 text-sm">
      <p><StatusValue status={output.tools_used.status}>{output.tools_used.value?.map((tool) => "T" + tool).join(", ") || "Unknown"}</StatusValue></p>
      <p><StatusValue status={output.tool_changes.status}>{output.tool_changes.value ?? "Unknown"}</StatusValue> tool changes</p>
      <p>Material use: {output.grams_by_tool.length ? output.grams_by_tool.map((row) =>
        "Tool " + row.logical_tool + ": " + row.grams + " g (" + row.basis + ")").join("; ") : "Unknown"}</p>
      <p><StatusValue status={output.time.status}>{output.time.value === null ? "Unknown" : Math.round(output.time.value / 60) + " min"}</StatusValue> estimated time</p>
      <p><StatusValue status={output.waste.status}>{output.waste.value ?? "Unknown"}</StatusValue> tower/waste</p>
    </CardContent>
  </Card>;
}

function VariantsView() {
  const [files, setFiles] = useState<[string | null, string | null]>([null, null]);
  const [result, setResult] = useState<VariantReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  function setPath(index: 0 | 1, value: string | null) {
    setFiles((current) => { const next = [...current] as [string | null, string | null]; next[index] = value; return next; });
    setResult(null);
  }
  async function choose(index: 0 | 1) {
    try {
      const picked = await open({ multiple: false, filters });
      if (typeof picked === "string") setPath(index, picked);
    } catch { setError("The file picker is not available here. Type the file path instead."); }
  }
  async function compare() {
    if (!files[0] || !files[1]) return;
    setBusy(true); setError(null); setResult(null);
    try { setResult(await compareVariants({ outputs: [{ path: files[0] }, { path: files[1] }] })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "The comparison could not be computed."); }
    finally { setBusy(false); }
  }
  return <main className="space-y-5 p-6">
    <PageHeader icon={GitCompareArrows} title="Variant comparison" subtitle="Compare two sliced outputs side by side. Studio reads local files and reports advisory evidence; it does not slice." />
    <div className="grid gap-3 md:grid-cols-2">
      {([0, 1] as const).map((index) => <Card key={index}><CardHeader><CardTitle>Output {index + 1}</CardTitle></CardHeader>
        <CardContent className="space-y-2"><Button variant="secondary" onClick={() => void choose(index)}>Choose 3MF or G-code</Button>
          <input aria-label={`Output ${index + 1} path`} className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm" placeholder="or type a local file path"
            value={files[index] ?? ""} onChange={(event) => setPath(index, event.target.value.trim() || null)} />
          <p className="truncate text-sm text-muted-foreground">{files[index] ? files[index]!.split(/[\\/]/).pop() : "No file selected"}</p>
        </CardContent></Card>)}
    </div>
    <Button disabled={busy || !files[0] || !files[1]} onClick={() => void compare()}>{busy ? "Comparing…" : "Compare outputs"}</Button>
    {error && <p className="text-sm text-risk" role="alert">{error}</p>}
    {result && <>
      {result.stale && <p className="rounded-md border border-repairable p-3 text-sm" role="status">A selected file changed during inspection. Its comparison is stale; reselect the file to refresh it.</p>}
      <div className="grid gap-3 md:grid-cols-2"><OutputCard output={result.outputs[0]} name="Output 1" /><OutputCard output={result.outputs[1]} name="Output 2" /></div>
      <Card><CardHeader><CardTitle>Settings differences</CardTitle></CardHeader><CardContent>
        {result.settings_diff.length ? <ul className="space-y-1 text-sm">{result.settings_diff.map((change) =>
          <li key={change.key}><span className="font-medium">{change.key}</span>: {String(change.old ?? "—")} → {String(change.new ?? "—")}</li>)}</ul>
          : <p className="text-sm text-muted-foreground">No readable settings differences.</p>}
      </CardContent></Card>
      <p className="text-xs text-muted-foreground">{result.advisory}</p>
    </>}
  </main>;
}

export default { path: "/variants", Component: VariantsView };
