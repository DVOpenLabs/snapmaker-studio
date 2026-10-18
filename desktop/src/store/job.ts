import { create } from "zustand";
import { jobCheck, type JobCheckEntry } from "@/api";
import {
  classify, clearSliced, linkPrepared, linkSliced, openProject, parseRecord, planFor, withFingerprint,
  JOB_SCHEMA, linked, type Fingerprint, type JobCheck, type JobRecord, type JobRole,
} from "@/lib/jobRecord";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";

const KEY = "snapstudio.job.v1";

function read(): JobRecord | null {
  try {
    return parseRecord(window.localStorage.getItem(KEY));
  } catch {
    return null;                 // private mode, or no storage at all
  }
}

function write(record: JobRecord | null) {
  try {
    if (record) window.localStorage.setItem(KEY, JSON.stringify(record));
    else window.localStorage.removeItem(KEY);
  } catch {
    /* resuming is a convenience, never a requirement */
  }
}

export type CheckPhase = "idle" | "checking" | "done" | "error";

/**
 * The job in hand: original, prepared copy and sliced G-code, linked, and kept
 * on this machine so it can be picked up after a restart.
 *
 * Restoring only reopens files for review. It never prepares, slices or sends,
 * and it never trusts a file it could not read back as the one that was recorded.
 */
interface JobState {
  record: JobRecord | null;
  /**
   * True once the project is known to be what the record says (made this session,
   * or checked against its fingerprint). Until then its earlier prepared copy and
   * G-code are not presented as its results.
   */
  verified: boolean;
  phase: CheckPhase;
  check: JobCheck;
  error: string | null;
  /** Compare the saved job's files with what was recorded. Read-only. */
  runCheck: () => Promise<void>;
  /** Reopen the unchanged files, plus any changed one the person named. */
  restore: (accepted: ReadonlySet<JobRole>) => void;
  forget: () => void;
}

const idle = { phase: "idle" as CheckPhase, check: {} as JobCheck, error: null };
let checkGeneration = 0;

export const useJob = create<JobState>((set, get) => ({
  record: read(),
  verified: false,
  ...idle,

  runCheck: async () => {
    const record = get().record;
    if (!record) return;
    const generation = ++checkGeneration;
    set({ phase: "checking", check: {}, error: null });
    const entries: JobCheckEntry[] = (["original", "prepared", "sliced"] as JobRole[]).flatMap((role) => {
      const entry = record[role];
      return entry ? [{ role, path: entry.path, ...(entry.fingerprint ? { expected: entry.fingerprint } : {}) }] : [];
    });
    try {
      const report = await jobCheck(entries);
      // The saved job may have been replaced or forgotten while the engine read its files.
      if (checkGeneration !== generation) return;
      // The job changed under the check (a file was linked or adopted): its answer is stale.
      if (get().record !== record) { set({ ...idle }); return; }
      set({ phase: "done", check: classify(record, report.files), error: null });
    } catch (e: any) {
      if (checkGeneration !== generation) return;
      if (get().record !== record) { set({ ...idle }); return; }
      set({ phase: "error", check: {}, error: String(e?.message ?? e) });
    }
  },

  restore: (accepted) => {
    const { record, check, phase } = get();
    if (!record || phase !== "done") return;
    let plan = planFor(check, accepted);
    let next = record;
    // A changed original means the prepared copy and sliced job were not made from
    // what is on disk now. Reopen the file, but do not present them as its results.
    if (plan.includes("original") && check.original !== "same") {
      next = { schema: JOB_SCHEMA, savedAt: new Date().toISOString(), original: linked(record.original.path), prepared: null, sliced: null };
      invalidateFingerprints();
      set({ record: next, verified: true });
      write(next);
      // A G-code already open belongs to the old file, not to the one being reopened.
      useSliced.getState().clear();
      void fingerprint("original", next.original.path);
    }
    // Naming a changed G-code adopts what is on disk now as the sliced identity.
    const adoptSliced = plan.includes("sliced") && next.sliced && check.sliced !== "same";
    if (adoptSliced && next.sliced) {
      next = { ...next, sliced: { ...next.sliced, fingerprint: null } };
      set({ record: next });
      write(next);
    }
    if (plan.includes("original")) {
      if (check.original === "same") set({ verified: true });
      useSession.getState().setFile(record.original.path);
    }
    if (plan.includes("sliced") && next.sliced) useSliced.getState().setSliced(next.sliced.path);
    if (adoptSliced && next.sliced) rebaselineSliced(next.sliced.path);
    set({ ...idle });
  },

  forget: () => {
    checkGeneration++;
    invalidateFingerprints();
    write(null);
    set({ record: null, verified: false, ...idle });
  },
}));

