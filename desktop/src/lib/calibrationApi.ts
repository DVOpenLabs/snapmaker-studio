import { callExt } from "./extApi";

export interface CalibrationRequest {
  source: "ditherforge_txt" | "kromacut_json";
  content: string;
  family: "frontlit" | "backlit";
  layer_height_mm: number;
  nozzle_mm?: number;
  material?: string;
  model?: string;
  first_layer_height_mm?: number;
  physical_colors?: Record<string, string>;
  owned_filaments?: { label: string; color: string }[];
}

export interface CalibrationEntry {
  enabled?: boolean;
  label: string; simulated_color: string; physical_color: string | null;
  physical_distance: number | null; td: number; td_provenance: "provided" | "derived";
  alternatives: { label: string; color: string; distance: number; advisory: boolean }[];
}

export interface CalibrationResponse {
  status: "evaluated" | "unknown";
  decoded: { schema_version: string | null; value: unknown; diagnostics: { code: string; field: string; severity: string }[]; valid_for_evaluation: boolean; raw?: unknown };
  result: null | { run_id: string; calibration_basis: { calibration_basis_id: string; family: string; layer_height_mm: number; nozzle_mm: number; material: string; source?: string; model?: string | null; first_layer_height_mm?: number | null }; entries: CalibrationEntry[]; advisory: string; inputs_revision: { revision: string; [key: string]: unknown } };
}

export function evaluateCalibration(input: CalibrationRequest): Promise<CalibrationResponse> {
  return callExt<CalibrationResponse>("/calibration/evaluate", input, "Palette calibration");
}

export type CalibrationRun = Omit<NonNullable<CalibrationResponse["result"]>, "run_id"> & { run_id?: string };
export function calibrationHistory(): Promise<{ runs: CalibrationRun[] }> {
  return callExt<{ runs: CalibrationRun[] }>("/calibration/history", {}, "Calibration history");
}
