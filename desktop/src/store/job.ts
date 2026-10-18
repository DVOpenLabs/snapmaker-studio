import { create } from "zustand";
import { jobCheck, type JobCheckEntry } from "@/api";
import {
  classify, clearSliced, linkPrepared, linkSliced, openProject, parseRecord, restorable, withFingerprint,
  JOB_SCHEMA, linked, type JobCheck, type JobRecord, type JobRole,
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
      if (checkGeneration !== generation || get().record !== record) return;
      set({ phase: "done", check: classify(record, report.files), error: null });
    } catch (e: any) {
      if (checkGeneration !== generation || get().record !== record) return;
      set({ phase: "error", check: {}, error: String(e?.message ?? e) });
    }
  },

  restore: (accepted) => {
    const { record, check, phase } = get();
    if (!record || phase !== "done") return;
    let plan = restorable(check, accepted);
    let next = record;
    // A changed original means the prepared copy and sliced job were not made from
    // what is on disk now. Reopen the file, but do not present them as its results.
    if (plan.includes("original") && check.original !== "same") {
      next = { schema: JOB_SCHEMA, savedAt: new Date().toISOString(), original: linked(record.original.path), prepared: null, sliced: null };
      plan = plan.filter((role) => role === "original");
      set({ record: next });
      write(next);
      void fingerprint("original", next.original.path);
    }
    // Naming a changed G-code adopts what is on disk now as the sliced identity.
    const adoptSliced = plan.includes("sliced") && next.sliced && check.sliced !== "same";
    if (adoptSliced && next.sliced) {
      next = { ...next, sliced: { ...next.sliced, fingerprint: null } };
      set({ record: next });
      write(next);
    }
    if (plan.includes("original")) useSession.getState().setFile(record.original.path);
    if (plan.includes("sliced") && next.sliced) useSliced.getState().setSliced(next.sliced.path);
    if (adoptSliced && next.sliced) void fingerprint("sliced", next.sliced.path);
    set({ ...idle });
  },

  forget: () => {
    checkGeneration++;
    write(null);
    set({ record: null, ...idle });
  },
}));

function update(next: JobRecord | null) {
  if (next === useJob.getState().record) return;
  write(next);
  useJob.setState({ record: next, ...idle });
}

/** Read the file's size and hash; it applies only if that file is still the one linked. */
async function fingerprint(role: JobRole, path: string) {
  try {
    const report = await jobCheck([{ role, path }]);
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
      update(next);
      if (next !== before) void fingerprint("original", s.file.path);
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
      update(clearSliced(before));
      return;
    }
    const next = linkSliced(before, useSession.getState().file?.path ?? null, s.path, now());
    if (next !== before) {
      update(next);
      void fingerprint("sliced", s.path);
    }
  });
  return () => { offSession(); offSliced(); };
}
