// Talks to the local Python sidecar. Port + token come from the Tauri shell,
// which spawned `python -m snapstudio_api` and read its handshake line.
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";

type ApiInfo = { port: number; token: string };
let cached: ApiInfo | null = null;

async function apiInfo(): Promise<ApiInfo> {
  if (cached) return cached;
  // Dev/screenshot-harness only: let headless Edge point at a running backend via
  // ?api=PORT:TOKEN. Stripped from production builds (import.meta.env.DEV === false).
  if ((import.meta as any).env?.DEV) {
    const q = new URLSearchParams(location.search).get("api");
    if (q) { const [p, t] = q.split(":"); cached = { port: Number(p), token: t || "" }; return cached; }
  }
  cached = await invoke<ApiInfo>("get_api_info");
  return cached;
}
// Dev/screenshot-harness only: a sample file path from ?file= instead of the native picker.
function devFilePath(): string | null {
  if ((import.meta as any).env?.DEV) return new URLSearchParams(location.search).get("file");
  return null;
}

// Open the locked in-app Model Browser at an approved-site URL. Rust validates
// the URL against the domain allowlist; this is a thin pass-through.
export async function openModelBrowser(url: string): Promise<void> {
  await invoke("open_model_browser", { url });
}

// Studio-side control of the locked Model Browser window (the remote page never
// gets any IPC). The trusted Find Models panel uses these to close / reflect state.
export async function closeModelBrowser(): Promise<void> {
  await invoke("close_model_browser");
}

export async function isModelBrowserOpen(): Promise<boolean> {
  return invoke<boolean>("is_model_browser_open");
}

// Bring the locked Model Browser window to the front. No-op if it isn't open.
export async function focusModelBrowser(): Promise<void> {
  await invoke("focus_model_browser");
}

// Snapmaker Orca handoff. detectOrca() returns the install path (or null); the UI
// never displays that path. openInOrca() launches the verified Orca exe with the
// prepared file — a one-way handoff. Studio does not slice and does not control Orca.
export async function detectOrca(): Promise<string | null> {
  return invoke<string | null>("detect_orca");
}

export async function openInOrca(path: string): Promise<void> {
  await invoke("open_in_orca", { path });
}

export async function health(): Promise<any> {
  const { port } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/health`);
  return r.json();
}

export async function doctor(path: string): Promise<any> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/doctor`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(`doctor failed (${r.status})`);
  return r.json();
}

export type PrepareMode = "preserve" | "recommended";

export interface SettingsChange {
  key: string;
  old: unknown;
  new: unknown;
}

export interface SettingsSummary {
  source_has_creator_settings: boolean;
  kept_count: number;
  mapped_to_u1?: SettingsChange[];
  compat_changed: SettingsChange[];
  could_not_carry: { key: string; reason: string }[];
  warnings: string[];
  recommendations_available: boolean;
  recommended_changes: SettingsChange[];
}

export interface ConversionResult {
  schema_version: "convert/2" | string;
  prepare_mode: PrepareMode | "starter";
  settings_summary: SettingsSummary;
  output_path: string;
  output_name: string;
  validated_ok: boolean;
  errors?: string[];
}

export async function convert(path: string, outDir?: string, prepareMode: PrepareMode = "preserve", dryRun = false): Promise<ConversionResult> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/convert`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path, out_dir: outDir ?? null, prepare_mode: prepareMode, dry_run: dryRun || undefined }),
  });
  if (!r.ok) {
    let msg = `convert failed (${r.status})`;
    try { const e = await r.json(); if (e?.error) msg = e.error; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json();
}

export async function diff(a: string, b: string): Promise<any> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/diff`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ a, b }),
  });
  if (!r.ok) {
    let msg = `diff failed (${r.status})`;
    try { const e = await r.json(); if (e?.error) msg = e.error; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json();
}

export interface LibraryProject {
  id: number;
  name: string;
  source_path: string;
  source_family: string | null;
  output_path: string | null;
  verdict: string | null;
  score: number | null;
  filament_count: number | null;
  last_action: string | null;
  updated_at: string | null;
}

export async function library(query = "", tag?: string): Promise<LibraryProject[]> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/library`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ query, tag: tag ?? null }),
  });
  if (!r.ok) throw new Error(`library failed (${r.status})`);
  const data = await r.json();
  return data.projects ?? [];
}

export interface HistoryEvent {
  id: number;
  project_id: number;
  action: string;
  detail: string;
  at: string;
}

export async function history(projectId: number): Promise<HistoryEvent[]> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/history`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ project_id: projectId }),
  });
  if (!r.ok) throw new Error(`history failed (${r.status})`);
  const data = await r.json();
  return data.events ?? [];
}

export async function libraryDelete(id: number): Promise<void> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/library/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ id }),
  });
  if (!r.ok) throw new Error(`delete failed (${r.status})`);
}

export interface BatchItem {
  path: string;
  status: "pending" | "running" | "done" | "error";
  output_path: string | null;
  output_name: string | null;
  validated_ok: boolean | null;
  error: string | null;
}

export interface BatchSnapshot {
  items: BatchItem[];
  total: number;
  done: number;
  failed: number;
  finished: boolean;
}

export interface BatchJobStatus {
  id: string;
  status: "running" | "done" | "error";
  error: string | null;
  result: BatchSnapshot | null;
}

export async function batchStart(paths: string[], outDir?: string): Promise<{ job_id: string; total: number }> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ paths, out_dir: outDir ?? null }),
  });
  if (!r.ok) {
    let msg = `batch failed (${r.status})`;
    try { const e = await r.json(); if (e?.error) msg = e.error; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json();
}

export async function batchStatus(jobId: string): Promise<BatchJobStatus> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/batch/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ job_id: jobId }),
  });
  if (!r.ok) throw new Error(`batch status failed (${r.status})`);
  return r.json();
}

export interface Insights {
  schema_version: string;
  name: string;
  source_type: string | null;
  source_family: string | null;
  verdict: string | null;
  readiness_score: number | null;
  is_compatible: boolean;
  objects: number | null;
  plates: number | null;
  colors: number | null;
  painted: boolean;
  materials: { color: string; type: string | null }[];
  dimensions_mm: { x: number; y: number; z: number } | null;
  triangles: number | null;
  complexity: string | null;
  issues: string[];
}

export async function insights(path: string): Promise<Insights> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/insights`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(`insights failed (${r.status})`);
  return r.json();
}

export interface ReadinessReport {
  schema_version: string;
  name: string;
  verdict: string | null;
  readiness_score: number | null;
  ready: boolean;
  checks: { name: string; status: "pass" | "warn" | "fail"; detail: string }[];
  preserved: string[];
  changes: string[];
  at_risk: string[];
  warnings: string[];
}

export async function report(path: string): Promise<ReadinessReport> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/report`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(`report failed (${r.status})`);
  return r.json();
}

export interface FirstLayerReport {
  available: boolean;
  bed_aware?: boolean;
  overall_level?: "ok" | "warn" | "risk";
  overall_text?: string;
  findings?: { level: "ok" | "warn" | "risk"; text: string }[];
  signals_used?: string[];
  reason?: string;
}
export async function firstLayer(path: string, host?: string | null): Promise<FirstLayerReport> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/first_layer`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path, host: host ?? null }),
  });
  if (!r.ok) throw new Error(`first_layer failed (${r.status})`);
  return r.json();
}

export interface ToolheadFitReport {
  available: boolean;
  printer_aware?: boolean;
  color_count?: number;
  toolhead_count?: number;
  overall_level?: "ok" | "warn" | "risk";
  overall_text?: string;
  findings?: { level: "ok" | "warn" | "risk"; text: string }[];
  reason?: string;
}
export async function toolheadFit(path: string, host?: string | null): Promise<ToolheadFitReport> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/toolhead_fit`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path, host: host ?? null }),
  });
  if (!r.ok) throw new Error(`toolhead_fit failed (${r.status})`);
  return r.json();
}