function update(next: JobRecord | null, verified?: boolean) {
  if (next === useJob.getState().record) return;
  write(next);
  useJob.setState({ record: next, ...(verified === undefined ? {} : { verified }), ...idle });
}

/**
 * Each fingerprint request is bound to the moment it was asked: when the file it
 * was reading is replaced, adopted or forgotten, its late answer is discarded
 * even if the same path is linked again.
 */
const fingerprintSeq: Record<JobRole, number> = { original: 0, prepared: 0, sliced: 0 };
function invalidateFingerprints() {
  for (const role of Object.keys(fingerprintSeq) as JobRole[]) fingerprintSeq[role]++;
}

/** Read the file's size and hash; it applies only if that file is still the one linked. */
async function fingerprint(role: JobRole, path: string) {
  const seq = ++fingerprintSeq[role];
  try {
    const report = await jobCheck([{ role, path }]);
    if (fingerprintSeq[role] !== seq) return;
    const observed = report.files[0]?.observed;
    if (report.files[0]?.status !== "recorded" || !observed) return;
    const next = withFingerprint(useJob.getState().record, role, path, observed);
    if (next !== useJob.getState().record) {
      write(next);
      useJob.setState({ record: next });
    }
  } catch {
    /* no fingerprint means "cannot be vouched for", which is the honest default */
  }
}

/**
 * Link the files as the person works. Call once, at startup; returns the unsubscribe.
 * Nothing here starts work: it only notes which files belong together.
 */
export function trackJob(): () => void {
  const now = () => new Date().toISOString();
  const offSession = useSession.subscribe((s, prev) => {
    if (s.file && s.file.path !== prev.file?.path) {
      const before = useJob.getState().record;
      const next = openProject(before, s.file.path, now());
      if (next !== before) {
        invalidateFingerprints();
        update(next, true);
        void fingerprint("original", s.file.path);
      } else if (next && !useJob.getState().verified) {
        void verifyOpened(next);
      }
    }
    const out = s.convert.status === "done" && s.convert.data && !s.convert.data.blocked && s.convert.data.validated_ok
      ? s.convert.data.output_path : null;
    const was = prev.convert.status === "done" ? prev.convert.data?.output_path : null;
    if (out && out !== was && s.file) {
      const next = linkPrepared(useJob.getState().record, s.file.path, out, String(s.convert.data?.prepare_mode ?? "unknown"), now());
      if (next !== useJob.getState().record) {
        update(next);
        void fingerprint("prepared", out);
      }
    }
  });
  const offSliced = useSliced.subscribe((s, prev) => {
    if (s.path === prev.path) return;
    const before = useJob.getState().record;
    if (!s.path) {
      sliceView = null;
      update(clearSliced(before));
      return;
    }
    watchSliceView(s.path);
    const next = linkSliced(before, useSession.getState().file?.path ?? null, s.path, now());
    if (next !== before) update(next);
  });
  return () => { offSession(); offSliced(); };
}

/**
 * The same project was opened by hand after a restart, bypassing the card. Its
 * earlier prepared copy and G-code count as its results only if the project is
 * still the file that was recorded; otherwise the job starts over.
 */
