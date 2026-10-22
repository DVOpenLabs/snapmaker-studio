import type { SettingsChange, SettingsSummary } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { settingNote } from "@/lib/settingNotes";
import { evidenceKindLabel } from "@/lib/evidenceKind";

function value(value: unknown) {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return (text ?? String(value)).slice(0, 80);
}

function Changes({ changes, explain = false }: { changes: SettingsChange[]; explain?: boolean }) {
  return (
    <ul className="space-y-1 text-xs text-muted-foreground">
      {changes.map((change) => {
        const note = explain ? settingNote(change) : null;
        return (
          <li key={change.key} className="space-y-0.5">
            <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] gap-1"><span className="truncate font-mono">{change.key}</span><span>:</span><span className="truncate">{value(change.old)} → {value(change.new)}</span></div>
            {note && <p className="pl-2 leading-snug">{note.kind && <strong>{evidenceKindLabel(note.kind)}</strong>}{note.kind && note.source ? ` — ${note.source}. ` : note.kind ? ". " : note.source ? `${note.source}. ` : ""}{note.note}</p>}
          </li>
        );
      })}
    </ul>
  );
}

function compatibilitySummary(changes: SettingsChange[]) {
  const remaining = new Set(changes);
  const take = (matches: (change: SettingsChange) => boolean) => {
    let found = false;
    for (const change of changes) {
      if (remaining.has(change) && matches(change)) {
        remaining.delete(change);
        found = true;
      }
    }
    return found;
  };
  const bullets: string[] = [];
  if (take((change) => /(identity|printer|compatible_printers)/i.test(change.key))) bullets.push("Printer identity changed to Snapmaker U1");
  const gcodeChanges = changes.filter((change) => remaining.has(change) && /gcode/i.test(change.key));
  if (gcodeChanges.length > 0) {
    gcodeChanges.forEach((change) => remaining.delete(change));
    const hasStart = gcodeChanges.some((change) => /start.*gcode|gcode.*start/i.test(change.key));
    const hasEnd = gcodeChanges.some((change) => /end.*gcode|gcode.*end/i.test(change.key));
    const hasUnspecified = gcodeChanges.some((change) => !/start.*gcode|gcode.*start|end.*gcode|gcode.*end/i.test(change.key));
    bullets.push(hasUnspecified || (hasStart && hasEnd)
      ? "U1 machine start/end G-code applied"
      : hasStart ? "U1 machine start G-code applied" : "U1 machine end G-code applied");
  }
  if (take((change) => /(filament|toolhead)/i.test(change.key) && (Array.isArray(change.old) || Array.isArray(change.new)))) bullets.push("Toolhead / filament list mapped to U1 layout");
  return { bullets, unmatched: [...remaining] };
}

function recommendationSummary(changes: SettingsChange[]) {
  const examples = new Set<string>();
  for (const change of changes) {
    if (/wipe_tower.*wall|tower.*wall/i.test(change.key)) examples.add("tower wall type");
    else if (/wipe_tower.*(?:x|y|position|placement)|tower.*(?:x|y|position|placement)/i.test(change.key)) examples.add("tower placement");
  }
  const count = `${changes.length} optional recommendation${changes.length === 1 ? "" : "s"} available`;
  return examples.size > 0 ? `${count}, including ${[...examples].join(" and ")}.` : `${count}.`;
}

export const STARTER_SETTINGS_NOTE = "Studio's U1 starter settings replace the creator's print settings, and Snapmaker Orca uses the U1 preset for any value the file does not declare as changed. Not every setting listed here will be in effect.";

export const STARTER_NOTICE = "This STL does not include creator slicer settings. Studio will use a U1 starter profile unless you choose another Orca profile.";

interface Props {
  summary: SettingsSummary;
  mode: "preserve" | "recommended" | "starter";
  preview?: boolean;
  onPreparePreserve?: () => void;
  onPrepareRecommended?: () => void;
  isStl?: boolean;
}