export interface CostEstimate {
  available: boolean;
  grams?: number;
  price_per_kg?: number;
  currency?: string;
  cost?: number;
  basis?: string;
  reason?: string;
}
export async function costEstimate(path: string, pricePerKg = 20, currency = "$"): Promise<CostEstimate> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/cost_estimate`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path, price_per_kg: pricePerKg, currency }),
  });
  if (!r.ok) throw new Error(`cost_estimate failed (${r.status})`);
  return r.json();
}

// Cost-to-Price Intelligence: true cost + suggested selling price with margin.
export interface CostToPrice {
  available: boolean;
  time_known?: boolean;
  grams?: number;
  print_hours?: number | null;
  currency?: string;
  breakdown?: {
    material: number; electricity: number; depreciation: number;
    labor: number; failure_buffer: number; marketplace_fee: number;
  };
  true_cost?: number;
  markup_pct?: number;
  suggested_price?: number;
  margin?: number;
  margin_pct?: number;
  basis?: string;
  verdict?: string;
  reason?: string;
}
export async function costToPrice(
  path: string,
  opts: { pricePerKg?: number; currency?: string; markupPct?: number;
          host?: string | null; filename?: string | null;
          factors?: Record<string, number> } = {},
): Promise<CostToPrice> {
  const { port, token } = await apiInfo();
  const body: Record<string, unknown> = { path, currency: opts.currency ?? "$", ...(opts.factors ?? {}) };
  if (opts.pricePerKg != null) body.price_per_kg = opts.pricePerKg;
  if (opts.markupPct != null) body.markup_pct = opts.markupPct;
  if (opts.host) body.host = opts.host;
  if (opts.filename) body.filename = opts.filename;
  const r = await fetch(`http://127.0.0.1:${port}/cost_to_price`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`cost_to_price failed (${r.status})`);
  return r.json();
}

// Business Mode: a whole batch rolled into one cost / price / profit P&L.
export interface BatchPricing {
  available: boolean;
  parts?: number;
  currency?: string;
  total_grams?: number;
  total_cost?: number;
  total_price?: number;
  total_profit?: number;
  margin_pct?: number;
  avg_price?: number;
  time_known?: boolean;
  verdict?: string;
  reason?: string;
}
export async function batchPricing(
  paths: string[],
  opts: { pricePerKg?: number; currency?: string; markupPct?: number } = {},
): Promise<BatchPricing> {
  const { port, token } = await apiInfo();
  const body: Record<string, unknown> = { paths, currency: opts.currency ?? "$" };
  if (opts.pricePerKg != null) body.price_per_kg = opts.pricePerKg;
  if (opts.markupPct != null) body.markup_pct = opts.markupPct;
  const r = await fetch(`http://127.0.0.1:${port}/batch_pricing`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`batch_pricing failed (${r.status})`);
  return r.json();
}

// Studio Intelligence Report: the one screen synthesising every Doctor.
export interface ReportRisk {
  doctor: string; level: "ok" | "warn" | "risk"; text: string;
  community?: { fix: string; success_pattern: string; confidence: string; sources: string[] };
}
export interface ReportEvidence { doctor: string; status: string; detail: string; }
export interface IntelligenceReport {
  available: boolean;
  studio_score?: number | null;
  print_success_score?: number | null;
  cost?: number | null;
  suggested_price?: number | null;
  margin_pct?: number | null;
  profit_per_print?: number | null;
  currency?: string;
  printer_compatibility?: "Compatible" | "Check" | "Unknown";
  risks?: ReportRisk[];
  biggest_risk?: ReportRisk | null;
  recommendations?: string[];
  next_action?: string;
  supporting?: ReportEvidence[];
  verdict?: string;
  reason?: string;
  is_demo?: boolean;
  demo_name?: string;
  expected_improvement?: { current: number; after_fixes: number; is_estimate: boolean; label: string } | null;
  comparison?: {
    issues_found: number; fixes_offered: number; prices_the_print: boolean;
    orca_line: string; studio_line: string;
  };
}
export async function demoReport(): Promise<IntelligenceReport> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/demo_report`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({}),
  });
  if (!r.ok) throw new Error(`demo_report failed (${r.status})`);
  return r.json();
}
export async function intelligenceReport(path: string, host?: string | null): Promise<IntelligenceReport> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/intelligence_report`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify(host ? { path, host } : { path }),
  });
  if (!r.ok) throw new Error(`intelligence_report failed (${r.status})`);
  return r.json();
}

// Pricing Doctor: hobby / marketplace / premium selling prices.
export interface PricingTier { label: string; markup_pct: number; price: number; profit: number; margin_pct: number; why: string; }
export interface PricingDoctor {
  available: boolean; currency?: string; true_cost?: number;
  tiers?: PricingTier[]; verdict?: string; reason?: string;
}
export async function pricingDoctor(path: string, host?: string | null,
  opts: { currency?: string; factors?: Record<string, number> } = {}): Promise<PricingDoctor> {
  const { port, token } = await apiInfo();
  const body: Record<string, unknown> = { path, ...(opts.factors ?? {}) };
  if (host) body.host = host;
  if (opts.currency) body.currency = opts.currency;
  const r = await fetch(`http://127.0.0.1:${port}/pricing_doctor`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`pricing_doctor failed (${r.status})`);
  return r.json();
}

// Profit Doctor: profit per print, margin, batch, monthly, break-even.
export interface ProfitDoctor {
  available: boolean; currency?: string;
  profit_per_print?: number; margin_pct?: number; monthly_profit?: number;
  prints_per_month?: number; break_even_prints?: number | null;
  batch?: { count: number; profit: number }; verdict?: string; reason?: string;
}
export async function profitDoctor(path: string, host?: string | null,
  opts: { currency?: string; factors?: Record<string, number> } = {}): Promise<ProfitDoctor> {
  const { port, token } = await apiInfo();
  const body: Record<string, unknown> = { path, ...(opts.factors ?? {}) };
  if (host) body.host = host;
  if (opts.currency) body.currency = opts.currency;
  const r = await fetch(`http://127.0.0.1:${port}/profit_doctor`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`profit_doctor failed (${r.status})`);
  return r.json();
}

// Multi-Material Doctor: one verdict for a multicolour U1 print.
export interface MMDoctor {
  available: boolean;
  multi_material?: boolean;
  colors?: number;
  heads?: number;
  heads_known?: boolean;
  overall_level?: "ok" | "warn" | "risk";
  overall_text?: string;
  findings?: { level: "ok" | "warn" | "risk"; text: string }[];
  fixes?: string[];
  verdict?: string;
  reason?: string;
}
export async function mmDoctor(path: string, host?: string | null): Promise<MMDoctor> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/mm_doctor`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify(host ? { path, host } : { path }),
  });
  if (!r.ok) throw new Error(`mm_doctor failed (${r.status})`);
  return r.json();
}

// Bed-Fit / Out-of-Bounds Doctor: does it fit the U1 bed, and if not, why + fix.
export interface BedFit {
  available: boolean;
  bed_known?: boolean;
  bed_source?: string;
  bed_mm?: { x: number; y: number; z: number };
  dims_mm?: { x: number; y: number; z: number };
  overall_level?: "ok" | "warn" | "risk";
  overall_text?: string;
  findings?: { level: "ok" | "warn" | "risk"; text: string }[];
  fixes?: string[];
  reason?: string;
}
export async function bedFit(path: string, host?: string | null): Promise<BedFit> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/bed_fit`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify(host ? { path, host } : { path }),
  });
  if (!r.ok) throw new Error(`bed_fit failed (${r.status})`);
  return r.json();
}

