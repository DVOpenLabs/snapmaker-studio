import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Move, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useToast } from "@/store/toast";
import { placementCheck, preparePlaced } from "@/api";
import type { PlacementCheck, PlacementFix } from "@/api";
import { blockedReason, overhangText, placementVerdict } from "@/lib/placement";

/**
 * Where the objects actually sit.
 *
 * A project made for another printer carries its objects at that printer's
 * coordinates. A small part can be well within the U1's size limits and still
 * land off the plate — every size check passes and Snapmaker Orca just says
 * "out of bounds". This card names the object, the edge and the millimetres,
 * and offers a fix that writes a new copy.
 */
export function PlacementCard({ path }: { path: string }) {
  const showToast = useToast((s) => s.show);
  const [check, setCheck] = useState<PlacementCheck | null>(null);
  const [failed, setFailed] = useState(false);
  const [fixing, setFixing] = useState(false);
  const [fix, setFix] = useState<PlacementFix | null>(null);

  useEffect(() => {
    let alive = true;
    setCheck(null);
    setFix(null);
    setFailed(false);
    placementCheck(path).then(
      (r) => { if (alive) setCheck(r); },
      () => { if (alive) setFailed(true); },
    );
    return () => { alive = false; };
  }, [path]);

  // A failed check must not block the page around it; the other Doctors on this
  // route still have something to say.
  if (failed) return null;

  const runFix = async () => {
    setFixing(true);
    try {
      const result = await preparePlaced(path);
      setFix(result);
      showToast(result.ok
        ? `Saved a repositioned copy — ${result.output_name}`
        : "Studio did not move anything — see the reason on the card.");
      if (result.ok) setCheck(result.after ?? check);
    } catch {
      showToast("Couldn't reposition this project — open it in Snapmaker Orca and use Arrange.");
    } finally {
      setFixing(false);
    }
  };

  return <PlacementView check={check} fix={fix} fixing={fixing} onFix={runFix} />;
}

/** What the card shows for a given check. Separate from the fetching so it can be rendered on its own. */
export function PlacementView({ check, fix, fixing, onFix }: {
  check: PlacementCheck | null;
  fix: PlacementFix | null;
  fixing: boolean;
  onFix: () => void;
}) {
  const showToast = useToast((s) => s.show);
  const verdict = placementVerdict(check);
  const blocked = blockedReason(check);

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          {verdict.tone === "ok" ? (
            <CheckCircle2 className="h-4 w-4 text-ready" aria-hidden="true" />
          ) : verdict.tone === "unknown" ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <AlertTriangle className="h-4 w-4 text-risk" aria-hidden="true" />
          )}
          Object placement
        </h3>

        <p className="text-sm text-muted-foreground">{verdict.headline}</p>

        {check?.available && check.off_plate.length > 0 && (
          <ul className="space-y-1.5">
            {check.off_plate.map((item) => (
              <li key={item.object_id} className="rounded-md border border-risk/40 p-2.5">
                <p className="text-xs font-medium">
                  Object {item.object_id} · {item.dimensions.x} × {item.dimensions.y} ×{" "}
                  {item.dimensions.z} mm
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">{overhangText(item)}</p>
              </li>
            ))}
          </ul>
        )}

        {blocked && (
          <p className="rounded-md border border-border bg-muted/20 p-2.5 text-xs text-muted-foreground">
            {blocked} Open the project in Snapmaker Orca and use Arrange.
          </p>
        )}

        {verdict.canFix && !fix?.ok && (
          <div className="space-y-1.5">
            <Button size="sm" onClick={onFix} disabled={fixing}>
              {fixing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Move className="h-3.5 w-3.5" />}
              {fixing ? "Repositioning…" : "Move onto the plate (saves a copy)"}
            </Button>
            <p className="text-[11px] text-muted-foreground">
              Studio writes a new file and leaves your original alone. Layout, rotation,
              scale and height stay exactly as the creator set them.
            </p>
          </div>
        )}

        {fix && !fix.ok && (
          <p className="text-xs text-risk">{fix.reason}</p>
        )}

        {fix?.ok && (
          <div className="space-y-1.5 rounded-md border border-ready/40 bg-ready/5 p-2.5">
            <p className="text-xs font-medium">{fix.summary}</p>
            {fix.changes?.map((change) => (
              <p key={change.what} className="text-[11px] text-muted-foreground">
                {change.detail} {change.kept}
              </p>
            ))}
            {fix.output_path && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  navigator.clipboard?.writeText(fix.output_path as string);
                  showToast("Copied the new file's location.");
                }}
              >
                <Copy className="h-3.5 w-3.5" /> Copy file location
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
