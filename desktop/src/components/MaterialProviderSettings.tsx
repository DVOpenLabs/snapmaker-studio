import { useEffect, useRef, useState } from "react";
import { Boxes, CheckCircle2, Loader2, AlertTriangle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { providerTest, type ProviderSpool, type ProviderTest } from "@/api";
import { useProvider, PROVIDERS, type ProviderKind } from "@/store/provider";
import LocalSpoolSettings from "@/components/LocalSpoolSettings";

// Where a person tells Studio what is keeping track of their filament.
//
// The engine has been able to read Spoolman for several releases and nothing in
// the app ever sent it an address, so the capability was real and unreachable.
// This is the missing half, and it is deliberately small: pick a provider, type
// the address of the machine it runs on, press Test, say which spool is in which
// slot. No account, no cloud, no scanning the network.
//
// A second provider was added without adding a second page, which is the point:
// choosing one swaps a label and a placeholder, and nothing else on this screen
// or after it knows the difference.
//
// The one genuinely confusing thing is slot numbering — a person counts the
// slots on a printer as 1, 2, 3, 4 while the G-code counts them 0, 1, 2, 3 — so
// it is asked rather than guessed. Guessing it puts every spool one slot out and
// then reports the wrong material with complete confidence.

const SLOTS = [0, 1, 2, 3];

function quality(spool: ProviderSpool): string {
  if (spool.remaining_g === null || spool.remaining_g === undefined) return "no weight recorded";
  const amount = `${Math.round(spool.remaining_g)} g`;
  // Both providers answer with a remaining weight for every spool, computed from
  // the spool's declared size. Only a spool something has printed from — or has
  // been weighed — carries a figure anything is actually keeping, so the two are
  // labelled apart here as well as in the engine.
  return spool.remaining_quality === "tracked" ? `${amount} tracked` : `${amount} estimated`;
}

export default function MaterialProviderSettings() {
  const { kind, url, key, keyEpoch, slotMap, slotBase, lastSeen, setKind, setUrl, setKey, setSlot, setSlotBase, markSeen } =
    useProvider();
  const [draft, setDraft] = useState(url);
  const [keyDraft, setKeyDraft] = useState(key);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ProviderTest | null>(null);
  const seqRef = useRef(0);
  const firstEpoch = useRef(keyEpoch);

  function invalidate() { seqRef.current += 1; setBusy(false); }

  useEffect(() => {
    if (keyEpoch !== firstEpoch.current) {
      setKeyDraft("");
      invalidate();
    }
  }, [keyEpoch]);

  useEffect(() => { if (key === "") setKeyDraft(""); }, [key]);
  useEffect(() => { setResult(null); }, [kind]);

  async function test() {
    const seq = ++seqRef.current;
    setBusy(true);
    setResult(null);
    try {
      const value = draft.trim();
      setUrl(value);
      const committedKey = kind === "spoolease" ? keyDraft : "";
      if (kind === "spoolease") setKey(committedKey);
      const out = await providerTest(value, kind, committedKey !== "" ? committedKey : undefined);
      if (seq !== seqRef.current) return;
      setResult(out);
      if (out.ok) markSeen();
    } catch (e) {
      if (seq !== seqRef.current) return;
      setResult({ ok: false, spools: 0, reason: e instanceof Error ? e.message : String(e), error_code: undefined, with_weight: 0 });
    } finally {
      if (seq === seqRef.current) setBusy(false);
    }
  }

  const spools = result?.choices ?? [];

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div>
          <p className="flex items-center gap-2 text-sm font-semibold">
            <Boxes className="h-4 w-4" /> Materials provider
          </p>
          <p className="pt-1 text-xs text-muted-foreground">
            A printer knows which spool is loaded and nothing about how much is left on it.
            If something on your network tracks that, Studio can read it — and then tell you
            whether a job will actually finish. Optional: without it, Studio says it does not
            know, which is the honest answer on a stock setup.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {(["none", "spoolman", "bambuddy", "spoolease"] as ProviderKind[]).map((option) => (
            <Button
              key={option}
              size="sm"
              variant={kind === option ? "primary" : "secondary"}
              onClick={() => {
                setKind(option);
                // The address belongs to the provider that was selected, and the
                // store has just cleared it. The box has to follow, or it shows
                // an address that is no longer configured.
                if (option !== kind) {
                  setDraft("");
                  setKeyDraft("");
                  setResult(null);
                  invalidate();
                }
              }}
            >
              {option === "none" ? "None" : PROVIDERS[option].label}
            </Button>
          ))}
        </div>

        {kind !== "none" && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={draft}
                onChange={(e) => { setDraft(e.target.value); invalidate(); }}
                onKeyDown={(e) => e.key === "Enter" && test()}
                placeholder={PROVIDERS[kind].placeholder}
                className="h-9 min-w-[220px] flex-1 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
              />
              {kind === "spoolease" && (
                <input
                  value={keyDraft}
                  type="password"
                  aria-label="Security key"
                  onChange={(e) => { setKeyDraft(e.target.value); invalidate(); }}
                  onBlur={() => setKey(keyDraft)}
                  placeholder="Security key"
                  className="h-9 min-w-[180px] flex-1 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                />
              )}
              <Button size="sm" onClick={test} disabled={busy || !draft.trim()}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Test connection
              </Button>
            </div>
            <p className="text-[11px] text-muted-foreground">
              {PROVIDERS[kind].blurb} Give the address of the machine it runs on, on your own
              network. Studio reads it and never writes to it, and it makes no requests to the
              internet — an address that is not on your network is refused, and so is a local
              address that redirects to one.
            </p>

            {result && (
              <div
                className={`flex items-start gap-2 rounded-md border p-3 text-xs ${
                  result.ok ? "border-ready/40 bg-ready/5" : "border-border"
                }`}
              >
                {result.ok ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ready" />
                ) : (
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                )}
                <span>{result.ok
                  ? `Connected. ${result.spools} spools. ${result.with_weight ?? 0} with usable remaining weight.`
                  : result.reason}</span>
              </div>
            )}

            {lastSeen && (
              <p className="text-[11px] text-muted-foreground opacity-70">
                Last read {new Date(lastSeen).toLocaleString()}.
              </p>
            )}

            <div className="space-y-2 border-t border-border pt-3">
              <p className="text-xs font-medium">Which spool is in which slot</p>
              <p className="text-[11px] text-muted-foreground">
                {PROVIDERS[kind].label} does not know where a spool is — you do. Pick the numbering that
                matches the labels on your printer, then say what is loaded. Studio never
                treats this as something the printer confirmed; on a machine that reports its
                own filament, the machine wins.
              </p>
              <div className="flex items-center gap-2 text-xs">
                <span className="text-muted-foreground">My slots are numbered</span>
                {([1, 0] as const).map((base) => (
                  <Button
                    key={base}
                    size="sm"
                    variant={slotBase === base ? "primary" : "secondary"}
                    onClick={() => setSlotBase(base)}
                  >
                    {base === 1 ? "1 – 4" : "0 – 3"}
                  </Button>
                ))}
              </div>

              {spools.length === 0 ? (
                <p className="text-[11px] text-muted-foreground">
                  Test the connection to load the list of spools.
                </p>
              ) : (
                <ul className="space-y-1">
                  {SLOTS.map((index) => {
                    const key = String(index + slotBase);
                    const chosen = slotMap[key];
                    return (
                      <li key={key} className="flex items-center gap-2 text-xs">
                        <span className="w-16 shrink-0 text-muted-foreground">Slot {key}</span>
                        <select
                          value={chosen ?? ""}
                          onChange={(e) =>
                            setSlot(key, e.target.value === "" ? null : (spools.find((spool) => String(spool.id) === e.target.value)?.id ?? null))
                          }
                          className="h-8 flex-1 rounded-md border border-border bg-card px-2 text-xs outline-none"
                        >
                          <option value="">— nothing mapped —</option>
                          {spools.map((spool) => (
                            <option key={spool.id} value={spool.id}>
                              {spool.label} · {quality(spool)}
                              {spool.archived ? " · archived" : ""}
                            </option>
                          ))}
                        </select>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        )}

        <LocalSpoolSettings />
      </CardContent>
    </Card>
  );
}