// Print Success Prediction: pre-print "will it print?" odds from existing signals.
export interface SuccessPrediction {
  available: boolean;
  likelihood?: number;
  band?: "likely" | "uncertain" | "risky";
  factors?: string[];
  verdict?: string;
  reason?: string;
}
export async function predictSuccess(path: string, host?: string | null): Promise<SuccessPrediction> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/predict_success`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify(host ? { path, host } : { path }),
  });
  if (!r.ok) throw new Error(`predict_success failed (${r.status})`);
  return r.json();
}

export interface FailureInsights {
  available: boolean;
  overall_level?: "ok" | "warn" | "risk";
  overall_text?: string;
  total?: number;
  failed?: number;
  failure_rate?: number;
  recent_failure_streak?: number;
  top_cause?: string | null;
  repeat_offenders?: { filename: string; failures: number }[];
  findings?: { level: "ok" | "warn" | "risk"; text: string }[];
  reason?: string;
}
export function printerFailureInsights(host: string, port = 7125): Promise<FailureInsights> {
  return printerPost("/printer/failure_insights", { host, port });
}

// Printer Health Score: one 0–100 from the U1's own read-only firmware + history signals.
export interface PrinterHealth {
  available: boolean;
  score?: number;
  grade?: "A" | "B" | "C" | "D" | "F";
  drivers?: string[];
  basis?: string;
  verdict?: string;
  reason?: string;
}
export function printerHealth(host: string, port = 7125): Promise<PrinterHealth> {
  return printerPost("/printer/health", { host, port });
}

/** Which printer Studio believes it is talking to, and how sure it is.
 *
 *  Moonraker publishes no model name, so `matched` is false far more often than
 *  true — and that is a correct answer, not a degraded one. Every check in
 *  Printer Hub works on a machine Studio cannot name. */
export interface PrinterIdentity {
  matched: boolean;
  printer_id?: string | null;
  confidence?: string | null;
  evidence?: string | null;
  matched_on?: string[];
}

/** How well established the facts about a printer are.
 *
 *  `hardware_verified` means a physical machine of this kind answered. Anything
 *  weaker must keep its qualifier: a profile-verified printer is never shown as
 *  "supported", "tested" or "verified" on its own. */
export type VerificationLevel =
  | "hardware_verified" | "profile_verified" | "simulated" | "unknown";

export interface PrinterProfileSummary {
  printer_id: string;
  display_name: string;
  manufacturer?: string | null;
  model?: string | null;
  verification_level: VerificationLevel;
  /** The exact words this level is allowed to be shown as. The backend owns this
   *  string so one place decides how a verification level reads. */
  verification_label: string;
  verification_meaning: string;
  verification_note?: string | null;
  tool_count?: number | null;
  build_volume_mm?: { x: number; y: number; z: number } | null;
  known_unknowns?: string[];
  not_verified?: string[];
}

// Firmware Capability Intelligence: what this printer's firmware actually exposes.
export interface FirmwareFeature { name: string; detail?: string; }
export interface PrinterFirmware {
  available: boolean;
  identity?: PrinterIdentity;
  toolhead_count?: number | null;
  bed_mm?: { x: number; y: number; z: number } | null;
  macro_count?: number;
  /** True only when a community firmware answered for itself. Never inferred
   *  from macro count, and its absence never means the printer is stock. */
  extended_firmware?: boolean;
  extended_firmware_evidence?: string | null;
  many_custom_macros?: boolean;
  features?: FirmwareFeature[];
  summary?: string;
  reason?: string;
}
export function printerFirmware(host: string, port = 7125): Promise<PrinterFirmware> {
  return printerPost("/printer/firmware", { host, port });
}

export interface MeshReport {
  schema_version: string;
  available: boolean;
  reason?: string;
  triangle_count?: number;
  integrity?: {
    watertight: boolean; manifold: boolean; open_edges: number; holes: number;
    non_manifold_edges: number; degenerate_faces: number; duplicate_faces: number;
    winding_consistent: boolean;
  };
  overhang?: { overhang_pct: number; severe_pct: number; supports_likely: boolean };
  stability?: { tip_risk: boolean; com_over_base: boolean; margin_mm: number | null; height_mm: number; aspect: number };
  volume_mm3?: number;
  volume_cm3?: number;
  surface_area_mm2?: number;
  material_estimate_g?: number | null;
  findings?: { level: "ok" | "warn" | "risk"; text: string }[];
}

export async function mesh(path: string): Promise<MeshReport> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/mesh`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(`mesh failed (${r.status})`);
  return r.json();
}

export interface PrintStrategy {
  id: string;
  name: string;
  explanation: string;
  intent: string;
  use_cases: string[];
  tradeoffs: string;
  settings: Record<string, string>;
}
export interface StrategyList {
  schema_version: string;
  default: string;
  strategies: PrintStrategy[];
  categories: Record<string, string>;
  notes: string;
}
export interface StrategyRecommendation {
  recommended: string;
  reason: string;
  warnings: string[];
  signals_used: string[];
  estimated_note: string;
  signals: { colors: number | null; source_family: string | null; dimensions_mm: { x: number; y: number; z: number } | null; complexity: string | null };
}

export async function strategies(): Promise<StrategyList> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/strategies`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token }, body: "{}",
  });
  if (!r.ok) throw new Error(`strategies failed (${r.status})`);
  return r.json();
}

export async function strategyRecommend(path: string): Promise<StrategyRecommendation> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/strategy/recommend`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(`recommend failed (${r.status})`);
  return r.json();
}

export interface PrinterProbe {
  reachable: boolean; host: string; port: number;
  klippy_state?: string; moonraker_version?: string; error?: string;
}
export interface PrinterStatus {
  host: string; port: number; print_state: string | null; filename: string | null;
  message: string | null;
  progress: number | null;
  print_duration_s: number | null; total_duration_s: number | null; filament_used_mm: number | null;
  current_layer: number | null; total_layer: number | null;
  speed_factor: number | null; extrude_factor: number | null;
  bed: { temperature: number | null; target: number | null };
  toolheads: { index: number; temperature: number | null; target: number | null; active?: boolean }[];
}
export interface PrinterJob {
  filename: string | null; status: string | null;
  start_time: number | null; end_time: number | null;
  print_duration_s: number | null; total_duration_s: number | null; filament_used_mm: number | null;
}
export interface PrinterHistory {
  host: string; port: number; jobs: PrinterJob[]; failures: PrinterJob[];
  totals: { total_jobs: number | null; total_print_time_s: number | null; total_time_s: number | null;
    total_filament_used_mm: number | null; longest_print_s: number | null };
}
export interface PrinterDiagnostics {
  host: string; port: number; klippy_state?: string; state_message?: string | null;
  hostname?: string; warnings: string[]; failed_components: string[]; healthy: boolean;
}

