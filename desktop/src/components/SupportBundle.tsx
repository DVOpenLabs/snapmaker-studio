import { useState } from "react";
import { LifeBuoy, ShieldCheck } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { diagnosticsBuild, diagnosticsPreview } from "@/api";
import type { DiagnosticsPreview } from "@/api";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";
import { usePrinter } from "@/store/printer";

/**
 * A support bundle the user reads before it exists as a file.
 *
 * Studio asks people to report when it gets an analysis wrong, which is only
 * useful with the facts behind it. Gathering those by hand is exactly the work a
 * beginner will not do — so Studio gathers them, redacts anything that
 * identifies a person or a machine, and shows the result first.
 *
 * Nothing is ever sent from Studio. This writes a file; sending it is a separate
 * decision the user makes elsewhere.
 */
export function SupportBundle() {
  const project = useSession((s) => s.file);
  const sliced = useSliced((s) => s.path);
  const host = usePrinter((s) => s.host);
  const [preview, setPreview] = useState<DiagnosticsPreview | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const opts = {
    projectPath: project?.path,
    gcodePath: sliced ?? undefined,
    host: host || undefined,
  };

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <LifeBuoy className="h-4 w-4" aria-hidden="true" />
            Reporting something Studio got wrong
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            A bug report is far more useful with the facts behind it. This gathers them
            for you.
          </p>
        </div>

        <p className="flex items-start gap-2 rounded-md border border-border bg-muted/20 p-2.5 text-xs text-muted-foreground">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            Your username, home folder, file paths, machine name and printer address are
            replaced before the bundle is assembled — and you can read the whole thing
            before it is written. <strong>Studio never sends it anywhere.</strong>
          </span>
        </p>

        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              setError(null);
              diagnosticsPreview(opts)
                .then((p) => { setPreview(p); setSaved(null); })
                .catch(() => setError("Studio could not gather the diagnostics."))
                .finally(() => setBusy(false));
            }}
          >
            Show me what it contains
          </Button>
          <Button
            disabled={busy}
            onClick={() => {
              setBusy(true);
              setError(null);
              diagnosticsBuild(opts)
                .then((b) => setSaved(b.path))
                .catch(() => setError("Studio could not write the bundle."))
                .finally(() => setBusy(false));
            }}
          >
            Save it to a file
          </Button>
        </div>

        {error && <p className="text-xs text-risk">{error}</p>}

        {saved && (
          <p className="text-xs">
            Saved to <code className="break-all">{saved}</code>. Attach it to a report at{" "}
            <span className="text-muted-foreground">
              github.com/DVOpenLabs/snapmaker-studio/issues
            </span>
            .
          </p>
        )}

        {preview && (
          <details open className="rounded-md border border-border">
            <summary className="cursor-pointer p-2.5 text-xs">
              {preview.sections.length} section(s), {Math.max(1, Math.round(preview.bytes / 1024))} KB
              — read it before you send it
            </summary>
            <pre className="max-h-80 overflow-auto border-t border-border p-2.5 text-[10px] leading-relaxed">
              {preview.text}
            </pre>
          </details>
        )}
      </CardContent>
    </Card>
  );
}
