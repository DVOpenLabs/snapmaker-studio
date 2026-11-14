import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AssemblyReport, SpoolRef, TileReport, Verdict } from "./types";

export const VERDICT_LABEL: Record<Verdict, string> = {
  enough: "Looks enough",
  shortage: "Shortage",
  stale: "Reading too old",
  unknown: "Unknown",
};
const VERDICT_CLASS: Record<Verdict, string> = {
  enough: "bg-ready/10 text-ready",
  shortage: "bg-risk/10 text-risk",
  stale: "bg-repairable/10 text-repairable",
  unknown: "bg-muted text-muted-foreground",
};
const LIBRARY_LABEL: Record<TileReport["library"]["status"], string> = {
  linked: "Matches library", changed: "Library file changed", missing: "Missing from library",
  unverified: "Not compared", unlinked: "No library project",
};
const UNRESOLVED_TEXT: Record<string, string> = {
  no_role: "has no role, so its spool is not known",
  ambiguous_role: "serves more than one role, so its spool is not known",
  no_binding: "serves a role with no spool chosen",
};

export function spoolLabel(ref: SpoolRef): string {
  return `${ref.provider_instance_id} / ${ref.provider_spool_id}`;
}

function grams(value: number | null): string {
  return value === null ? "not stated" : `${value} g`;
}

/** Pure presentation of an assembly report: per-tile need, shared-spool verdicts and everything unknown. */
export default function AssemblyReportView({ report }: { report: AssemblyReport }) {
  return (
    <div className="space-y-4" data-testid="assembly-report">
      <div className="flex flex-wrap items-center gap-2">
        <Badge className={VERDICT_CLASS[report.verdict]} data-testid="overall-verdict">{VERDICT_LABEL[report.verdict]}</Badge>
        <span className="text-sm text-muted-foreground" role="note">{report.advisory}</span>
      </div>

      <Card>
        <CardHeader><CardTitle>Shared spools</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {report.spools.length === 0 && <p className="text-sm text-muted-foreground">No tile slot is tied to a spool yet, so no spool can be checked.</p>}
          {report.spools.map((s) => (
            <div key={spoolLabel(s.spool)} className="rounded-md border border-border p-3 text-sm" data-testid="spool-row">
              <div className="flex flex-wrap items-center gap-2">
                <Badge className={VERDICT_CLASS[s.verdict]}>{VERDICT_LABEL[s.verdict]}</Badge>
                <span className="font-medium">{spoolLabel(s.spool)}</span>
                <span className="text-muted-foreground">for {s.roles.join(", ")}</span>
              </div>
              <p className="mt-1">Tiles state {s.need_known_g} g{s.need_complete ? "" : " or more"}; the spool has {grams(s.remaining_g)} left.</p>
              <p className="text-muted-foreground">{s.reason}</p>
              {s.starving_tiles.length > 0 && <p data-testid="starving">Tiles that run short: {s.starving_tiles.join(", ")}. Short by {s.shortfall_g} g.</p>}
              {s.unknown_tiles.length > 0 && <p data-testid="unknown-tiles">Tiles with no stated grams for this spool: {s.unknown_tiles.join(", ")}.</p>}
            </div>
          ))}
          {report.unresolved.length > 0 && (
            <ul className="list-disc pl-5 text-sm text-muted-foreground" aria-label="Slots with no known spool" data-testid="unresolved">
              {report.unresolved.map((u) => (
                <li key={`${u.tile_id}-${u.slot}`}>{u.tile_id} {u.slot} ({grams(u.grams)}) {UNRESOLVED_TEXT[u.reason] ?? "has no known spool"}.</li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Tiles</CardTitle></CardHeader>
        <CardContent>
          <table className="w-full text-left text-sm" aria-label="Per-tile need">
            <thead>
              <tr className="text-muted-foreground"><th className="py-1 pr-3">Tile</th><th className="pr-3">Plate</th><th className="pr-3">Need</th><th className="pr-3">Scale</th><th>Library</th></tr>
            </thead>
            <tbody>
              {report.tiles.map((t) => (
                <tr key={t.tile_id} className="border-t border-border" data-testid="tile-row">
                  <td className="py-1 pr-3">{t.name}</td>
                  <td className="pr-3">{t.plate ?? "-"}</td>
                  <td className="pr-3">{t.need_known_g} g{t.need_complete ? "" : ` (not stated for ${t.unknown_slots.length ? t.unknown_slots.join(", ") : "any slot"})`}</td>
                  <td className="pr-3">{t.scale === null ? "not stated" : `${t.scale}%`}</td>
                  <td>{LIBRARY_LABEL[t.library.status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Roles, parts and seams</CardTitle></CardHeader>
        <CardContent className="space-y-1.5 text-sm">
          {report.roles.map((r) => (
            <p key={r.role}>
              <span className="font-medium">{r.role}</span>: {r.tiles.length} tile{r.tiles.length === 1 ? "" : "s"} on plate{r.plates.length === 1 ? "" : "s"} {r.plates.join(", ") || "-"}
              {r.shared_across_plates ? " (shared across plates)" : ""}{r.spool ? "" : "; no spool chosen"}.
            </p>
          ))}
          {report.parts.missing.length > 0 && (
            <p data-testid="missing-parts">Parts with no tile: {report.parts.missing.map((p) => p.name).join(", ")}.</p>
          )}
          <p data-testid="seam-scale">
            {report.seam_scale.status === "consistent" && "Seam scale: every tile states the same scale."}
            {report.seam_scale.status === "mismatch" && `Seam scale differs between tiles: ${report.seam_scale.known.map((k) => `${k.tile_id} ${k.scale}%`).join(", ")}.`}
            {report.seam_scale.status === "unknown" && `Seam scale: not stated for ${report.seam_scale.unknown.join(", ")}.`}
          </p>
          {report.attribution.length > 0 && (
            <p data-testid="attribution">Attribution kept: {report.attribution.map((a) => [a.item, a.author, a.license].filter(Boolean).join(", ")).join("; ")}.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
