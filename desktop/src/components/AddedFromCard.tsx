import { useNavigate } from "react-router-dom";
import { CheckCircle2, ShieldCheck, Wand2, FolderOpen, X } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useSession } from "@/store/session";
import { useModelDownloads } from "@/store/modelDownloads";
import type { AddedItem } from "@/lib/modelDownloads";

/** Presentational card: "Added from <site>", the file, what Studio detected, and the next step. */
export function AddedFromView({
  item, onCheck, onPrepare, onOpen, onDismiss,
}: {
  item: AddedItem;
  onCheck: () => void;
  onPrepare: () => void;
  onOpen: () => void;
  onDismiss: () => void;
}) {
  return (
    <Card>
      <CardContent className="space-y-2 p-4" data-testid="added-from-card">
        <div className="flex items-start justify-between gap-2">
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden /> {item.heading}
          </p>
          <button type="button" aria-label={`Dismiss ${item.name}`} onClick={onDismiss}
            className="text-muted-foreground hover:text-foreground"><X className="h-4 w-4" aria-hidden /></button>
        </div>
        <p className="truncate text-sm" title={item.name}>{item.name}</p>
        {item.facts.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {item.facts.map((f, i) => <li key={i}>{f}</li>)}
          </ul>
        )}
        <div className="flex flex-wrap gap-2 pt-1">
          <Button size="sm" variant={item.needsPrepare ? "secondary" : "primary"} onClick={onCheck}>
            <ShieldCheck className="h-4 w-4" aria-hidden /> Check for U1
          </Button>
          <Button size="sm" variant={item.needsPrepare ? "primary" : "secondary"} onClick={onPrepare}>
            <Wand2 className="h-4 w-4" aria-hidden /> Prepare
          </Button>
          <Button size="sm" variant="secondary" onClick={onOpen}>
            <FolderOpen className="h-4 w-4" aria-hidden /> Open project
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/** Wired card: loads the file into the session (which runs the existing analysis) and navigates. */
export function AddedFromCard({ item }: { item: AddedItem }) {
  const nav = useNavigate();
  const setFile = useSession((s) => s.setFile);
  const dismiss = useModelDownloads((s) => s.dismiss);
  const go = (route: string) => () => { setFile(item.path); nav(route); };
  return (
    <AddedFromView
      item={item}
      onCheck={go("/doctor/project")}
      onPrepare={go("/compatibility")}
      onOpen={go("/workspace")}
      onDismiss={() => dismiss(item.path)}
    />
  );
}
