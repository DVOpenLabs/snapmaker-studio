import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ListChecks, Loader2, RotateCw, AlertTriangle, Printer as PrinterIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader, EmptyState } from "@/components/ui/layout";
import { readyNowStart, readyNowStatus } from "@/api";
import type { ReadyNowProject } from "@/api";
import { ReadyNowSections } from "@/components/ReadyNowSections";
import ProviderStatusNote from "@/components/ProviderStatusNote";
import { useSession } from "@/store/session";
import { usePrinter } from "@/store/printer";
import { useProvider, providerArgs } from "@/store/provider";
import {
  READY_NOW_TITLE, READY_NOW_FOOTER, DECLARED_NOTE, NO_PRINTER_TITLE, NO_PRINTER_TEXT,
  summarySentence, progressText,
} from "@/lib/readyNow";

export default function ReadyNow() {
  const nav = useNavigate();
  const setFile = useSession((s) => s.setFile);
  const host = usePrinter((s) => s.host);
  const provider = useProvider();
  const hasPrinter = host.trim() !== "";
  const [jobId, setJobId] = useState<string | null>(null);
  const autoStarted = useRef(false);

  // The provider key lives in memory only and is sent with this one request; it is
  // never part of a query key, never stored, and never shown.
  const start = useMutation({
    mutationFn: () => readyNowStart(host, providerArgs(provider)),
    onSuccess: (r) => setJobId(r.job_id),
  });

  const job = useQuery({
    queryKey: ["ready-now", jobId],
    enabled: jobId !== null,
    queryFn: () => readyNowStatus(jobId as string),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 700 : false),
  });

  // Start once on opening the page, and only when there is a printer to ask.
  useEffect(() => {
    if (hasPrinter && !autoStarted.current) {
      autoStarted.current = true;
      start.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasPrinter]);

  const data = job.data;
  const running = start.isPending || (jobId !== null && (data === undefined || data.status === "running"));
  const result = data?.result ?? null;
  const results = result?.results ?? [];
  const failed = start.isError || job.isError || data?.status === "error";

  const open = (r: ReadyNowProject) => { setFile(r.path); nav("/workspace"); };
  const prepare = (r: ReadyNowProject) => { setFile(r.path); nav("/compatibility"); };

  return (
    <div className="space-y-6">
      <PageHeader
        icon={ListChecks}
        title={READY_NOW_TITLE}
        subtitle={summarySentence(result, running)}
        actions={
          <Button size="sm" variant="secondary" disabled={!hasPrinter || running} onClick={() => start.mutate()}>
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />} Check my library
          </Button>
        }
      />

      {!hasPrinter && (
        <Card><CardContent className="p-0">
          <EmptyState icon={PrinterIcon} title={NO_PRINTER_TITLE} description={NO_PRINTER_TEXT}
            action={<Button size="sm" onClick={() => nav("/printers")}>Open Printer Hub</Button>} />
        </CardContent></Card>
      )}

      {running && (
        <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> {progressText(data?.progress)}
        </p>
      )}

      {failed && (
        <Card><CardContent className="flex flex-col items-center gap-2 py-10 text-center">
          <AlertTriangle className="h-7 w-7" aria-hidden="true" />
          <p className="font-medium">Couldn't check your library</p>
          <p className="text-sm text-muted-foreground">Try again in a moment.</p>
        </CardContent></Card>
      )}

      {result && result.printer && !result.printer.reachable && (
        <p className="rounded-md border border-border p-2.5 text-xs text-muted-foreground">
          Studio could not reach your printer. Projects for another printer can still be sorted into
          "Needs preparation"; nothing else can be judged until the printer answers.
        </p>
      )}
      <ProviderStatusNote status={result?.provider_status} />

      {results.length > 0 && <ReadyNowSections results={results} onOpen={open} onPrepare={prepare} />}

      {hasPrinter && data?.status === "done" && results.length === 0 && (
        <Card><CardContent className="p-0">
          <EmptyState icon={ListChecks} title="Nothing to check yet"
            description="Projects you open or prepare in Studio appear in your library, and then here." />
        </CardContent></Card>
      )}

      <footer className="space-y-1 border-t border-border pt-3 text-xs text-muted-foreground">
        <p>{READY_NOW_FOOTER}</p>
        <p>{DECLARED_NOTE}</p>
      </footer>
    </div>
  );
}
