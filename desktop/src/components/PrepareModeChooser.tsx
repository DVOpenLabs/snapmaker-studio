import type { PrepareMode } from "@/api";
import { Card, CardContent } from "@/components/ui/card";

interface Props {
  mode: PrepareMode;
  onModeChange: (mode: PrepareMode) => void;
  onCustom: () => void;
  previewing?: boolean;
  blocked?: boolean;
}

export function PrepareModeChooser({ mode, onModeChange, onCustom, previewing = false, blocked = false }: Props) {
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div>
          <h3 className="text-sm font-semibold">Preparation mode</h3>
          <p className="mt-1 text-xs text-muted-foreground">{blocked ? "Review the original in Snapmaker Orca first. Studio cannot prepare this project." : "Studio will make a U1 profile copy; review in Orca before slicing."}</p>
        </div>
        <label className="flex cursor-pointer items-start gap-2 rounded-md border p-3">
          <input type="radio" name="prepare-mode" checked={mode === "preserve"} onChange={() => onModeChange("preserve")} disabled={blocked} />
          <span><span className="flex flex-wrap items-center gap-1.5 text-sm font-medium">Preserve creator settings<span className="rounded-full bg-primary/15 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-primary">Recommended</span></span><span className="block text-xs text-muted-foreground">Keeps the print looking the way the creator intended — the right choice for a downloaded model. Studio changes only the minimum needed for Snapmaker Orca to open it.</span></span>
        </label>
        <label className="flex cursor-pointer items-start gap-2 rounded-md border p-3">
          <input type="radio" name="prepare-mode" checked={mode === "recommended"} onChange={() => onModeChange("recommended")} disabled={blocked} />
          <span><span className="block text-sm font-medium">Use Studio&apos;s U1 starter settings instead</span><span className="block text-xs text-muted-foreground">Replaces the creator&apos;s print settings with Studio&apos;s U1 defaults — useful when the file was made for a very different printer. Speed, temperature, retraction, supports and cooling will change.</span></span>
        </label>
        <div className="flex items-center justify-between rounded-md border p-3">
          <span><span className="block text-sm font-medium">Custom</span><span className="block text-xs text-muted-foreground">Review settings before preparing.</span></span>
          <button type="button" className="text-sm font-medium text-primary hover:underline" onClick={onCustom} disabled={previewing || blocked}>{previewing ? "Reviewing…" : "Review settings"}</button>
        </div>
      </CardContent>
    </Card>
  );
}
