import { useState } from "react";
import { Button } from "@/components/ui/button";
import { usePrinter } from "@/store/printer";
import { isPrinterSetUp, normalizeHost } from "@/lib/printerSetup";

/** The one place Settings sets or removes the printer address. Typing only edits a draft: Studio looks
 *  the printer up only after Save, so a half-typed name is never queried. */
export default function PrinterAddress() {
  const saved = usePrinter((s) => s.host);
  const setHost = usePrinter((s) => s.setHost);
  const [draft, setDraft] = useState(saved);
  const setUp = isPrinterSetUp(saved);
  const dirty = normalizeHost(draft) !== saved;
  const save = () => { if (normalizeHost(draft)) setHost(draft); };
  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex items-center gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") save(); }}
          placeholder="U1.local"
          aria-label="Printer network name or IP"
          className="h-9 w-40 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
        />
        <Button size="sm" variant="secondary" disabled={!dirty || !normalizeHost(draft)} onClick={save}>
          {setUp ? "Save" : "Save and connect"}
        </Button>
        {setUp && (
          <Button size="sm" variant="ghost" onClick={() => { setHost(""); setDraft(""); }}>Remove</Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground" role="status">
        {setUp ? `Set up: ${saved}` : "Not set up. Studio does not look for a printer until you save one."}
      </p>
    </div>
  );
}