async function printerPost<T>(path: string, body: object): Promise<T> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} failed (${r.status})`);
  return r.json();
}

export function printerHistory(host: string, port = 7125): Promise<PrinterHistory> {
  return printerPost("/printer/history", { host, port, limit: 20 });
}
export function printerDiagnostics(host: string, port = 7125): Promise<PrinterDiagnostics> {
  return printerPost("/printer/diagnostics", { host, port });
}
export interface PrinterFileMetadata {
  available: boolean; filename: string;
  estimated_time_s?: number | null; filament_total_mm?: number | null; filament_weight_g?: number | null;
  filament_type?: string | null; layer_count?: number | null; layer_height?: number | null;
  first_layer_height?: number | null; object_height?: number | null;
  first_layer_bed_temp?: number | null; first_layer_extr_temp?: number | null;
  slicer?: string | null; slicer_version?: string | null; thumbnail_count?: number;
}
export function printerFileMetadata(host: string, filename: string, port = 7125): Promise<PrinterFileMetadata> {
  return printerPost("/printer/file_metadata", { host, filename, port });
}
export interface PrinterCapabilities {
  host: string; port: number; toolhead_count: number | null;
  bed_mm: { x: number; y: number; z: number } | null;
}
export function printerCapabilities(host: string, port = 7125): Promise<PrinterCapabilities> {
  return printerPost("/printer/capabilities", { host, port });
}

// ---- Printer Hub Phase B: control (every start/cancel/e-stop is confirmed in the UI) ----
export interface PrinterControlResult { ok?: boolean; action?: string; result?: string; filename?: string; path?: string; size?: number; }
export interface PrinterQueue { queue_state: string | null; jobs: { filename: string | null; id: string | null }[]; count: number; }

export function printerPause(host: string, port = 7125): Promise<PrinterControlResult> {
  return printerPost("/printer/control/pause", { host, port });
}
export function printerResume(host: string, port = 7125): Promise<PrinterControlResult> {
  return printerPost("/printer/control/resume", { host, port });
}
export function printerCancel(host: string, port = 7125): Promise<PrinterControlResult> {
  return printerPost("/printer/control/cancel", { host, port });
}
export function printerStartPrint(host: string, filename: string, port = 7125): Promise<PrinterControlResult> {
  return printerPost("/printer/control/start", { host, filename, port });
}
export function printerEmergencyStop(host: string, port = 7125): Promise<PrinterControlResult> {
  return printerPost("/printer/control/emergency_stop", { host, port });
}
export function printerJobQueue(host: string, port = 7125): Promise<PrinterQueue> {
  return printerPost("/printer/job_queue", { host, port });
}
/**
 * What can be true after an upload. Collapsing these into "failed" is how someone
 * deletes a file that is already on the printer, or starts one the printer has
 * not finished reading.
 */
export type UploadState =
  | "verified"              // the printer has it and has read it
  | "pending_verification"  // it is there; the printer is still reading it
  | "not_listed"            // the bytes were accepted and the printer does not list it
  | "mismatch"              // a file of that name is there, and it is not this one
  | "refused_by_printer"    // the printer answered, and said no
  | "not_accepted"          // the connection failed; nothing was started
  | "changed"               // the world moved since the checks were read
  | "unknown";

export interface UploadResult extends PrinterControlResult {
  state?: UploadState;
  uploaded?: boolean;
  detail?: string;
  status?: number;
  changed?: Array<{ part: string; title: string; detail: string }>;
  check?: SendCheck;
  confirmation?: { ok?: boolean; detail?: string };
}

export function printerUploadGcode(
  host: string, path: string, port = 7125,
  // What the user was shown when they decided to send. The engine re-reads the
  // same things and refuses rather than uploading against a stale answer.
  expectState?: SendState | null, projectPath?: string,
  // The same provider the send check used. Re-reading the check without it would
  // compare against a different set of facts than the one the user was shown.
  provider: ProviderArgs = {},
): Promise<UploadResult> {
  return printerPost("/printer/upload_gcode", {
    host, path, port,
    expect_state: expectState ?? null,
    project_path: projectPath ?? "",
    ...provider,
  });
}

// Native picker limited to sliced gcode, for uploading to the printer.
export async function openGcodeDialog(): Promise<string | null> {
  const picked = await open({ multiple: false, filters: [{ name: "Sliced gcode", extensions: ["gcode", "g", "gco"] }] });
  return typeof picked === "string" ? picked : null;
}

export async function printerDiscover(hosts?: string[]): Promise<PrinterProbe[]> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/printer/discover`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ hosts: hosts ?? null }),
  });
  if (!r.ok) throw new Error(`discover failed (${r.status})`);
  return (await r.json()).printers ?? [];
}

