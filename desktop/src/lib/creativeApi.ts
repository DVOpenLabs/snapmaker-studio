import { callExt } from "./extApi";

export interface CreativeNamedPart { name: string; sha256: string }

export interface CreativeRecipeComponent { source: string; ratio?: unknown; ratio_kind?: string }

export interface CreativeRecipe {
  recipe_id: string;
  generator: { name: string; version: string | null };
  kind: string;
  components: CreativeRecipeComponent[];
  simulated: boolean;
  execution_supported: boolean | null;
}

export interface CreativeOrigin {
  generator: string;
  status: "detected" | "chosen" | "ambiguous" | "unknown";
  candidates: string[];
}

export interface CreativeInspectResponse {
  origin: CreativeOrigin;
  understood: string[];
  passed_through: CreativeNamedPart[];
  could_not_interpret: string[];
  missing: string[];
  diagnostics: string[];
  recipes: CreativeRecipe[];
  physical_slots_needed: number | null;
  source: { name: string; size_bytes: number; sha256_before: string; sha256_after: string; unchanged: boolean };
  evidence: string;
  advisory: string;
}

export const CREATIVE_FORMATS = ["auto", "forcaslicer", "lixnix", "fullspectrum", "imagemap", "lumina"] as const;
export type CreativeFormat = (typeof CREATIVE_FORMATS)[number];

/** The request body for one inspection. A blank path is a sentence for the person, not a request. */
export function buildInspectBody(path: string, format: CreativeFormat = "auto"): { path: string; format?: CreativeFormat } {
  const trimmed = path.trim().replace(/^"(.*)"$/, "$1");
  if (trimmed === "") throw new Error("Enter the path of a .3mf project file.");
  return format === "auto" ? { path: trimmed } : { path: trimmed, format };
}

/** Inspect one local project file through the local service. Read-only; nothing is sent off this computer. */
export function inspectCreative(path: string, format: CreativeFormat = "auto"): Promise<CreativeInspectResponse> {
  return callExt<CreativeInspectResponse>("/creative/inspect", buildInspectBody(path, format), "Creative project inspection");
}

const GENERATOR_LABEL: Record<string, string> = {
  forcaslicer: "FOrcaSlicer",
  lixnix: "LixNix Full Multi-Nozzle",
  fullspectrum: "FullSpectrum",
  imagemap: "OrcaSlicer ImageMap",
  lumina: "Lumina Layers",
};

/** One sentence about where the project came from. Unknown stays unknown. */
export function originSentence(origin: CreativeOrigin): string {
  if (origin.status === "ambiguous") {
    const names = origin.candidates.map((c) => GENERATOR_LABEL[c] ?? c).join(" and ");
    return `Origin not decided: the settings match ${names}.`;
  }
  if (origin.generator === "unknown") return "Origin unknown: Studio does not recognise the generator of this project.";
  const name = GENERATOR_LABEL[origin.generator] ?? origin.generator;
  return origin.status === "chosen" ? `Read as ${name} (your choice).` : `Looks like ${name}, from the settings it contains.`;
}
