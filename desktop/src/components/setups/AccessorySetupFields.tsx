import type { AccessoryInput } from "@/lib/setupsTypes";
import type { Topology } from "@/lib/extTypes";

export type AccessoryForm = { adapter: string; mode: "live" | "snapshot"; host: string; port: string; snapshot: string; mapping: string; snapshotKind: "text" | "json" };
export const EMPTY_ACCESSORY: AccessoryForm = { adapter: "", mode: "live", host: "", port: "", snapshot: "", mapping: "", snapshotKind: "text" };
const versions: Record<string, string> = { multiace: "1", afc: "1", bmcu: "1", sidecar: "beta-preview" };
export function accessoryBody(form: AccessoryForm): AccessoryInput | undefined {
  if (!form.adapter) return undefined;
  const mode = form.adapter === "bmcu" || form.adapter === "sidecar" ? "snapshot" : form.mode;
  const result: AccessoryInput = { adapter_id: form.adapter, source_version: versions[form.adapter], mode };
  if (mode === "live") {
    if (!form.host.trim()) throw new Error("Enter the accessory service host.");
    result.host = form.host.trim();
    if (!form.port.trim()) throw new Error("Enter the accessory service port explicitly.");
    if (form.port.trim()) {
      const p = Number(form.port);
      if (!Number.isInteger(p) || p < 1 || p > 65535) throw new Error("Accessory port must be from 1 to 65535.");
      result.port = p;
    }
  } else {
    if (!form.snapshot.trim()) throw new Error("Paste the accessory snapshot or command text.");
    if (form.snapshot.length > 256 * 1024) throw new Error("Accessory snapshot is too large.");
    result.payload = form.snapshotKind === "json" ? JSON.parse(form.snapshot) : form.adapter === "bmcu" ? { kind: "klipper_text", text: form.snapshot }
      : form.adapter === "sidecar" ? { kind: "gcode", text: form.snapshot } : JSON.parse(form.snapshot);
  }
  const slots = form.mapping.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
  if (slots.length && (form.adapter === "bmcu" || form.adapter === "sidecar")) throw new Error("This contract supplies its own tool mapping. Clear the declared map; device-reported mappings cannot be overridden.");
  if (slots.length) result.slot_map = slots;
  return result;
}

export default function AccessorySetupFields({ value, onChange, disabled, topology }: {
  value: AccessoryForm; onChange: (v: AccessoryForm) => void; disabled?: boolean; topology?: Topology | null;
}) {
  const field = "rounded-md border border-border bg-card px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary/50";
  const snapshot = value.mode === "snapshot" || value.adapter === "bmcu" || value.adapter === "sidecar";
  const declaredMapAllowed = value.adapter === "multiace" || value.adapter === "afc";
  return <section className="space-y-2 rounded-md border border-border p-3" aria-label="Accessory input">
    <label className="block text-sm">Accessory (optional) <select aria-label="Accessory adapter" className={field} value={value.adapter} disabled={disabled} onChange={e => onChange({ ...EMPTY_ACCESSORY, adapter: e.target.value })}>
      <option value="">Host only</option><option value="multiace">multiACE — contract 1</option><option value="afc">AFC — contract 1</option><option value="bmcu">BMCU — command contract 1</option><option value="sidecar">Sidecar — beta preview G-code</option>
    </select></label>
    {value.adapter && <>
      <p className="text-xs text-muted-foreground">Choose the contract explicitly. No accessory is auto-detected. The printer host above is optional physical-head evidence; it is not the accessory address. No control commands are sent.</p>
      {(value.adapter === "multiace" || value.adapter === "afc") && <label className="block text-sm">Input <select aria-label="Accessory input mode" className={field} value={value.mode} disabled={disabled} onChange={e => onChange({ ...value, mode: e.target.value as AccessoryForm["mode"] })}><option value="live">Read service (GET only)</option><option value="snapshot">Import JSON snapshot</option></select></label>}
      {(value.adapter === "bmcu" || value.adapter === "sidecar") && <label className="block text-sm">Snapshot representation <select aria-label="Accessory snapshot representation" className={field} value={value.snapshotKind} disabled={disabled} onChange={e => onChange({ ...value, snapshotKind: e.target.value as AccessoryForm["snapshotKind"] })}><option value="text">Published command/G-code text</option><option value="json">Published reply in a Studio JSON envelope</option></select></label>}
      {snapshot ? <textarea aria-label="Accessory snapshot" className={`${field} min-h-24 w-full font-mono`} value={value.snapshot} disabled={disabled} placeholder={value.adapter === "bmcu" || value.adapter === "sidecar" ? "Paste exported command/G-code text; Studio will not execute it" : "Paste the published response JSON"} onChange={e => onChange({ ...value, snapshot: e.target.value })} />
        : <div className="flex flex-wrap gap-2"><input aria-label="Accessory service host" placeholder="Accessory service host" className={field} value={value.host} disabled={disabled} onChange={e => onChange({ ...value, host: e.target.value })} /><input aria-label="Accessory service port" placeholder="Service port" className={field} value={value.port} disabled={disabled} onChange={e => onChange({ ...value, port: e.target.value })} /></div>}
      <p className="text-xs text-muted-foreground">Imported observations remain historical. Head counts come only from physical inventory. Lane count never creates logical slots.</p>
      {declaredMapAllowed && topology && <div className="text-xs" aria-label="Reported accessory lanes"><p>Reported lanes (copy the desired IDs into the explicit map):</p>{topology.units.flatMap(u => u.lanes).map(l => <p key={l.id} className="break-all font-mono">{l.id}</p>)}</div>}
      {declaredMapAllowed && <label className="block text-sm">Explicit logical slot map (optional)<textarea aria-label="Accessory logical slot map" className={`${field} min-h-20 w-full font-mono`} value={value.mapping} disabled={disabled} placeholder="One reported lane ID per line, in T0, T1, … order. Never inferred." onChange={e => onChange({ ...value, mapping: e.target.value })} /></label>}
      {declaredMapAllowed ? <p className="text-xs text-muted-foreground">Read once to inspect lanes, enter your actual project tool order, then read again. This is your declared mapping, not a device-reported mapping. Missing or contradictory evidence pauses Prepare.</p> : <p className="text-xs text-muted-foreground">This contract supplies its own tool mapping when present. Studio keeps it as reported and does not accept a replacement declared map. Missing evidence remains unknown.</p>}
    </>}
  </section>;
}
