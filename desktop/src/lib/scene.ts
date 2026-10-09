// Client for the engine's scene/1 contract (backend/snapstudio_core/data/scene-1.schema.json). Read-only: it asks the
// engine to describe a project, follows the job, and hands back the finished scene. Nothing here edits a file.
import { engineConnection } from "@/api";

export type UnitName = "micron" | "millimeter" | "centimeter" | "inch" | "foot" | "meter";
export type VolumeRole = "part" | "modifier" | "negative" | "support_enforcer" | "support_blocker" | "unknown";
export type ResourceKey = { part: string; object_id: string };
export type Bounds = { min: number[]; max: number[] } | null;

export type SceneVolume = {
  id: string; triangle_start: number; triangle_count: number; role: VolumeRole;
  source: "prusa_range" | "bambu_part" | "object" | null;
};
export type SceneMesh = {
  key: ResourceKey; vertex_count: number; triangle_count: number;
  positions_f32le_base64: string; indices_u32le_base64: string; volumes: SceneVolume[];
};
export type ScenePlateRef = { state: "known" | "ambiguous" | "unknown"; plate_id: string | null; source: "plate_config" | null };
export type SceneNode = {
  id: string; parent_id: string | null; resource: ResourceKey; mesh_key: ResourceKey | null;
  local_to_parent_mm: number[]; world_mm: number[]; mirrored: boolean; role_context: VolumeRole | null;
  build_index: number | null; instance_ref: { build_index: number | null; component_path: number[] };
  plate: ScenePlateRef; placement_state: "known" | "unknown"; printable: boolean | null;
  has_non_part_volumes: boolean; bounds_mm: Bounds; finding_ids: string[];
};
export type SceneFinding = {
  id: string; engine: string; schema: string; pointer: string; scope: "project" | "plate" | "instance";
  kind: "placement" | "size" | "note"; target_ids: string[];
  value: {
    code: "PLACEMENT_OUTSIDE_BED" | "SIZE_EXCEEDS_BED";
    overhang_mm: { left: number; right: number; front: number; back: number } | null;
  };
};
export type LimitationCode =
  | "UNKNOWN_VOLUME_ROLE" | "UNKNOWN_PLACEMENT" | "PLATE_MEMBERSHIP_AMBIGUOUS" | "PLATE_MEMBERSHIP_UNKNOWN"
  | "PLATES_UNAVAILABLE" | "BED_TEMPLATE_UNAVAILABLE" | "REPEATED_INSTANCE_PLACEMENT_UNVERIFIED"
  | "NON_MM_SOURCE_UNIT" | "UNSUPPORTED_UNIT" | "MULTI_PLATE_PLACEMENT_UNCHECKED" | "NO_BUILD_ITEMS";
export type SceneLimitation = { code: LimitationCode; target_ids: string[] };
export type SceneBed = {
  polygon_mm: number[][]; height_mm: number | null; edge_margin_mm: number; policy: "u1_template" | "fallback";
};
export type SceneV1 = {
  schema: "scene/1"; revision: string; status: "complete" | "partial"; units: "mm"; axes: "right-handed-z-up";
  sources: { part: string; unit: UnitName; mm_per_unit: number }[];
  bed: SceneBed; meshes: SceneMesh[]; nodes: SceneNode[];
  plates: { id: string; ui_number: number | null; origin_mm: number[] | null }[];
  findings: SceneFinding[]; limitations: SceneLimitation[];
  counts: Record<"nodes" | "meshes" | "vertices" | "triangles" | "rendered_triangles" | "plates" | "findings" | "limitations", number>;
  limits: Record<string, number>;
};

export type JobState = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type JobStage = "reading" | "parsing" | "encoding" | null;
export type SceneErrorCode =
  | "INVALID_REQUEST" | "UNSUPPORTED_FORMAT" | "INVALID_ARCHIVE" | "INVALID_GEOMETRY" | "UNRESOLVED_REFERENCE"
  | "LIMIT_EXCEEDED" | "SOURCE_CHANGED" | "CANCELLED" | "TIMEOUT" | "EXPIRED" | "NOT_READY" | "WORKER_WEDGED" | "INTERNAL"
  // Client-side only: the engine could not be reached, or sent something that is not a scene/1 document.
  | "UNREACHABLE" | "BAD_RESPONSE"
  // The engine refused a start as out of order (a newer one was seen from this client) or as already cancelled.
  | "STALE_START" | "CANCELLED_BEFORE_START"
  // The engine does not know this client session (restarted, or idle too long), or will not open another one.
  | "SESSION_EXPIRED" | "SESSION_LIMIT";
