import type { ReceiptFact, ReceiptStatus, ReceiptStage, SettingsReceipt } from "@/api";

/**
 * Plain wording for the settings receipt. The engine decides each status; this only
 * decides how it is said. Nothing here claims a print will work: the receipt is
 * about settings, and says so.
 */
export const STATUS_LABEL: Record<ReceiptStatus, string> = {
  unchanged: "Same",
  changed: "Different",
  missing: "Not stated",
  not_checked: "Not checked",
};

export const STAGE_LABEL: Record<ReceiptStage, string> = {
  original: "Project",
  prepared: "Prepared copy",
  sliced: "Sliced G-code",
};

/** What the files are called when a step is read aloud. */
export function stepTitle(from: ReceiptStage, to: ReceiptStage): string {
  return `${STAGE_LABEL[from]} → ${STAGE_LABEL[to]}`;
}

/** Visual weight only; "missing" and "not checked" are never drawn as a pass. */
export function statusTone(status: ReceiptStatus): "ok" | "attention" | "unknown" {
  if (status === "unchanged") return "ok";
  if (status === "changed") return "attention";
  return "unknown";
}

/**
 * The identity a receipt answers for. A response is shown only while this is still
 * the key of what is open, so an answer about earlier files can never sit beside
 * later ones.
 */
export function receiptKey(original: string, prepared: string | null, sliced: string | null, revision = 0): string {
  return JSON.stringify([original, prepared, sliced, revision]);
}

export type StageCell =
  | { kind: "value"; lines: string[] }
  | { kind: "not_stated" }
  | { kind: "not_checked" }
  | { kind: "not_included" };

const mm = (v: number) => `${v} mm`;

/** One declared value as the lines a person reads. Nozzles keep their tool order: Tool 1 first. */
export function valueLines(fact: ReceiptFact["id"], value: number | boolean | number[]): string[] {
  if (fact === "nozzles") return (Array.isArray(value) ? value : [value as number]).map((v, i) => `Tool ${i + 1}: ${mm(v)}`);
  if (fact === "layer_height") return [mm(Array.isArray(value) ? value[0] : (value as number))];
  return [value ? "On" : "Off"];
}

/**
 * What one file says about one setting. A step that could not be checked never lends its
 * empty values to a file that was read, and a value the file does not state stays "not stated".
 */
export function stageCell(receipt: SettingsReceipt, fact: ReceiptFact, stage: ReceiptStage): StageCell {
  const state = receipt.stages[stage].state;
  if (state === "not_provided") return { kind: "not_included" };
  if (state === "unreadable") return { kind: "not_checked" };
  // A transition that was checked beats one that could not be: it may carry this file's value.
  const touching = fact.steps.filter((s) => s.from === stage || s.to === stage);
  const step = touching.find((s) => s.status !== "not_checked") ?? touching[0];
  if (!step || step.status === "not_checked") return { kind: "not_checked" };
  const value = step.from === stage ? step.from_value : step.to_value;
  return value === null || value === undefined ? { kind: "not_stated" } : { kind: "value", lines: valueLines(fact.id, value) };
}