export async function printerStatus(host: string, port = 7125): Promise<PrinterStatus> {
  const { port: p, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${p}/printer/status`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ host, port }),
  });
  if (!r.ok) throw new Error(`status failed (${r.status})`);
  return r.json();
}

// Native open dialog limited to the formats the engine accepts.
// ---- Per-Plate Filament Remapper (Commits A/B/C) ----
import type { PlateInspect, PlateDryRun, PlateExport } from "@/lib/plateRemapWizard";

async function platePost<T>(route: string, body: Record<string, unknown>): Promise<T> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}${route}`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let msg = `${route} failed (${r.status})`;
    try { const e = await r.json(); if (e?.error) msg = e.error; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json();
}

export function plateInspect(path: string): Promise<PlateInspect> {
  return platePost("/plate_inspect", { path });
}
export function plateDryRun(path: string, uiPlate: number, fromFilament: number, toFilament: number): Promise<PlateDryRun> {
  return platePost("/plate_dry_run", { path, ui_plate: uiPlate, from_filament: fromFilament, to_filament: toFilament });
}
export function plateExport(path: string, uiPlate: number, fromFilament: number, toFilament: number): Promise<PlateExport> {
  return platePost("/plate_export", { path, ui_plate: uiPlate, from_filament: fromFilament, to_filament: toFilament });
}

// ---- Print Quality Doctor (advisory, read-only) ----
export interface QualityEvidence { label: string; level: "ok" | "warn" | "risk"; text: string; doctor: string; }
export interface QualityResult {
  symptom: string;
  title: string;
  likely_causes: string[];
  first_checks: string[];
  orca_paths: string[];
  hardware_checks: string[];
  avoid: string[];
  evidence_needed: string[];
  disclaimer: string;
  evidence?: QualityEvidence[];        // file-specific findings (when a file is given)
  evidence_available?: boolean;
}
export interface QualityResponse { result: QualityResult | null; warnings: string[]; }
export function qualityCheck(symptom: string, path?: string): Promise<QualityResponse> {
  return platePost("/quality_check", path ? { symptom, path } : { symptom });
}

// ---- File/source ecosystem detection (read-only, advisory) ----
export interface SourceCompatibilityReport {
  schema_version: string;
  ecosystem: string;          // bambu-family | prusa | cura | generic | stl | unknown
  ecosystem_label: string;
  source_app: string | null;
  printer_model: string | null;
  is_u1: boolean;
  readable_settings: Record<string, unknown>;
  can_read: string[];
  cannot_convert: string[];
  risks: string[];
  recommended_next_step: string;
}
export function sourceCompatibility(path: string): Promise<SourceCompatibilityReport> {
  return platePost("/source_compatibility", { path });
}

// ---- First Layer Doctor (advisory, read-only) ----
export interface FirstLayerResult {
  symptom: string;
  title: string;
  likely_causes: string[];
  first_checks: string[];
  u1_checks: string[];
  slicer_checks: string[];
  avoid: string[];
  evidence_needed: string[];
  disclaimer: string;
}
export interface FirstLayerResponse { result: FirstLayerResult | null; warnings: string[]; }
export function firstLayerCheck(symptom: string): Promise<FirstLayerResponse> {
  return platePost("/first_layer_check", { symptom });
}

// ---- Scale Doctor (analysis-only preview) ----
export interface ScaleResult {
  available: boolean;
  reason?: string;
  scale_percent?: number;
  original_dimensions?: { x: number; y: number; z: number };
  scaled_dimensions?: { x: number; y: number; z: number };
  fits_build_volume?: boolean;
  estimated_material_delta?: { grams: number; basis: string };
  estimated_cost_delta?: { amount: number | null; basis: string };
  risks?: string[];
  recommendation?: "likely safe" | "caution" | "not recommended";
  explanation?: string;
}
export function scalePreview(path: string, scalePercent: number): Promise<ScaleResult> {
  return platePost("/scale_preview", { path, scale_percent: scalePercent });
}

// ---- Scale Options Ladder ----
export interface ScalePartDims {
  plate_index: number;
  name: string;
  dimensions: { x: number; y: number; z: number };
  fits_build_volume?: boolean;
}
export interface ScaleOption {
  label: string;
  scale_percent: number;
  risk_level: "low" | "medium" | "high";
  recommendation: string;
  dimensions_by_part: ScalePartDims[];
  explanation: string;
}
export interface ScaleOptionsResult {
  available: boolean;
  schema_version?: number;
  reason?: string;
  printer?: string;
  margin_mm?: number;
  build_volume?: { x: number; y: number; z: number };
  current_parts?: { plate_index: number; name: string; dimensions: { x: number; y: number; z: number } }[];
  group_scaling_recommended?: boolean;
  limiting_part?: string;
  limiting_axis?: string;
  recommended_scale_percent?: number;
  placement_verified?: boolean;
  placement_max_percent?: number | null;
  fit_basis?: string;
  options?: ScaleOption[];
  warnings?: string[];
  next_steps?: string[];
}
export function scaleOptions(path: string, marginMm = 5, printer = "snapmaker_u1"): Promise<ScaleOptionsResult> {
  return platePost("/scale_options", { path, printer, margin_mm: marginMm });
}

// ---- Scale Doctor: prepare a scaled copy (writes a new file; original untouched) ----
export interface ScaledCopyResult {
  source_type?: string;
  output_path?: string;
  output_name?: string;
  validated_ok?: boolean;
  errors?: string[];
  scale_percent?: number;
  original_mm?: number[];   // [x, y, z]
  scaled_mm?: number[];     // [x, y, z]
  fits_u1?: boolean | null;
  blocked?: boolean;
}
export function prepareScaled(path: string, scalePercent: number): Promise<ScaledCopyResult> {
  return platePost("/prepare_scaled", { path, scale_percent: scalePercent });
}

// ---- Print Failure Troubleshooter (known-good aware) ----
export interface PrintFailureFinding {
  id: string;
  severity: string;
  title: string;
  evidence: string;
  explanation: string;
  suggested_action: string;
  safe_starting_point?: string;
}
export interface PrintFailureResult {
  available: boolean;
  schema_version?: string;
  reason?: string;
  summary?: string;
  confidence?: string;
  known_good_print?: boolean;
  known_good_context?: string;
  findings?: PrintFailureFinding[];
  troubleshooting_steps?: string[];
  compare_against_known_good?: string[];
  disclaimers?: string[];
}
export interface PrintFailureInput {
  path: string;
  symptom?: string;
  known_good_print?: boolean;
  known_good_material?: string;
  failed_material?: string;
  failure_stage?: string;
}
export function printFailureTroubleshoot(input: PrintFailureInput): Promise<PrintFailureResult> {
  return platePost("/print_failure_troubleshoot", { symptom: "fails_even_with_supports", ...input });
}

// ---- Model Discovery Hub v1 (search + link-out) ----
import type { SearchResponse, SearchFilters } from "@/lib/modelSearch";
export function modelSearch(query: string, filters: SearchFilters = {}): Promise<SearchResponse> {
  return platePost("/model_search", { query, filters });
}

// ---- Compatibility Doctor (read-only) ----
export interface CompatibilityFinding {
  id: string;
  severity: "error" | "warning" | "info";
  title: string;
  explanation: string;
  setting_path: string;
  suggested_action: string;
  evidence: string;
}
export interface CompatibilityResult {
  findings: CompatibilityFinding[];
  summary: string;
  recommendation: string;
}
export function compatibilityCheck(path: string): Promise<CompatibilityResult> {
  return platePost("/compatibility_check", { path });
}

// 3MF-only picker for the plate remap wizard (projects only — not bare STLs).
export async function open3mfDialog(): Promise<string | null> {
  const dev = devFilePath(); if (dev) return dev;
  const picked = await open({ multiple: false, filters: [{ name: "3MF project", extensions: ["3mf"] }] });
  return typeof picked === "string" ? picked : null;
}

export async function openModelDialog(): Promise<string | null> {
  const dev = devFilePath(); if (dev) return dev;
  const picked = await open({
    multiple: false,
    filters: [{ name: "3D models / projects", extensions: ["stl", "3mf"] }],
  });
  return typeof picked === "string" ? picked : null;
}

// Multi-select variant for batch conversion.
export async function openModelsDialog(): Promise<string[]> {
  const dev = devFilePath(); if (dev) return [dev];
  const picked = await open({
    multiple: true,
    filters: [{ name: "3D models / projects", extensions: ["stl", "3mf"] }],
  });
  if (Array.isArray(picked)) return picked;
  return typeof picked === "string" ? [picked] : [];
}

// ---- Ecosystem intelligence -------------------------------------------------
// Studio reads what a project actually contains and says which open-source tool
// is the right next step for it. Detection of installed tools happens in Rust
// (the webview can only ask to open a tool by id, never by path), and the engine
// only ever marks a tool "installed" for ids Rust actually found on disk.

export interface EcosystemTool {
  id: string;
  name: string;
  kind: string;
  official: boolean;
  role: string;
  url: string;
  license: string;
  install_hint: string;
  caution?: string | null;
  maturity: "stable" | "preview" | string;
  handoff: "file" | "link" | string;
  stage: string;
  score: number;
  why: string[];
  installed: boolean;
  path: string | null;
}

export interface EcosystemAdvice {
  schema_version: string;
  registry_updated?: string;
  primary: EcosystemTool | null;
  alternatives: EcosystemTool[];
  discover: EcosystemTool[];
  summary: string;
  traits: Record<string, any>;
}

/** Tool id -> install path, containing only tools genuinely found on disk. */
export async function detectTools(): Promise<Record<string, string>> {
  try {
    return await invoke<Record<string, string>>("detect_tools");
  } catch {
    // Not running inside the Tauri shell (dev harness): nothing is detectable,
    // which is reported honestly as "nothing installed" rather than as an error.
    return {};
  }
}

/** One-way handoff: launch a detected tool with this file. Studio never slices. */
export async function openWithTool(toolId: string, path: string): Promise<void> {
  await invoke("open_with_tool", { toolId, path });
}

export async function ecosystemAdvice(
  path: string,
  installed?: Record<string, string>,
): Promise<EcosystemAdvice> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/ecosystem_advice`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path, installed: installed ?? null }),
  });
  if (!r.ok) throw new Error(`ecosystem advice failed (${r.status})`);
  return r.json();
}

// ---- Plate placement --------------------------------------------------------
// A small object placed at another printer's coordinates lands off the U1 plate
// while passing every size check. These read where each object sits and, when a
// single honest move fixes it, write a NEW copy — the original is never touched.

export interface PlacementItem {
  object_id: string;
  dimensions: { x: number; y: number; z: number };
  position: { x: number; y: number };
  off_plate: boolean;
  overhang_mm: { left: number; right: number; front: number; back: number };
  edges: string | null;
}

export interface PlacementCheck {
  schema_version: string;
  available: boolean;
  reason?: string;
  source_printer?: string | null;
  plate_count?: number;
  item_count?: number;
  items: PlacementItem[];
  off_plate: PlacementItem[];
  skipped_plates?: { plate: number; reason: string }[];
  unresolved_objects?: { object_id: string }[];
  fixable: boolean;
  summary?: string;
}

export interface PlacementFix {
  schema_version: string;
  ok: boolean;
  reason?: string;
  output_path?: string;
  output_name?: string;
  objects_moved?: number;
  changes?: { what: string; detail: string; kept: string }[];
  summary?: string;
  after?: PlacementCheck;
}

export async function placementCheck(path: string): Promise<PlacementCheck> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/placement_check`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(`placement check failed (${r.status})`);
  return r.json();
}

export async function preparePlaced(path: string, outDir?: string): Promise<PlacementFix> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/prepare_placed`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path, out_dir: outDir ?? null }),
  });
  if (!r.ok) throw new Error(`placement fix failed (${r.status})`);
  return r.json();
}

// ---- Project ↔ printer preflight -------------------------------------------
// Joins what a project needs to what the printer reports. Every check can come
// back "unknown", which is a real answer: stock U1 firmware does not publish the
// fitted nozzle, so Studio says to go and look rather than inventing a match.

export type PreflightResult = "ok" | "attention" | "unknown" | "blocked";

export interface PreflightCheck {
  id: string;
  title: string;
  result: PreflightResult;
  evidence: string | null;
  confidence: "confirmed" | "likely" | "informational" | string;
  consequence: string;
  action: string | null;
  source: string | null;
}

export interface Preflight {
  schema_version: string;
  checks: PreflightCheck[];
  counts: Record<PreflightResult, number>;
  needs_attention: PreflightCheck[];
  unknowns: PreflightCheck[];
  printer_reachable: boolean;
  summary: string;
  disclaimer: string;
  printer?: Record<string, unknown>;
}

export async function preflight(path: string, host?: string, port = 7125): Promise<Preflight> {
  const { port: apiPort, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${apiPort}/preflight`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path, host: host ?? "", port }),
  });
  if (!r.ok) throw new Error(`preflight failed (${r.status})`);
  return r.json();
}

