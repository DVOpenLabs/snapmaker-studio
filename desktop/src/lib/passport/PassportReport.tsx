import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ChainState, PassportDocument, Verification } from "./types";
import { BYTES_LABEL, CHAIN_LABEL, chainSummary, derivationText, lossText, reasonText, roleLabel, shortSha } from "./view";

const CHAIN_CLASS: Record<ChainState, string> = {
  intact: "bg-ready/10 text-ready", invalidated: "bg-risk/10 text-risk", unverified: "bg-muted text-muted-foreground",
};

/** Pure presentation of a passport and its verification. No state, no network, no storage. */
export default function PassportReport({ passport, verification }: { passport: PassportDocument; verification: Verification }) {
  const losses = verification.losses;
  return (
    <div className="space-y-4" data-testid="passport-report">
      <p className="text-sm" role="status" data-testid="chain-summary">{chainSummary(verification.artifacts)}</p>
      <Card>
        <CardHeader>
          <CardTitle>Files in this passport</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">Passport {passport.passport_id}</p>
        </CardHeader>
        <CardContent>
          <ol className="space-y-3" aria-label="Derivation chain">
            {verification.artifacts.map((a) => (
              <li key={a.artifact_id} className="rounded-md border border-border p-3" data-testid={`artifact-${a.role}`}>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium">{roleLabel(a.role)}</span>
                  <span>{a.name}</span>
                  <Badge className={CHAIN_CLASS[a.chain]}>{CHAIN_LABEL[a.chain]}</Badge>
                  <Badge>{BYTES_LABEL[a.bytes]}</Badge>
                  <span className="text-xs text-muted-foreground">{a.size_bytes} bytes, sha256 {shortSha(a.sha256)}</span>
                </div>
                {a.reasons.length > 0 && (
                  <ul className="mt-1 list-disc pl-5 text-sm text-muted-foreground">
                    {a.reasons.map((r, i) => <li key={`${r.code}-${i}`}>{reasonText(r)}</li>)}
                  </ul>
                )}
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>
      {verification.derivations.length > 0 && (
        <Card>
          <CardHeader><CardTitle>How each file was derived</CardTitle></CardHeader>
          <CardContent>
            <ul className="space-y-1.5 text-sm" aria-label="Derivations">
              {verification.derivations.map((d) => (
                <li key={d.derivation_id} className="flex flex-wrap items-start gap-2" data-testid="derivation">
                  <Badge className={CHAIN_CLASS[d.status]}>{CHAIN_LABEL[d.status]}</Badge>
                  {d.declared_mismatch === true && <Badge className="bg-risk/10 text-risk">Declared parent differs</Badge>}
                  <span>{derivationText(d)}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader><CardTitle>Recipes and material mappings</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p data-testid="retained">
            Kept: {verification.recipes_retained.length} recipe(s), {verification.material_mappings_retained.length} material mapping(s).
          </p>
          {losses.length > 0 ? (
            <ul className="list-disc pl-5 text-muted-foreground" aria-label="Not carried over" data-testid="losses">
              {losses.map((l, i) => <li key={`${l.kind}-${l.id}-${i}`}>{lossText(l)}</li>)}
            </ul>
          ) : <p className="text-muted-foreground">Nothing was left out.</p>}
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">
        {verification.note} This is an advisory check of file contents, not a statement about how a print will turn out.
      </p>
    </div>
  );
}
