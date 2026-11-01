import { callExt } from "../extApi";
import type { EvaluateResponse, SaveResponse, SavedAssembly } from "./types";

/** Parse the text of a JSON box. A mistake becomes a sentence for the person, never a stack trace. */
export function parseJsonBox<T>(text: string, what: string): T {
  const trimmed = text.trim();
  if (trimmed === "") throw new Error(`${what} is empty.`);
  try {
    return JSON.parse(trimmed) as T;
  } catch {
    throw new Error(`${what} is not valid JSON. Check for a missing comma or quote.`);
  }
}

/** Work out the advisory verdict through the local service. Nothing is sent off this computer. */
export function evaluateAssembly(assembly: unknown, supply: unknown): Promise<EvaluateResponse> {
  return callExt<EvaluateResponse>("/assemblies/evaluate", { assembly, supply }, "Assembly check");
}

export function saveAssembly(assembly: unknown, id?: number, expectedRevision?: number): Promise<SaveResponse> {
  const body: Record<string, unknown> = { assembly };
  if (id !== undefined) {
    body.id = id;
    body.expected_revision = expectedRevision;
  }
  return callExt<SaveResponse>("/assemblies/save", body, "Save assembly");
}

export function listAssemblies(): Promise<{ assemblies: SavedAssembly[] }> {
  return callExt("/assemblies/list", {}, "Saved assemblies");
}

export function getAssembly(id: number): Promise<{ id: number; revision: number; assembly: unknown }> {
  return callExt("/assemblies/get", { id }, "Open assembly");
}
