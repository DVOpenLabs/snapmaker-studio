import { callExt } from "@/lib/extApi";

export type VariantRequest = { outputs: [{ path: string }, { path: string }] };

export interface VariantOutput {
  artifact: { artifact_id: string; role: string; bytes: { sha256: string; size_bytes: number }; name: string; locator: null; created_at: string };
  freshness: "current" | "stale";
  format: string;
  tools_used: { value: number[] | null; status: string };
  tool_changes: { value: number | null; status: string };
  grams_by_tool: { logical_tool: number; grams: number; physical_source: string | null; basis: string }[];
  time: { value: number | null; unit: string; status: string };
  waste: { value: string | null; status: string };
}

export interface VariantReport {
  outputs: [VariantOutput, VariantOutput];
  stale: boolean;
  tools_union: { value: number[] | null; status: string };
  settings_diff: { key: string; old: unknown; new: unknown; removed: boolean }[];
  requirements: { key: string; result: string; reason?: string }[];
  advisory: string;
}

export function compareVariants(request: VariantRequest): Promise<VariantReport> {
  return callExt<VariantReport>("/variants/compare", request, "compare sliced outputs");
}
