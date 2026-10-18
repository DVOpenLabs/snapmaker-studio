import type { ReceiptStatus, ReceiptStage } from "@/api";

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