// ---- The Orca round-trip ----------------------------------------------------
// After Snapmaker Orca slices the prepared copy, the result should come back on
// its own. Studio polls one folder the user chose, only while the page that
// cares is open, and only offers files it can see are finished.

export type Provenance = "confirmed" | "likely" | "ambiguous" | "no_match" | "unknown";

// Evidence is not all of one kind, and the difference decides the answer.
// "identity" says something about the model itself — which objects the job
// prints. "profile" says something about the setup it was sliced with, which
// every job from the same printer with the same spools shares. Only identity
// evidence can establish a match; profile evidence can only corroborate one.
export type EvidenceKind = "identity" | "profile" | "circumstantial";

export interface ProvenanceEvidence {
  signal: string;
  weight: number;
  detail: string;
  kind?: EvidenceKind;
  label?: string;
}

export interface ProvenanceResult {
  schema_version: string;
  verdict: Provenance;
  score: number;
  evidence: ProvenanceEvidence[];
  identity_evidence?: ProvenanceEvidence[];
  summary: string;
  /** Why this answer and not a more certain one. */
  why?: string;
}

export interface WatchCandidate {
  path: string;
  name: string;
  size_bytes: number;
  age_seconds: number;
  complete: boolean;
  state: string;
  job?: {
    slicer: string | null;
    printer_model: string | null;
    layer_count: number | null;
    tools_used: number[] | null;
    total_g: number | null;
  };
  provenance?: ProvenanceResult;
}

export interface WatchResult {
  schema_version: string;
  available: boolean;
  error?: string;
  folder: string | null;
  seen?: number;
  candidates: WatchCandidate[];
  best?: string | null;
  best_verdict?: Provenance | null;
  summary?: string;
}

export function watchFolder(folder: string, projectPath?: string): Promise<WatchResult> {
  return post("/watch_folder", { folder, project_path: projectPath ?? "" }, "watch folder");
}

export function sliceProvenance(projectPath: string, gcodePath: string): Promise<ProvenanceResult> {
  return post("/slice_provenance", { project_path: projectPath, gcode_path: gcodePath },
    "provenance");
}

// ---- Update check -----------------------------------------------------------
// The only thing in Studio that talks to the internet: when a person presses
// the manual button, or — only if they opted in via the checkbox — at most
// once a day. Either way it sends nothing but the request: no identifiers, no
// usage, no telemetry. Studio never downloads or installs an update on its own.

export interface UpdateInfo {
  current: string;
  latest: string;
  newer: boolean;
  url: string;
  published: string;
}

export async function checkForUpdate(): Promise<UpdateInfo> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<UpdateInfo>("check_for_update");
}

/** The opt-in automatic-check preference, persisted locally by the app shell. */
export interface UpdateCheckPref {
  auto_check: boolean;
  last_checked_at_unix: number | null;
}

export async function getUpdateCheckPref(): Promise<UpdateCheckPref> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<UpdateCheckPref>("get_update_check_pref");
}

export async function setAutoCheckUpdates(enabled: boolean): Promise<void> {
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("set_auto_check_updates", { enabled });
}

/**
 * Called once per app launch. Returns null whenever the preference is off, a
 * check already happened within the last day, or the request failed — all
 * silently, by design: this is never allowed to interrupt anyone.
 */
export async function maybeAutoCheckUpdate(): Promise<UpdateInfo | null> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<UpdateInfo | null>("maybe_auto_check_update");
}

// ---- Print plan, materials, and the send confirmation ------------------------
// The three questions that only exist after slicing: what happens and when, what
// should be loaded, and whether to press send.

export interface PlanLine { at: string; text: string; evidence: string }

export interface PrintPlan {
  schema_version: string;
  available: boolean;
  error?: string;
  layers_seen?: number;
  tools_seen?: number[];
  tool_changes?: number;
  pauses?: number;
  first_tool?: number | null;
  last_tool?: number | null;
  truncated?: boolean;
  narration?: PlanLine[];
  summary?: string;
}