export function PrepareSettingsSummary({ summary, mode, preview = false, onPreparePreserve, onPrepareRecommended, isStl = false }: Props) {
  if (mode === "starter" || !summary.source_has_creator_settings) {
    const notice = isStl ? STARTER_NOTICE : "This file does not include creator slicer settings. Studio will use a U1 starter profile unless you choose another Orca profile.";
    return <Card><CardContent className="space-y-2 p-4 text-sm text-muted-foreground"><p>{notice}</p>{summary.warnings.length > 0 && <section><h3 className="text-sm font-semibold">Warnings</h3><ul className="mt-1 space-y-1 text-xs">{summary.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></section>}</CardContent></Card>;
  }
  const mappedToU1 = summary.mapped_to_u1 ?? [];
  const hasMappedTemperatures = mappedToU1.some((change) => change.key.startsWith("nozzle_temperature"));
  const compat = compatibilitySummary(summary.compat_changed);
  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        {preview && <p className="text-sm font-medium">Settings preview</p>}
        {summary.supports_note && <section role="note"><h3 className="text-sm font-semibold">Supports</h3><p className="text-xs text-muted-foreground">{summary.supports_note}</p></section>}
        {(summary.kept_count > 0 || mappedToU1.length > 0) && <section><h3 className="text-sm font-semibold">{mode === "recommended" ? "Still written in the file" : "Kept from the original file"}</h3>{mode === "recommended" ? <><p className="text-xs text-muted-foreground">{summary.kept_count} creator settings are written in the file</p><p className="mt-1 text-xs text-muted-foreground">{STARTER_SETTINGS_NOTE}</p></> : <><p className="text-xs text-muted-foreground">{summary.kept_count} creator settings kept</p><p className="mt-1 text-xs text-muted-foreground">These settings are kept from the original file.</p></>}{hasMappedTemperatures && <p className="mt-1 text-xs text-muted-foreground">Creator temperature values were preserved and mapped to the U1 toolhead layout.</p>}{mappedToU1.length > 0 && <>{!hasMappedTemperatures && <p className="mt-1 text-xs text-muted-foreground">Creator values preserved and mapped to the U1 toolhead layout.</p>}<details className="mt-2 text-xs text-muted-foreground"><summary className="cursor-pointer font-medium">Technical detail</summary><div className="mt-1"><Changes changes={mappedToU1} /></div></details></>}</section>}
        {summary.compat_changed.length > 0 && <section><h3 className="text-sm font-semibold">Adjusted for U1 project compatibility</h3><p className="mb-1 text-xs text-muted-foreground">{mode === "recommended" ? "These settings were replaced by Studio's U1 starter settings or changed for U1 compatibility." : "These settings changed only for U1 compatibility."}</p><ul className="space-y-1 text-xs text-muted-foreground">{compat.bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}</ul>{compat.unmatched.length > 0 && <div className="mt-2"><Changes changes={compat.unmatched} explain /></div>}<details className="mt-2 text-xs text-muted-foreground"><summary className="cursor-pointer font-medium">Technical detail</summary><div className="mt-1"><Changes changes={summary.compat_changed} explain /></div></details></section>}
        {summary.could_not_carry.length > 0 && <section><h3 className="text-sm font-semibold">Could not carry over</h3><ul className="space-y-1 text-xs text-muted-foreground">{summary.could_not_carry.map((item) => <li key={item.key}><span className="font-mono">{item.key}</span>: {item.reason}</li>)}</ul></section>}
        {mode === "preserve" && summary.recommendations_available && summary.recommended_changes.length > 0 && <section className="space-y-2"><h3 className="text-sm font-semibold">Optional recommendations (not applied)</h3><p className="text-xs text-muted-foreground">These optional recommendations are not applied unless you choose them.</p><p className="text-xs text-muted-foreground">{recommendationSummary(summary.recommended_changes)}</p><details className="text-xs text-muted-foreground"><summary className="cursor-pointer font-medium">Technical detail</summary><div className="mt-1"><Changes changes={summary.recommended_changes} /></div></details>{onPrepareRecommended && <Button size="sm" variant="secondary" onClick={onPrepareRecommended}>Prepare another copy with recommended settings</Button>}</section>}
        {preview && <div className="flex flex-wrap gap-2">{onPreparePreserve && <Button size="sm" onClick={onPreparePreserve}>Prepare with preserved settings</Button>}{onPrepareRecommended && <Button size="sm" variant="secondary" onClick={onPrepareRecommended}>Prepare with recommended settings</Button>}</div>}
        {summary.warnings.length > 0 && <section><h3 className="text-sm font-semibold">Warnings</h3><ul className="mt-1 space-y-1 text-xs text-muted-foreground">{summary.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></section>}
      </CardContent>
    </Card>
  );
}