async function verifyOpened(record: JobRecord) {
  const path = record.original.path;
  const fresh = () => {
    if (useJob.getState().record !== record) return;
    invalidateFingerprints();
    update({ ...openProject(null, path, new Date().toISOString()) }, true);
    void fingerprint("original", path);
  };
  if (!record.prepared && !record.sliced) {
    useJob.setState({ verified: true });
    if (!record.original.fingerprint) void fingerprint("original", path);
    return;
  }
  if (!record.original.fingerprint) return fresh();
  try {
    const report = await jobCheck([{ role: "original", path, expected: record.original.fingerprint }]);
    if (useJob.getState().record !== record || useSession.getState().file?.path !== path) return;
    if (report.files[0]?.status === "same") useJob.setState({ verified: true });
    else fresh();
  } catch {
    if (useSession.getState().file?.path === path) fresh();
  }
}

/**
 * What Studio last read from the open G-code: its size, hash and exact modification
 * time. A path alone is not an identity — Orca writes each new export over the same
 * name — so the watcher's sightings of this path are compared with this.
 *
 * One read at a time, and every answer is bound to the view it was asked for: a
 * path change or a clear makes any answer in flight stale. The same read fills the
 * job record's fingerprint, so there is a single source of the sliced identity.
 */
interface SliceView {
  path: string;
  reading: boolean;
  /** null until a read succeeds; sightings then trigger a read instead of being compared. */
  base: Fingerprint | null;
}
let sliceView: SliceView | null = null;

function watchSliceView(path: string) {
  const view: SliceView = { path, reading: false, base: null };
  sliceView = view;
  void readSliced(view, undefined, false);
}

async function readSliced(view: SliceView, verdict: string | undefined, sighted: boolean) {
  view.reading = true;
  try {
    const report = await jobCheck([{ role: "sliced", path: view.path }]);
    if (sliceView !== view) return;                       // the path changed or was cleared meanwhile
    const observed = report.files[0]?.observed;
    if (report.files[0]?.status !== "recorded" || !observed) return;
    const before = view.base;
    view.base = observed;
    // Same bytes only when both hashes exist and agree; a size-only identity never counts.
    const sameBytes = !!before && before.sha256 !== null && observed.sha256 !== null &&
      before.size_bytes === observed.size_bytes && before.sha256 === observed.sha256;
    const replaced = sighted && !sameBytes;
    const record = useJob.getState().record;
    if (record?.sliced && record.sliced.path === view.path) {
      // A replacement that is another project's slice is not this job's result.
      update(replaced && verdict === "no_match" ? clearSliced(record) : withFingerprint(record, "sliced", view.path, observed));
    }
    if (replaced) useSliced.getState().refresh();
  } catch {
    /* unreadable now: keep what is shown; the next completed sighting reads again */
  } finally {
    if (sliceView === view) view.reading = false;
  }
}

export interface SightedExport {
  path: string;
  size_bytes: number;
  /** The file's exact modification time as the watcher saw it (text; nanoseconds). */
  modified_ns?: string;
  complete: boolean;
  /** Provenance verdict against the open project, when the watcher computed one. */
  verdict?: string;
}

/**
 * The folder watcher saw a file at the path that is open. Only a completed file
 * (the watcher's own settle check) whose size or exact modification time differs
 * from what was last read is read again; an untouched file is never hashed, however
 * often it is polled. When the bytes really differ, the saved identity is replaced
 * and everything shown from the old bytes is read again. If the last read failed or
 * never happened, the next completed sighting reads.
 */
export function observeSliced(sighting: SightedExport) {
  const view = sliceView;
  if (!view || view.path !== sighting.path || !sighting.complete || view.reading) return;
  const base = view.base;
  const untouched = !!base && base.size_bytes === sighting.size_bytes &&
    (sighting.modified_ns === undefined || base.mtime_ns === sighting.modified_ns);
  if (untouched) return;
  void readSliced(view, sighting.verdict, true);
}

/** The open G-code was reopened under its own name by a restore: read it afresh. */
export function rebaselineSliced(path: string) {
  watchSliceView(path);
  useSliced.getState().refresh();
}
