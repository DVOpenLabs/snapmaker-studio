import { useEffect, useRef, useSyncExternalStore } from "react";
import { AlertTriangle, Loader2, Wrench } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { usePrinter } from "@/store/printer";
import { displayHost } from "@/lib/host";
import {
  countMismatchNote, nozzleActionsVisible, nozzleRows, rowCountLabel, showsNothingReportedBanner,
  type NozzleRow,
} from "@/lib/nozzleRows";
import { createNozzleSettingsController } from "@/lib/nozzleSettingsController";
import { settingsNozzleFetchTrigger } from "@/lib/nozzleFetchTriggers";

const CHOICES = [0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8] as const;
const NOT_SURE = "not_sure";
const PORT = 7125;

/** Pure presentational rendering of the Toolhead|Nozzle|Source|Status table —
 *  exported so its states (reported live, confirmed, unknown, conflict,
 *  out-of-range) can be exercised directly in tests without needing the
 *  surrounding fetch effect to have run. */
export function NozzleTable({
  rows, draftFor = () => "", onDraftChange = () => {}, onUpdateToPrinter = () => {},
  onRemoveNote = () => {}, busy = false,
}: {
  rows: NozzleRow[];
  draftFor?: (toolhead0: number) => string;
  onDraftChange?: (toolhead0: number, value: string) => void;
  onUpdateToPrinter?: (toolhead1: number, value: number) => void;
  onRemoveNote?: (toolhead1: number) => void;
  /** R4-D4: every mutation control is serialised — Update/Remove included. */
  busy?: boolean;
}) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-muted-foreground">
          <th className="py-1 pr-2 font-normal">Toolhead</th>
          <th className="py-1 pr-2 font-normal">Nozzle</th>
          <th className="py-1 pr-2 font-normal">Source</th>
          <th className="py-1 font-normal">Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const readOnly = row.status === "reported_live";
          return (
            <tr key={row.toolhead} className="border-t border-border">
              <td className="py-1.5 pr-2">Toolhead {row.toolhead}</td>
              <td className="py-1.5 pr-2">
                {readOnly ? (
                  row.diameterLabel
                ) : (
                  <select
                    aria-label={`Nozzle size for toolhead ${row.toolhead}`}
                    value={draftFor(row.toolhead - 1)}
                    onChange={(e) => onDraftChange(row.toolhead - 1, e.target.value)}
                    className="h-7 rounded-md border border-border bg-card px-1 text-xs outline-none"
                  >
                    <option value="">— pick —</option>
                    {CHOICES.map((c) => (
                      <option key={c} value={c}>{c} mm</option>
                    ))}
                    <option value={NOT_SURE}>Not sure</option>
                  </select>
                )}
              </td>
              <td className="py-1.5 pr-2 text-muted-foreground">{row.sourceLabel}</td>
              <td className="py-1.5">
                <span className={row.status === "conflict" ? "text-risk" : "text-muted-foreground"}>
                  {row.statusLabel}
                </span>
                {row.updateLabel && (
                  <Button
                    size="sm" variant="ghost" className="ml-1" disabled={busy}
                    onClick={() => {
                      const value = Number(row.diameterLabel.replace(" mm", ""));
                      if (Number.isFinite(value)) onUpdateToPrinter(row.toolhead, value);
                    }}
                  >
                    {row.updateLabel}
                  </Button>
                )}
                {row.removeLabel && (
                  <Button
                    size="sm" variant="ghost" className="ml-1" disabled={busy}
                    onClick={() => onRemoveNote(row.toolhead)}
                  >
                    {row.removeLabel}
                  </Button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** "Nozzles · for <host>" — a per-printer confirmation of what is fitted, only
 *  ever used to fill a gap the printer itself does not report. The printer's
 *  own live reading always wins; this never overrides it (plan D-6, A1.6).
 *
 *  Freshness within this component is entirely owned by its own controller
 *  (lib/nozzleSettingsController.ts) — a monotonic request token, not a
 *  shared cross-component floor (that machinery was deleted in the round-3
 *  re-diagnosis after three review rounds kept finding races in it). This
 *  component does NOT subscribe to the global nozzleNotesVersion counter
 *  (F5/A2): it already owns and refetches its own data on every host change
 *  and applies its own mutation responses directly, so nothing else needs to
 *  tell it to refetch. */
export default function PrinterNozzleSettings() {
  const host = usePrinter((s) => s.host);
  const canonical = displayHost(host);
  const controller = useRef(createNozzleSettingsController()).current;
  const state = useSyncExternalStore(controller.subscribe, controller.getState, controller.getState);

  useEffect(() => {
    controller.start(host, PORT);
    return () => controller.unmount();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, settingsNozzleFetchTrigger(host));

  const { status, checkingLive, loadError, errorMessage, busy, draft, liveCheckFailed } = state;
  const rows = nozzleRows(status);
  const rowCount = rowCountLabel(status);
  const mismatch = countMismatchNote(status);
  // The backend now always returns a row per known toolhead, even with the
  // printer offline (profile count). The banner is informational and sits
  // above the table — it never replaces the editable rows (D4).
  const showNothingReportedBanner = showsNothingReportedBanner(status);
  // v1.2.0 release polish: Save/Remove all have nothing to do when every row
  // is a plain printer reading with nothing stored underneath it and nothing
  // drafted — hide them rather than offer actions that would be a no-op.
  const showActions = nozzleActionsVisible(status, Object.keys(draft).length > 0);

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div>
          <p className="flex items-center gap-2 text-sm font-semibold">
            <Wrench className="h-4 w-4" aria-hidden="true" /> Nozzles · for {canonical}
          </p>
          <p className="pt-1 text-xs text-muted-foreground">
            Toolhead 1 feeds slot 1 — numbered as printed on the U1.
          </p>
        </div>

        {loadError && (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" /> Couldn't read nozzle status. Try again.
          </p>
        )}

        {status === null && !loadError && (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> Checking your printer…
          </p>
        )}

        {status && checkingLive && (
          <p className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> Checking the printer…
          </p>
        )}

        {liveCheckFailed ? (
          // Opus follow-up (honesty fix): the live-only request itself
          // failed (local service down / network) — the printer was never
          // actually asked, so this must never read as "nothing reported by
          // this printer". The rows still show the save that just succeeded.
          <p className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            Couldn't check the printer just now — these rows show what you have saved, not a live reading.
          </p>
        ) : showNothingReportedBanner && (
          <p className="text-[11px] text-muted-foreground">
            No nozzle size reported by this printer. You can confirm the fitted size yourself.
          </p>
        )}

        {errorMessage && (
          <p className="flex items-center gap-2 rounded-md border border-risk/40 bg-risk/5 p-2 text-[11px] text-risk">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> {errorMessage}
          </p>
        )}

        {status && rows.length > 0 && (
          <>
            {rowCount && (
              <p className="text-[11px] text-muted-foreground">
                {rowCount.count} toolhead{rowCount.count === 1 ? "" : "s"} · {rowCount.sourceLabel}
              </p>
            )}
            {mismatch && (
              <p className="flex items-center gap-2 rounded-md border border-border bg-muted/20 p-2 text-[11px] text-muted-foreground">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> {mismatch}
              </p>
            )}
            <NozzleTable
              rows={rows}
              draftFor={controller.draftFor}
              onDraftChange={controller.setDraft}
              onUpdateToPrinter={(t1, value) => void controller.updateToPrinter(t1, value)}
              onRemoveNote={(t1) => void controller.removeNote(t1)}
              busy={busy}
            />

            {showActions && (
              <div className="flex items-center gap-2 pt-1">
                <Button size="sm" disabled={busy} onClick={() => void controller.saveAll()}>Save</Button>
                <Button size="sm" variant="secondary" disabled={busy} onClick={() => void controller.removeAll()}>Remove all</Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
