import type { AccessoryForm } from "@/components/setups/AccessorySetupFields";

export type SetupDraft = { host: string; port: string; accessory: AccessoryForm };
const drafts = new Map<string, SetupDraft>();
function copy(value: SetupDraft): SetupDraft {
  const a = value.accessory;
  return { host: value.host, port: value.port, accessory: { adapter: a.adapter, mode: a.mode, host: a.host, port: a.port,
    snapshot: a.snapshot, mapping: a.mapping, snapshotKind: a.snapshotKind } };
}
/** Inputs only, in memory for at most eight projects. No key, report, topology, browser storage or network. */
export function saveSetupDraft(projectPath: string, value: SetupDraft): boolean {
  if (projectPath.length > 4096 || value.host.length > 2048 || value.port.length > 8 || value.accessory.host.length > 2048 ||
      value.accessory.port.length > 8 || value.accessory.snapshot.length > 256 * 1024 || value.accessory.mapping.length > 8192) {
    drafts.delete(projectPath); return false;
  }
  drafts.delete(projectPath); drafts.set(projectPath, copy(value));
  if (drafts.size > 8) drafts.delete(drafts.keys().next().value!);
  return true;
}
export function readSetupDraft(projectPath: string): SetupDraft | undefined {
  const value = drafts.get(projectPath); return value ? copy(value) : undefined;
}
export function forgetSetupDraft(projectPath: string): void { drafts.delete(projectPath); }
