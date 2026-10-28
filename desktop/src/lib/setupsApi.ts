import { callExt } from "./extApi";
import type { EvaluateRequest, EvaluateResponse, ListResponse } from "./setupsTypes";

/** Build the request body. Blank fields are left out; the key is included only when typed. */
export function buildEvaluateBody(input: { host: string; port?: string; key?: string; materials?: string[] }): EvaluateRequest {
  const body: EvaluateRequest = { host: input.host.trim() };
  const port = (input.port ?? "").trim();
  if (port !== "") {
    const n = Number(port);
    // A typo must not be sent as null, which the service reads as "use the default port".
    if (!Number.isInteger(n) || n < 1 || n > 65535) throw new Error("The port must be a whole number from 1 to 65535.");
    body.port = n;
  }
  const key = (input.key ?? "").trim();
  if (key !== "") body.api_key = key;
  const materials = (input.materials ?? []).map((m) => m.trim()).filter((m) => m !== "");
  if (materials.length > 0) body.requirements = materials.map((material) => ({ material }));
  return body;
}

/** Read one host through the local service. GET-only reads happen there; Studio sends no control command. */
export function evaluateSetup(body: EvaluateRequest): Promise<EvaluateResponse> {
  return callExt<EvaluateResponse>("/setups/evaluate", body, "Setup check");
}

export function listSetupAdapters(): Promise<ListResponse> {
  return callExt<ListResponse>("/setups/list", {}, "Setup adapters");
}
