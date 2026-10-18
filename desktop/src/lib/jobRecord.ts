/**
 * One job, three files, linked.
 *
 * A job is the project that came in (original), the copy Studio prepared from it
 * (prepared) and the G-code the slicer produced (sliced). Studio keeps their
 * identities together, so after a restart it can offer to pick the job back up —
 * and say honestly which of the three it can still vouch for.
 *
 * Pure: no storage, no network. The store does those and calls these.
 */

export const JOB_SCHEMA = "job/1";

export type JobRole = "original" | "prepared" | "sliced";
export const JOB_ROLES: JobRole[] = ["original", "prepared", "sliced"];

export interface Fingerprint {
  size_bytes: number;
  /** null when the file was too large to hash: identity is then size-only and never "same". */
  sha256: string | null;
}

export interface LinkedFile {
  path: string;
  name: string;
  /** null until the engine has read the file; a file without one cannot be vouched for. */
  fingerprint: Fingerprint | null;
}

export interface JobRecord {
  schema: typeof JOB_SCHEMA;
  savedAt: string;
  original: LinkedFile;
  prepared: (LinkedFile & { mode: string }) | null;
  sliced: LinkedFile | null;
}

/** What the engine reported for a file, plus the one state only the record knows. */
export type FileState = "same" | "changed" | "missing" | "unreadable" | "unverified";

export type JobCheck = Partial<Record<JobRole, FileState>>;

const nameOf = (path: string) => path.split(/[\\/]/).pop() || path;

export const linked = (path: string, fingerprint: Fingerprint | null = null): LinkedFile =>
  ({ path, name: nameOf(path), fingerprint });

const same = (a: string, b: string) => a === b;

/** A project is opened. The same project keeps its job; any other starts a new one. */
export function openProject(prev: JobRecord | null, path: string, now: string): JobRecord {
  if (prev && same(prev.original.path, path)) return prev;
  return { schema: JOB_SCHEMA, savedAt: now, original: linked(path), prepared: null, sliced: null };
}

/** A prepared copy is linked only to the project it was made from. */
export function linkPrepared(prev: JobRecord | null, projectPath: string, preparedPath: string, mode: string, now: string): JobRecord | null {
  if (!prev || !same(prev.original.path, projectPath)) return prev;
  if (prev.prepared && same(prev.prepared.path, preparedPath) && prev.prepared.mode === mode) return prev;
  return { ...prev, savedAt: now, prepared: { ...linked(preparedPath), mode }, sliced: null };
}

/**
 * A sliced job is linked only while the project it belongs to is open. G-code
 * opened with no project, or beside a different one, is not tied to this job.
 */
export function linkSliced(prev: JobRecord | null, projectPath: string | null, slicedPath: string, now: string): JobRecord | null {
  if (!prev || !projectPath || !same(prev.original.path, projectPath)) return prev;
  if (prev.sliced && same(prev.sliced.path, slicedPath)) return prev;
  return { ...prev, savedAt: now, sliced: linked(slicedPath) };
}

/** The engine's fingerprint arrives later; it applies only to the file it was read from. */
export function withFingerprint(prev: JobRecord | null, role: JobRole, path: string, fingerprint: Fingerprint): JobRecord | null {
  if (!prev) return prev;
  const entry = prev[role];
  if (!entry || !same(entry.path, path)) return prev;
  return { ...prev, [role]: { ...entry, fingerprint } };
}

export function clearSliced(prev: JobRecord | null): JobRecord | null {
  return prev ? { ...prev, sliced: null } : prev;
}

/** Turn the engine's report into one state per linked file. */
export function classify(record: JobRecord, files: Array<{ role: JobRole; status: string }>): JobCheck {
  const out: JobCheck = {};
  for (const role of JOB_ROLES) {
    const entry = record[role];
    if (!entry) continue;
    const report = files.find((f) => f.role === role);
    // A file that is gone or cannot be read is never eligible, fingerprint or not.
    if (report?.status === "missing") { out[role] = "missing"; continue; }
    if (!report || report.status === "unreadable") { out[role] = "unreadable"; continue; }
    if (!entry.fingerprint) { out[role] = "unverified"; continue; }
    switch (report.status) {
      case "same": out[role] = "same"; break;
      case "changed": out[role] = "changed"; break;
      case "missing": out[role] = "missing"; break;
      case "unverified": out[role] = "unverified"; break;
      default: out[role] = "unreadable";
    }
  }
  return out;
}

/**
 * Which files restoring would reopen. Unchanged files only, unless the person
 * names a changed or unverifiable one; missing and unreadable files never.
 */
export function restorable(check: JobCheck, accepted: ReadonlySet<JobRole>): JobRole[] {
  return JOB_ROLES.filter((role) => {
    const state = check[role];
    // What was made from the project is offered back only while the project is
    // provably what it was; otherwise only if the person names it.
    if (state === "same") {
      if (role === "original" || accepted.has(role)) return true;
      if (check.original !== "same") return false;
      // The G-code came from the prepared copy: unnamed, it needs that copy intact too.
      return role !== "sliced" || check.prepared === undefined || check.prepared === "same";
    }
    return (state === "changed" || state === "unverified") && accepted.has(role);
  });
}

/**
 * The one answer to "what would Reopen do?", shared by the card and the store.
 * Naming a changed original reopens only the original: what was made from the
 * old file is not presented as the result of the new one.
 */
export function planFor(check: JobCheck, accepted: ReadonlySet<JobRole>): JobRole[] {
  const plan = restorable(check, accepted).filter((role) => role !== "prepared");
  return plan.includes("original") && check.original !== "same" ? ["original"] : plan;
}

/** Defensive parse of what local storage holds: anything off-shape is "no saved job". */
export function parseRecord(raw: string | null): JobRecord | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw);
    if (!v || v.schema !== JOB_SCHEMA || typeof v.savedAt !== "string") return null;
    const file = (x: unknown): LinkedFile | null => {
      const f = x as LinkedFile | null;
      if (!f || typeof f.path !== "string" || !f.path) return null;
      const fp = f.fingerprint;
      const ok = fp && Number.isInteger(fp.size_bytes) && fp.size_bytes >= 0 &&
        (fp.sha256 === null || (typeof fp.sha256 === "string" && fp.sha256.length === 64));
      return { path: f.path, name: nameOf(f.path), fingerprint: ok ? { size_bytes: fp.size_bytes, sha256: fp.sha256 } : null };
    };
    const original = file(v.original);
    if (!original) return null;
    const prepared = file(v.prepared);
    const sliced = file(v.sliced);
    return {
      schema: JOB_SCHEMA, savedAt: v.savedAt, original,
      prepared: prepared ? { ...prepared, mode: typeof v.prepared?.mode === "string" ? v.prepared.mode : "unknown" } : null,
      sliced,
    };
  } catch {
    return null;
  }
}