export type JobStatus = {
  job_id: string; request_id: string; state: JobState; stage: JobStage; completed: number | null; total: number | null;
  error: { code: SceneErrorCode; message: string } | null; revision: string | null;
};
export type SceneProgress = { state: JobState; stage: JobStage; completed: number | null; total: number | null };

export class SceneError extends Error {
  readonly code: SceneErrorCode;
  constructor(code: SceneErrorCode) {
    super(code);
    this.name = "SceneError";
    this.code = code;
  }
}

// Plain-language text for each failure. The engine's own message is never shown: it can carry file names.
const ERROR_TEXT: Record<SceneErrorCode, string> = {
  INVALID_REQUEST: "The engine could not understand the request for the 3D view.",
  UNSUPPORTED_FORMAT: "The 3D view supports 3MF and STL files only.",
  INVALID_ARCHIVE: "This file could not be read as a 3MF project, so there is no 3D view.",
  INVALID_GEOMETRY: "This file has geometry the 3D view cannot read, so there is no 3D view.",
  UNRESOLVED_REFERENCE: "This project points at a part that is not in the file, so the 3D view cannot show it.",
  LIMIT_EXCEEDED: "This project is larger than the 3D view can show. The rest of Studio still works on it.",
  SOURCE_CHANGED: "The file changed while it was being read. Try again once it has finished saving.",
  CANCELLED: "The 3D view was cancelled.",
  TIMEOUT: "Reading the project took too long, so the 3D view was stopped.",
  EXPIRED: "The 3D view result was discarded by the engine. Try again.",
  NOT_READY: "The 3D view is still being prepared. Try again in a moment.",
  WORKER_WEDGED: "The engine is still busy with an earlier 3D view. Wait a few seconds and try again.",
  INTERNAL: "The engine hit an unexpected problem while building the 3D view.",
  UNREACHABLE: "Studio could not reach the local engine, so there is no 3D view.",
  BAD_RESPONSE: "The engine sent a 3D view Studio does not understand.",
  STALE_START: "A newer request for the 3D view replaced this one.",
  CANCELLED_BEFORE_START: "This 3D view request was cancelled before it started.",
  SESSION_EXPIRED: "Studio lost its connection to the engine for the 3D view. Try again.",
  SESSION_LIMIT: "The engine is already serving as many 3D views as it allows. Close another Studio window, then try again.",
};
export function sceneErrorText(code: SceneErrorCode): string {
  return ERROR_TEXT[code] ?? ERROR_TEXT.INTERNAL;
}

const KNOWN_CODES = new Set<string>(Object.keys(ERROR_TEXT));
function asCode(value: unknown): SceneErrorCode {
  return typeof value === "string" && KNOWN_CODES.has(value) ? (value as SceneErrorCode) : "INTERNAL";
}

/** One engine call: POST a JSON body to a scene route and return the parsed body with its HTTP status. */
export type SceneTransport = (
  route: "session" | "start" | "status" | "result" | "cancel", body: unknown, signal?: AbortSignal,
) => Promise<{ status: number; body: unknown }>;

