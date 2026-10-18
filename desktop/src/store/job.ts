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
    if (adoptSliced && next.sliced) void fingerprint("sliced", next.sliced.path);
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
    if (next !== before) {
      update(next);
      void fingerprint("sliced", s.path);
    }
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
 * What Studio last read from the open G-code: its identity and when. A path alone
 * is not an identity — Orca writes each new export over the same name — so the
 * watcher's sightings of this path are compared with this.
 */
let sliceView: { path: string; fp: Fingerprint | null; at: number; seq: number } | null = null;
let viewSeq = 0;
/** Clock slack between the file system's timestamps and ours. */
const TIMESTAMP_SLACK_MS = 2000;

function watchSliceView(path: string) {
  const seq = ++viewSeq;
  sliceView = { path, fp: null, at: Date.now(), seq };
  jobCheck([{ role: "sliced", path }]).then((report) => {
    const observed = report.files[0]?.observed;
    if (sliceView?.seq === seq && report.files[0]?.status === "recorded" && observed) sliceView.fp = observed;
  }).catch(() => { /* no identity yet: the next sighting cannot be compared, so nothing is claimed */ });
}

export interface SightedExport {
  path: string;
  size_bytes: number;
  age_seconds: number;
  complete: boolean;
  /** Provenance verdict against the open project, when the watcher computed one. */
  verdict?: string;
}

/**
 * The folder watcher saw a file at the path that is open. Only a completed file
 * (the watcher's own settle check) that is a different size, or was written after
 * the open copy was read, is re-read; nothing is hashed on a routine poll. When
 * the bytes really differ, the saved identity is replaced and everything shown
 * from the old bytes is read again. A late answer never replaces a newer one.
 */
export async function observeSliced(sighting: SightedExport, now = Date.now()) {
  const view = sliceView;
  if (!view || view.path !== sighting.path || !sighting.complete || !view.fp) return;
  const wroteAt = now - sighting.age_seconds * 1000;
  if (sighting.size_bytes === view.fp.size_bytes && wroteAt <= view.at + TIMESTAMP_SLACK_MS) return;
  const seq = ++viewSeq;
  view.seq = seq;
  view.at = now;
  try {
    const report = await jobCheck([{ role: "sliced", path: sighting.path }]);
    const observed = report.files[0]?.observed;
    if (sliceView?.seq !== seq || useSliced.getState().path !== sighting.path) return;
    if (report.files[0]?.status !== "recorded" || !observed) return;
    const before = sliceView.fp;
    sliceView.fp = observed;
    if (before && observed.size_bytes === before.size_bytes && observed.sha256 === before.sha256) return;
    const record = useJob.getState().record;
    if (record?.sliced && record.sliced.path === sighting.path) {
      // A replacement that is another project's slice is not this job's result.
      update(sighting.verdict === "no_match"
        ? clearSliced(record)
        : { ...record, sliced: { ...record.sliced, fingerprint: observed } });
    }
    useSliced.getState().refresh();
  } catch {
    /* unreadable now: keep what is shown; the next sighting tries again */
  }
}