export interface MaterialSlot {
  tool: number;
  label: string;
  needed: boolean;
  wants_material: string | null;
  wants_colour: string | null;
  has_material: string | null;
  has_colour: string | null;
  state:
    | "ready" | "empty" | "wrong_material" | "different_colour"
    // Short according to something that tracks the spool, and short according to
    // a figure that will not say where it came from. They read the same and mean
    // different things, so they are not the same state.
    | "not_enough" | "maybe_not_enough"
    | "unused" | "unknown" | null;
  detail: string | null;
  action: string | null;
  needs_grams?: number | null;
  remaining_g?: number | null;
  remaining_quality?: "tracked" | "derived" | "user_confirmed" | "unknown";
  sufficiency?: {
    verdict: "enough" | "probably_enough" | "probably_short" | "insufficient" | "unknown";
    detail: string;
    source: string;
    quality?: string;
    trusted?: boolean;
  };
  /** Where two sources describe this slot differently. Shown, never resolved. */
  conflicts?: string[];
  notes?: string[];
}

export interface MaterialPlan {
  schema_version: string;
  available: boolean;
  printer_known: boolean;
  slots: MaterialSlot[];
  to_change?: number[];
  ready?: number[];
  colour_notes?: number[];
  summary: string;
}

export interface SendItem {
  kind: "blocker" | "warning" | "unknown";
  title: string;
  detail: string;
  action: string | null;
  source: string | null;
}

/**
 * A fingerprint of everything the send check looked at.
 *
 * Passed back with the upload so the engine can re-read the same things and
 * refuse if any of them moved while the user was deciding — a slot emptied, a
 * spool swapped, a print started, the job re-sliced to the same filename.
 */
export interface SendState {
  schema_version: string;
  token: string;
  hashes: Record<string, string>;
  parts: Record<string, unknown>;
}

export interface SendCheck {
  schema_version: string;
  provenance?: ProvenanceResult | null;
  available: boolean;
  printer_reachable?: boolean;
  verdict: "blocker" | "warning" | "unknown" | "ready";
  counts?: Record<string, number>;
  items: SendItem[];
  headline: string;
  disclaimer: string;
  state?: SendState;
  printer?: { observed_at?: number; reachable?: boolean };
}

async function post<T>(route: string, body: unknown, label: string): Promise<T> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}${route}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${label} failed (${r.status})`);
  return r.json();
}

export function printPlan(path: string): Promise<PrintPlan> {
  return post("/print_plan", { path }, "print plan");
}

/** What a material provider adds to a request, or nothing when none is set up.
 *
 *  Built by `providerArgs` in the provider store, so a screen never has to know
 *  the wire names. Sending nothing is the normal case and a complete one: a
 *  stock printer with no other software answers every question here except how
 *  much filament is left. */
export interface ProviderArgs {
  /** Which provider to read. The engine turns this into a decision exactly once,
   *  in the adapter; nothing downstream of that looks at it again. */
  provider?: string;
  provider_url?: string;
  slot_map?: Record<string, number>;
  slot_base?: number;
}

/** Can Studio read this provider? Read-only, and the address is validated in the
 *  engine before anything is opened — a public host is refused rather than
 *  fetched. */
export interface ProviderTest {
  ok: boolean;
  reason?: string;
  spools: number;
  /** Which provider answered, echoed back so a stale result cannot be read as
   *  belonging to the one now selected. */
  provider?: string;
  /** How many spools carry a weight something is actually keeping track of.
   *  Both providers report what a spool started with until something prints from
   *  it, so "connected" and "useful" are different numbers. */
  with_tracked_weight?: number;
  archived?: number;
  detail?: string;
  choices?: ProviderSpool[];
}

export interface ProviderSpool {
  id: number;
  label: string;
  material?: string | null;
  color?: string | null;
  remaining_g?: number | null;
  remaining_quality?: string | null;
  archived?: boolean;
}

export function providerTest(url: string, provider: string): Promise<ProviderTest> {
  return post("/provider/test", { url, provider }, "provider test");
}

export function materialPlan(
  path: string, host?: string, port = 7125, provider: ProviderArgs = {},
): Promise<MaterialPlan> {
  return post("/material_plan", { path, host: host ?? "", port, ...provider }, "material plan");
}

export function sendCheck(
  path: string, host?: string, port = 7125, includeTimeline = false, projectPath?: string,
  provider: ProviderArgs = {},
): Promise<SendCheck> {
  return post("/send_check", {
    path, host: host ?? "", port, include_timeline: includeTimeline,
    project_path: projectPath ?? "", ...provider,
  }, "send check");
}

// ---- Support bundle ---------------------------------------------------------
// Studio asks people to report when it gets an analysis wrong. This gathers the
// facts behind that report — and shows the user exactly what it contains before
// anything is written. Nothing is ever sent from Studio.

export interface DiagnosticsPreview {
  schema_version: string;
  text: string;
  bytes: number;
  sections: string[];
  note: string;
}

export interface DiagnosticsBuilt {
  schema_version: string;
  path: string;
  bytes: number;
  sections: string[];
  note: string;
}

export async function diagnosticsPreview(opts: {
  projectPath?: string; gcodePath?: string; host?: string;
} = {}): Promise<DiagnosticsPreview> {
  const { port: apiPort, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${apiPort}/diagnostics_preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({
      project_path: opts.projectPath ?? "", gcode_path: opts.gcodePath ?? "",
      host: opts.host ?? "", port: 7125,
    }),
  });
  if (!r.ok) throw new Error(`diagnostics preview failed (${r.status})`);
  return r.json();
}

export async function diagnosticsBuild(opts: {
  projectPath?: string; gcodePath?: string; host?: string;
} = {}): Promise<DiagnosticsBuilt> {
  const { port: apiPort, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${apiPort}/diagnostics_build`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({
      project_path: opts.projectPath ?? "", gcode_path: opts.gcodePath ?? "",
      host: opts.host ?? "", port: 7125,
    }),
  });
  if (!r.ok) throw new Error(`diagnostics build failed (${r.status})`);
  return r.json();
}

// ---- Post-Slice Doctor ------------------------------------------------------
// The other half of the preflight. Everything above asks whether a *project*
// suits a printer; this asks whether the job the slicer actually produced suits
// the printer as it is right now. Studio still does not slice.

export interface SlicedJob {
  slicer: string | null;
  slicer_version: string | null;
  printer_model: string | null;
  layer_count: number | null;
  layer_height_mm: number | null;
  max_z_mm: number | null;
  estimated_seconds: number | null;
  tools_used: number[] | null;
  total_g: number | null;
  size_bytes: number | null;
  purge: {
    separable: boolean;
    expected: boolean;
    prime_tower?: boolean;
    detail: string;
  } | null;
}

export interface PostSlice {
  schema_version: string;
  available: boolean;
  printer_reachable?: boolean;
  job?: SlicedJob;
  checks: PreflightCheck[];
  counts: Record<string, number>;
  needs_attention?: PreflightCheck[];
  unknowns?: PreflightCheck[];
  summary: string;
  disclaimer: string;
  printer?: Record<string, unknown>;
}

export async function postSlice(
  path: string, host?: string, port = 7125, projectPath?: string,
): Promise<PostSlice> {
  const { port: apiPort, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${apiPort}/post_slice`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path, host: host ?? "", port, project_path: projectPath ?? "" }),
  });
  if (!r.ok) throw new Error(`post-slice check failed (${r.status})`);
  return r.json();
}

export interface SlicedCostLine {
  label: string;
  amount: number | null;
  evidence: string;
  source: "measured" | "derived" | "assumption" | "unknown" | string;
  detail: string | null;
}

export interface SlicedCost {
  schema_version: string;
  available: boolean;
  currency?: string;
  per_slot?: Array<{
    tool: number; material: string | null; name: string | null;
    grams: number; mm: number | null; price_per_kg: number; cost: number;
  }>;
  total_grams?: number | null;
  print_seconds?: number | null;
  lines?: SlicedCostLine[];
  total?: number | null;
  incomplete?: string[];
  waste?: { separable: boolean; expected: boolean; detail: string; source: string };
  summary: string;
}

export async function slicedCost(path: string, pricePerKg = 20, currency = "$"): Promise<SlicedCost> {
  const { port: apiPort, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${apiPort}/sliced_cost`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path, price_per_kg: pricePerKg, currency }),
  });
  if (!r.ok) throw new Error(`sliced cost failed (${r.status})`);
  return r.json();
}