export const defaultTransport: SceneTransport = async (route, body, signal) => {
  let connection: { base: string; token: string };
  try {
    connection = await engineConnection();
  } catch {
    throw new SceneError("UNREACHABLE");
  }
  let response: Response;
  try {
    response = await fetch(`${connection.base}/scene/${route}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Auth-Token": connection.token },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new SceneError("UNREACHABLE");
  }
  let parsed: unknown = null;
  try { parsed = await response.json(); } catch { /* an empty or non-JSON body is handled by the caller */ }
  return { status: response.status, body: parsed };
};

export function newRequestId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c?.getRandomValues) c.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
const STATES = new Set(["queued", "running", "succeeded", "failed", "cancelled"]);

function readStatus(body: unknown): JobStatus {
  if (!isObject(body) || typeof body.job_id !== "string" || typeof body.state !== "string" || !STATES.has(body.state)) {
    throw new SceneError("BAD_RESPONSE");
  }
  return body as unknown as JobStatus;
}

/** What /scene/start answers: a job's identity and state only. It carries no stage, progress or error. */
export type JobStart = {
  job_id: string; request_id: string; state: JobState; revision: string | null; replaced_job_id: string | null;
};

function readStart(body: unknown): JobStart {
  return readStatus(body) as unknown as JobStart;
}

function errorFromResponse(status: number, body: unknown): SceneError {
  if (isObject(body) && "error" in body) return new SceneError(asCode(body.error));
  return new SceneError(status >= 500 ? "INTERNAL" : "BAD_RESPONSE");
}

// ---- Sessions ------------------------------------------------------------------------------------------------------------
// The engine orders overlapping starts within a SESSION. The client opens one session lazily (the first time it needs one)
// and uses its `client_id` on every start and cancel. Each start attempt takes the next `seq` of the session (strictly
// increasing from 1). The engine's rules, which the stand-in engine in scene.test.ts implements:
//   * a start whose seq is not higher than the highest seen is refused (STALE_START). That includes an exact retry of a start
//     the engine already processed, so every retry uses a fresh request id and the next seq;
//   * a start whose request or seq was cancelled is refused (CANCELLED_BEFORE_START);
//   * an unknown or idle-expired session is refused (SESSION_EXPIRED): the client opens a new session (seq starts again at 1)
//     and restarts ONCE; more sessions than the engine allows is SESSION_LIMIT (shown, with Try again);
//   * the guarantee is per session only: a start from another session replaces the running job as before.
type Session = { clientId: string; seq: number };
let session: Session | null = null;
let opening: Promise<Session> | null = null;

/** Forgets the session. For tests; the app never needs it. */
export function resetSceneSession(): void {
  session = null;
  opening = null;
}
/** The current session's client id, or null before one is opened. For tests and diagnostics. */
export function currentSceneClientId(): string | null {
  return session?.clientId ?? null;
}

/** Opens the session once, however many loads ask at the same time. A caller can stop waiting without cancelling the open. */
function ensureSession(transport: SceneTransport, caller: AbortSignal, ms: number): Promise<Session> {
  if (session) return Promise.resolve(session);
  if (!opening) {
    const attempt = (async (): Promise<Session> => {
      const reply = await limited((s) => transport("session", {}, s), new AbortController().signal, ms);
      if (reply.status !== 200) throw errorFromResponse(reply.status, reply.body);
      const id = isObject(reply.body) ? reply.body.client_id : undefined;
      if (typeof id !== "string" || id.length === 0 || id.length > 128) throw new SceneError("BAD_RESPONSE");
      session = { clientId: id, seq: 0 };
      return session;
    })();
    opening = attempt;
    const done = () => { if (opening === attempt) opening = null; };
    attempt.then(done, done);
  }
  const shared = opening;
  return limited(() => shared, caller, ms);
}

/** One start attempt: enough to cancel it. */
export type StartAttempt = { clientId: string; requestId: string; seq: number };

const CANCEL_MS = 3000;

/**
 * Tells the engine a start attempt is no longer wanted, by `{client_id, request_id, seq}`, so it works whether or not the
 * start has been answered or even delivered (a late start is then refused). Best effort and silent: it runs from cleanup
 * paths that must never throw or wait, it is bounded, and it is never awaited, so it cannot hold up the next start. A
 * SESSION_EXPIRED answer (the session is gone, so the request is too) needs nothing more.
 */
export function cancelSceneRequest(attempt: StartAttempt, transport: SceneTransport = defaultTransport): void {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), CANCEL_MS);
  let sent: Promise<unknown>;
  try {
    sent = transport("cancel", { client_id: attempt.clientId, request_id: attempt.requestId, seq: attempt.seq }, ctl.signal);
  } catch {
    clearTimeout(timer);
    return;
  }
  void sent.catch(() => undefined).finally(() => clearTimeout(timer));
}


export type LoadSceneOptions = {
  signal: AbortSignal;
  /** A fresh id per scene generation, so a cancelled earlier job is never handed back. */
  requestId?: string;
  onProgress?: (p: SceneProgress) => void;
  pollMs?: number;
  transport?: SceneTransport;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
  /** How long to wait for the engine to answer the start call. Default 15 s. */
  startTimeoutMs?: number;
  /** How long to wait for any one status or result answer. Default 30 s. */
  requestTimeoutMs?: number;
};

function abortError(): Error {
  const e = new Error("aborted");
  e.name = "AbortError";
  return e;
}
export const isAbort = (e: unknown): boolean => isObject(e) && (e as { name?: unknown }).name === "AbortError";

function defaultSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError());
    const t = setTimeout(() => { signal.removeEventListener("abort", onAbort); resolve(); }, ms);
    const onAbort = () => { clearTimeout(t); reject(abortError()); };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Runs one engine call that gives up when the caller aborts or after `ms`. The result is a race, so a transport that
 * ignores its signal still cannot hold the caller: the answer is dropped. Rejects with an AbortError or a TIMEOUT SceneError.
 */
function limited<T>(run: (signal: AbortSignal) => Promise<T>, caller: AbortSignal, ms: number): Promise<T> {
  if (caller.aborted) return Promise.reject(abortError());
  const ctl = new AbortController();
  let timedOut = false;
  const onCaller = () => ctl.abort();
  caller.addEventListener("abort", onCaller, { once: true });
  const timer = setTimeout(() => { timedOut = true; ctl.abort(); }, ms);
  let onLimit: () => void = () => undefined;
  return new Promise<T>((resolve, reject) => {
    onLimit = () => reject(timedOut ? new SceneError("TIMEOUT") : abortError());
    ctl.signal.addEventListener("abort", onLimit, { once: true });
    run(ctl.signal).then(resolve, reject);
  }).finally(() => {
    clearTimeout(timer);
    caller.removeEventListener("abort", onCaller);
    ctl.signal.removeEventListener("abort", onLimit);
  });
}

// Outcomes that mean "this request was replaced or cancelled by something other than the user leaving": the engine
// replaced it with a newer start, or refused a start as out of order or already cancelled.
const SUPERSEDED = new Set<SceneErrorCode>(["CANCELLED", "STALE_START", "CANCELLED_BEFORE_START"]);

/**
 * Starts a scene job for `path`, follows it, and resolves with the scene. If `signal` aborts, the browser requests are
 * aborted AND the engine is told to cancel the start attempt by client id, request id and seq, at once (aborting a request
 * alone does not stop work in the engine); the promise then rejects with an AbortError. Every other failure rejects with a
 * SceneError.
 *
 * Ordering of overlapping starts is the engine's job, within a session (see "Sessions" above). As resilience, not as the
 * fix, there are at most two automatic restarts, each with a fresh request id and the next seq: ONE after SESSION_EXPIRED
 * (a new session is opened first), and ONE when a wanted request comes back cancelled or refused as superseded. A second
 * outcome of the same kind is reported as it is.
 */
export async function loadScene(path: string, opts: LoadSceneOptions): Promise<SceneV1> {
  const { signal } = opts;
  if (signal.aborted) throw abortError();
  let sessionRestarted = false;
  let supersededRestarted = false;
  for (let attempt = 0; ; attempt++) {
    try {
      return await runOnce(path, opts, attempt === 0 ? opts.requestId ?? newRequestId() : newRequestId());
    } catch (error) {
      if (!(error instanceof SceneError) || signal.aborted) throw error;
      if (error.code === "SESSION_EXPIRED" && !sessionRestarted) { sessionRestarted = true; continue; }
      if (SUPERSEDED.has(error.code) && !supersededRestarted) { supersededRestarted = true; continue; }
      throw error;
    }
  }
}

async function runOnce(path: string, opts: LoadSceneOptions, requestId: string): Promise<SceneV1> {
  const { signal } = opts;
  const transport = opts.transport ?? defaultTransport;
  const sleep = opts.sleep ?? defaultSleep;
  const pollMs = opts.pollMs ?? 250;
  const startMs = opts.startTimeoutMs ?? 15000;
  const requestMs = opts.requestTimeoutMs ?? 30000;

  // Registered before anything is sent, so leaving at ANY moment cancels the start attempt once there is one (before the
  // session is known, or before the attempt takes its seq, nothing has been sent and there is nothing to cancel).
  let attempt: StartAttempt | null = null;
  const onAbort = () => { if (attempt) cancelSceneRequest(attempt, transport); };
  signal.addEventListener("abort", onAbort, { once: true });
  try {
    const sess = await ensureSession(transport, signal, startMs);
    if (signal.aborted) throw abortError();
    attempt = { clientId: sess.clientId, requestId, seq: ++sess.seq };
    const sent = attempt;
    const started = await limited(
      (s) => transport("start", { path, request_id: sent.requestId, client_id: sent.clientId, seq: sent.seq }, s), signal, startMs,
    );
    if (started.status !== 200) throw errorFromResponse(started.status, started.body);
    const job = readStart(started.body);
    const jobId = job.job_id;
    // The start answer has no progress or error fields, so it becomes a status with those unknown (null).
    let status: JobStatus = {
      job_id: job.job_id, request_id: job.request_id, state: job.state, stage: null, completed: null, total: null, error: null, revision: job.revision,
    };
    let fromStart = true;
    for (;;) {
      if (signal.aborted) throw abortError();
      opts.onProgress?.({ state: status.state, stage: status.stage, completed: status.completed, total: status.total });
      if (status.state === "succeeded") break;
      if (status.state === "failed") {
        // Asking again with a request id the engine still holds returns a failed job without its reason; fetch it.
        if (fromStart) {
          const why = await limited((s) => transport("status", { job_id: jobId, client_id: sent.clientId }, s), signal, requestMs);
          if (why.status !== 200) throw errorFromResponse(why.status, why.body);
          status = readStatus(why.body);
          fromStart = false;
        }
        throw new SceneError(asCode(status.error?.code));
      }
      if (status.state === "cancelled") throw new SceneError("CANCELLED");
      await sleep(pollMs, signal);
      const polled = await limited((s) => transport("status", { job_id: jobId, client_id: sent.clientId }, s), signal, requestMs);
      if (polled.status !== 200) throw errorFromResponse(polled.status, polled.body);
      status = readStatus(polled.body);
      fromStart = false;
    }
    const result = await limited(
      (s) => transport("result", { job_id: jobId, client_id: sent.clientId, ...(status.revision ? { expected_revision: status.revision } : {}) }, s),
      signal, requestMs,
    );
    if (signal.aborted) throw abortError();
    if (result.status !== 200) throw errorFromResponse(result.status, result.body);
    if (!isObject(result.body) || result.body.schema !== "scene/1" || !Array.isArray(result.body.nodes)) {
      throw new SceneError("BAD_RESPONSE");
    }
    return result.body as unknown as SceneV1;
  } catch (error) {
    if (signal.aborted && !isAbort(error)) throw abortError();
    if (error instanceof SceneError) {
      // An answer that never came: stop the attempt too (a no-op if it is already over).
      if (error.code === "TIMEOUT" && attempt) cancelSceneRequest(attempt, transport);
      // The session is gone: forget it, so the next attempt opens a new one (seq starts again at 1).
      if (error.code === "SESSION_EXPIRED" && attempt && session?.clientId === attempt.clientId) session = null;
    }
    throw error;
  } finally {
    signal.removeEventListener("abort", onAbort);
  }
}


// ---- Geometry helpers -------------------------------------------------------------------------------------------

function base64Bytes(text: string): Uint8Array {
  const binary = atob(text);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}

/** Decodes one mesh's little-endian float32 positions and uint32 indices. Throws BAD_RESPONSE when sizes disagree. */
export function decodeMesh(mesh: SceneMesh): { positions: Float32Array; indices: Uint32Array } {
  let positionBytes: Uint8Array;
  let indexBytes: Uint8Array;
  try {
    positionBytes = base64Bytes(mesh.positions_f32le_base64);
    indexBytes = base64Bytes(mesh.indices_u32le_base64);
  } catch {
    throw new SceneError("BAD_RESPONSE");
  }
  if (positionBytes.length !== mesh.vertex_count * 12 || indexBytes.length !== mesh.triangle_count * 12) {
    throw new SceneError("BAD_RESPONSE");
  }
  // Copy into aligned buffers: a Uint8Array view from atob has no alignment promise, and the data is little endian.
  const positions = new Float32Array(mesh.vertex_count * 3);
  const indices = new Uint32Array(mesh.triangle_count * 3);
  const pv = new DataView(positionBytes.buffer, positionBytes.byteOffset, positionBytes.byteLength);
  const iv = new DataView(indexBytes.buffer, indexBytes.byteOffset, indexBytes.byteLength);
  for (let i = 0; i < positions.length; i++) positions[i] = pv.getFloat32(i * 4, true);
  for (let i = 0; i < indices.length; i++) {
    const v = iv.getUint32(i * 4, true);
    if (v >= mesh.vertex_count) throw new SceneError("BAD_RESPONSE");
    indices[i] = v;
  }
  return { positions, indices };
}
