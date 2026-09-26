import { useEffect, useState } from "react";
import { Download, RefreshCw, ShieldCheck } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { checkForUpdate, getUpdateCheckPref, setAutoCheckUpdates } from "@/api";
import type { UpdateInfo } from "@/api";
import { useUpdateCheckStore } from "@/store/updateCheck";

/**
 * Checking for a newer release.
 *
 * Studio is local-first, and this is the one exception: a request to GitHub's
 * releases API asking which release is newest. It sends nothing but the request
 * itself — no identifiers, no usage, no telemetry — and Studio never downloads or
 * installs anything on its own; the answer is always just a version number and a
 * link. By default that request only happens when someone presses the button
 * below. The checkbox is the one way to make it happen without pressing
 * anything — off by default, and never more than once a day even when it is on.
 */
export function UpdateCheck() {
  // A manual "Check GitHub now" result overrides whatever the automatic
  // check found, for as long as this page stays open — pressing the button
  // is the more direct, more recent answer. Read directly at render time
  // (not synced through an effect into its own state) so a result the
  // automatic check already found, before this page was ever opened, shows
  // up immediately rather than only after a render nothing triggers.
  const [manualInfo, setManualInfo] = useState<UpdateInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoCheck, setAutoCheck] = useState(false);
  const [autoPrefLoaded, setAutoPrefLoaded] = useState(false);
  // The automatic check runs once per launch, from App's own startup effect
  // — not from this component — so it genuinely happens whether or not this
  // page is ever opened. The result lands in this shared store.
  const autoResult = useUpdateCheckStore((s) => s.autoResult);
  const info = manualInfo ?? autoResult;

  useEffect(() => {
    getUpdateCheckPref()
      .then((pref) => setAutoCheck(pref.auto_check))
      .catch(() => {})
      .finally(() => setAutoPrefLoaded(true));
  }, []);

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} aria-hidden="true" />
            Check for a newer version
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Studio never updates itself — checking only ever tells you a version
            number and a link.
          </p>
        </div>

        <p className="flex items-start gap-2 rounded-md border border-border bg-muted/20 p-2.5 text-xs text-muted-foreground">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            Pressing the button, or turning on the checkbox below, makes one
            request to GitHub asking which release is newest. It sends nothing
            about you or your files.
          </span>
        </p>

        <label className="flex items-start gap-2 text-xs">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={autoCheck}
            disabled={!autoPrefLoaded}
            onChange={(e) => {
              const enabled = e.target.checked;
              setAutoCheck(enabled);
              setAutoCheckUpdates(enabled).catch(() => setAutoCheck(!enabled));
            }}
          />
          <span>
            Automatically check for updates
            <span className="block text-muted-foreground">
              Once a day at most, and only a version check — Studio still never
              downloads or installs anything, and this stays off until you turn
              it on.
            </span>
          </span>
        </label>

        <Button
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setError(null);
            checkForUpdate()
              .then(setManualInfo)
              .catch((e) => setError(String(e)))
              .finally(() => setBusy(false));
          }}
        >
          Check GitHub now
        </Button>

        {error && (
          <p className="text-xs text-risk">
            Studio could not reach GitHub. You are offline, or it is unavailable —
            nothing is wrong with your installation.
          </p>
        )}

        {info && !error && (
          info.newer ? (
            <div className="rounded-md border border-ready/40 p-2.5">
              <p className="text-sm font-medium">
                Version {info.latest} is available — you have {info.current}.
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Download it yourself and install over the top; your settings and
                library are kept.
              </p>
              <a
                className="mt-2 inline-flex items-center gap-1.5 text-xs underline"
                href={info.url}
                target="_blank"
                rel="noreferrer"
              >
                <Download className="h-3.5 w-3.5" aria-hidden="true" />
                Open the release page
              </a>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              You have {info.current}, which is the newest release.
            </p>
          )
        )}
      </CardContent>
    </Card>
  );
}
