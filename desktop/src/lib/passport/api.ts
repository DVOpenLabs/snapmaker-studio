import { callExt } from "../extApi";
import type { BuildRequest, BuildResponse, ChainRole, VerifyRequest, VerifyResponse } from "./types";

const ROLE_ORDER: ChainRole[] = ["original", "prepared", "sliced"];

/** Entries in chain order; blank fields are skipped. Throws when nothing was entered. */
export function buildRequest(
  paths: Partial<Record<"original" | "prepared" | "sliced", string>>,
  recipesText = "",
  mappingsText = "",
): BuildRequest {
  const entries = ROLE_ORDER.flatMap((role) => {
    const path = (paths[role as "original" | "prepared" | "sliced"] ?? "").trim();
    return path === "" ? [] : [{ path, role }];
  });
  if (entries.length === 0) throw new Error("Enter the path of at least one file.");
  const body: BuildRequest = { entries };
  const recipes = parseOptionalList(recipesText, "Recipes");
  const mappings = parseOptionalList(mappingsText, "Material mappings");
  if (recipes !== undefined) body.recipes = recipes;
  if (mappings !== undefined) body.material_mappings = mappings;
  return body;
}

function parseOptionalList(text: string, label: string): unknown[] | undefined {
  if (text.trim() === "") return undefined;
  let parsed: unknown;
  try { parsed = JSON.parse(text); } catch { throw new Error(`${label} must be valid JSON.`); }
  if (!Array.isArray(parsed)) throw new Error(`${label} must be a JSON list.`);
  return parsed;
}

/** The files are read and hashed by the local service; nothing is written next to them. */
export function buildPassport(body: BuildRequest): Promise<BuildResponse> {
  return callExt<BuildResponse>("/passport/build", body, "Build passport");
}

export function verifyPassport(body: VerifyRequest): Promise<VerifyResponse> {
  return callExt<VerifyResponse>("/passport/verify", body, "Verify passport");
}