// ---- Fidelity audit ---------------------------------------------------------
// What survived preparing a copy. The categories that matter are `unverified`
// and `unsupported`: a report that can only say preserved-or-changed has to lie
// about the parts it does not understand.

export type FidelityStatus =
  | "preserved_exact"
  | "preserved_semantic"
  | "changed"
  | "added"
  | "removed"
  | "unsupported"
  | "unverified";

/**
 * Whether Snapmaker Orca was measured to act on a fact at all.
 *
 * Separate from `status`, which only says whether the fact made it from the
 * source into the copy. A copy can pass that on paper and fail on the plate:
 * one stated an object's filament correctly and Orca, having decided the file
 * was foreign, loaded the geometry and nothing else.
 *
 * `null` means nobody has measured it — which is not the same as "ignored".
 */
export type FidelityTarget =
  | "reaches_target"
  | "reconstructed"
  | "ignored"
  | "not_established";

export interface FidelityRow {
  element: string;
  status: FidelityStatus;
  detail: string;
  reason: string | null;
  part: string | null;
  target?: FidelityTarget | null;
  target_detail?: string | null;
}

export interface FidelityReport {
  schema_version: string;
  available: boolean;
  reason?: string;
  original?: string;
  prepared?: string;
  rows: FidelityRow[];
  counts: Partial<Record<FidelityStatus, number>>;
  kept: FidelityRow[];
  changed: FidelityRow[];
  not_carried: FidelityRow[];
  unverified: FidelityRow[];
  claims: {
    geometry_unchanged: boolean;
    nothing_removed: boolean;
    fully_accounted: boolean;
    may_claim_nothing_lost: boolean;
  };
  summary: string;
  disclaimer?: string;
}

export async function fidelityAudit(original: string, prepared: string): Promise<FidelityReport> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/fidelity`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ original, prepared }),
  });
  if (!r.ok) throw new Error(`fidelity audit failed (${r.status})`);
  return r.json();
}

// ---- Fix ledger -------------------------------------------------------------
// One record per file Studio produced: what it did, what triggered it, every
// change with its old and new value, and where to go back to. Originals are
// never written to, so "return to original" points the workflow at an untouched
// file rather than trying to reverse the copy.

export interface FixChange {
  key?: string;
  old?: unknown;
  new?: unknown;
  reason?: string;
}

export interface FixEntry {
  schema_version: string;
  operation: string;
  title: string;
  timestamp: string;
  source_name: string | null;
  output_name: string | null;
  changes: FixChange[];
  findings: { title?: string; detail?: string }[];
  validated: boolean | null;
  notes: string[];
  local?: { source_path: string; output_path: string };
}

export interface FixHistory {
  schema_version: string;
  entries: FixEntry[];
}

export interface FixOriginal {
  available: boolean;
  source_path?: string | null;
  source_name?: string | null;
  title?: string;
  reason?: string | null;
  note?: string;
}

export async function fixHistory(source?: string, limit = 50): Promise<FixHistory> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/fix_history`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ source: source ?? "", limit }),
  });
  if (!r.ok) throw new Error(`fix history failed (${r.status})`);
  return r.json();
}

export async function fixOriginal(output: string): Promise<FixOriginal> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/fix_original`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ output }),
  });
  if (!r.ok) throw new Error(`fix original failed (${r.status})`);
  return r.json();
}

// ---- Colour planning --------------------------------------------------------
// More colours than toolheads is not one problem but two: colours that share
// layers need a toolhead each, colours introduced at a height may be planned
// swaps. Painted colour is read from the project itself — which slots, how much
// area, and at what heights — and a painted colour only leaves the "needs a
// toolhead" bucket when its separation from every other colour is proven.

export type ColorVerdict = "fits" | "possible_with_swaps" | "needs_reduction" | "cannot_classify";

export interface ColorUse {
  slot: number;
  color: string | null;
  material: string | null;
  usage: "simultaneous" | "layer_based" | "unclassified";
  evidence: string;
  from_z_mm?: number | null;
  estimated_layer?: number | null;
  layer_is_estimated?: boolean;
  /** Set when this colour is used by painting the model rather than by
   *  assigning a whole object to it. The measurements are of the paint itself. */
  painted?: boolean;
  painted_facets?: number | null;
  painted_area_mm2?: number | null;
  painted_z_min_mm?: number | null;
  painted_z_max_mm?: number | null;
}

/** One painted mesh, for the expert disclosure. */
export interface PaintedObject {
  object_id: string | null;
  part: string | null;
  name: string | null;
  triangle_count: number;
  painted_triangle_count: number;
  mesh_area_mm2: number;
  default_slot: number | null;
  default_slot_source: string;
  transform_known: boolean;
  malformed_triangle_count: number;
  facets_outside_mesh: number;
  assignments: {
    slot: number | null;
    state: number;
    painted: boolean;
    triangles_touching: number;
    area_mm2: number;
    area_share: number | null;
    z_min_mm: number | null;
    z_max_mm: number | null;
    z_is_placed: boolean;
    evidence: string;
  }[];
}

/** What the project's own painting says, decoded. Absent painting leaves
 *  `painted` false and everything else empty. */
export interface PaintedColor {
  available: boolean;
  painted?: boolean;
  reason?: string | null;
  dialect?: string | null;
  format_version?: number | null;
  format_version_known?: boolean;
  slots?: number[];
  unlisted_slots?: number[];
  painted_facets?: number | null;
  malformed_facets?: number | null;
  facets_outside_mesh?: number | null;
  truncated?: boolean;
  confidence?: string;
  objects?: PaintedObject[];
  coexistence?: {
    pairs: { slots: number[]; verdict: "separate" | "overlaps" | "unknown"; reason: string }[];
    note: string;
  };
  headline?: string | null;
  evidence?: string | null;
}

export interface ColorPlan {
  schema_version: string;
  available: boolean;
  reason?: string;
  color_count: number;
  toolheads: number;
  toolheads_measured: boolean;
  toolheads_source: string;
  painted_regions: boolean;
  painted?: PaintedColor;
  simultaneous: ColorUse[];
  layer_based: ColorUse[];
  unclassified: ColorUse[];
  verdict: ColorVerdict;
  headline: string;
  summary: string;
  guidance: string[];
  disclaimer?: string;
}

export async function colorPlan(path: string, toolheads?: number): Promise<ColorPlan> {
  const { port, token } = await apiInfo();
  const r = await fetch(`http://127.0.0.1:${port}/color_plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ path, toolheads: toolheads ?? 0 }),
  });
  if (!r.ok) throw new Error(`colour plan failed (${r.status})`);
  return r.json();
}

/**
 * A model passed on the command line, if any — file association, "Open with", or
 * an automated run. Null is the ordinary case. Never throws outside Tauri.
 */
export async function launchFile(): Promise<string | null> {
  try {
    return await invoke<string | null>("get_launch_file");
  } catch {
    return null;
  }
}
