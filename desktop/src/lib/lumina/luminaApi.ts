import { callExt } from "../extApi";

/** One artifact kind the adapter supports, with what it means and how it was tested. */
export interface LuminaFormat {
  kind: string;
  meaning: string;
  evidence: string;
}

export interface LuminaFormatsResponse {
  formats: LuminaFormat[];
  evidence: string;
  progress: "unknown";
  cancel: "unknown";
  note: string;
}

export interface LuminaStatusResponse {
  status: "ok" | "unknown";
  api_version?: string;
  can_generate?: boolean;
  code?: string;
  message?: string;
  progress: "unknown";
  cancel: "unknown";
  evidence: string;
  note?: string;
}

export interface LuminaGenerateRequest {
  service_url: string;
  image_path: string;
  lut_name: string;
  format: string;
  out_dir?: string;
}

export interface LuminaGenerateResponse {
  generated: true;
  file_name: string;
  sha256: string;
  size_bytes: number;
  kind: string;
  generated_by: string;
  location_label: string;
  advisory: string;
  progress: "unknown";
  cancel: "unknown";
  evidence: string;
}

export interface LuminaForm {
  serviceUrl: string;
  imagePath: string;
  lutName: string;
  format: string;
  outDir?: string;
}

/** Build the request. A missing field is an error here, never a guess: the format in particular is a
 *  choice from the service's explicit list, never inferred from the image. */
export function buildGenerateBody(form: LuminaForm, formats: readonly LuminaFormat[]): LuminaGenerateRequest {
  const service_url = form.serviceUrl.trim();
  const image_path = form.imagePath.trim();
  const lut_name = form.lutName.trim();
  if (service_url === "") throw new Error("Enter the address of your local Lumina-compatible service.");
  if (image_path === "") throw new Error("Enter the path of the image file on this computer.");
  if (lut_name === "") throw new Error("Enter the LUT name the service should use.");
  if (!formats.some((f) => f.kind === form.format)) {
    throw new Error(`Choose a format from the list: ${formats.map((f) => f.kind).join(", ")}.`);
  }
  const body: LuminaGenerateRequest = { service_url, image_path, lut_name, format: form.format };
  const out = (form.outDir ?? "").trim();
  if (out !== "") body.out_dir = out;
  return body;
}

export function fetchLuminaFormats(): Promise<LuminaFormatsResponse> {
  return callExt<LuminaFormatsResponse>("/engines/lumina/formats", {}, "Lumina formats");
}

export function checkLuminaService(serviceUrl: string): Promise<LuminaStatusResponse> {
  return callExt<LuminaStatusResponse>("/engines/lumina/status", { service_url: serviceUrl.trim() }, "Lumina service check");
}

export function generateWithLumina(body: LuminaGenerateRequest): Promise<LuminaGenerateResponse> {
  return callExt<LuminaGenerateResponse>("/engines/lumina/generate", body, "Lumina generate");
}
