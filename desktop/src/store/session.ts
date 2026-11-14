import { create } from "zustand";
import { useSliced } from "@/store/sliced";
import { doctor as apiDoctor, convert as apiConvert, diff as apiDiff, type ConversionResult, type PrepareMode, type SettingsSummary } from "@/api";
import { NO_SETUP, prepareBlockedBy, selectionFromEvaluate, selectionFromFailure, topologyToSend, type PrepareSetupSelection } from "@/lib/prepareSetup";
import { buildEvaluateBody, evaluateSetup } from "@/lib/setupsApi";

export interface FileRef {
  path: string;
  name: string;
  ext: "stl" | "3mf" | string;
}

export type Phase = "idle" | "loading" | "done" | "error";

export interface AsyncState<T> {
  status: Phase;
  data: T | null;
  error: string | null;
}

const blank = <T>(): AsyncState<T> => ({ status: "idle", data: null, error: null });
let requestGeneration = 0;

function toFileRef(path: string): FileRef {
  const name = path.split(/[\\/]/).pop() || path;
  const ext = (name.split(".").pop() || "").toLowerCase();
  return { path, name, ext };
}

interface SessionState {
  file: FileRef | null;
  doctor: AsyncState<any>;
  convert: AsyncState<any>;
  prepareMode: PrepareMode;
  settingsSummary: SettingsSummary | null;
  preview: AsyncState<ConversionResult>;
  diff: AsyncState<any>;
  /** The printer setup Prepare and its preview use for the open project, if the person chose one. */
  prepareSetup: PrepareSetupSelection;
  /** Read a host and make what it reports the chosen setup. The key is used for this one request and never kept. */
  readPrepareSetup: (input: { host: string; port?: string; key?: string }, projectPath?: string) => Promise<void>;
  /** Drop the chosen setup, and with it any preview or prepared copy made under it. */
  clearPrepareSetup: () => void;
  /** Prepare with no setup: clears the choice first, so nothing from it is sent. */
  runConvertWithoutSetup: (mode?: PrepareMode) => Promise<void>;
  /** Select a file and immediately run Doctor on it. */
  setFile: (path: string) => void;
  runDoctor: () => Promise<void>;
  setPrepareMode: (mode: PrepareMode) => void;
  runConvert: (mode?: PrepareMode) => Promise<void>;
  /** A Prepare started elsewhere for this project: forget any earlier copy until the new one is validated. */
  beginPrepare: (sourcePath: string) => number | null;
  /** A Prepare that finished elsewhere: shared state only takes a validated, unblocked copy of the project that is open now. */
  publishPrepared: (revision: number | null | undefined, sourcePath: string, data: any) => void;
  previewConvert: () => Promise<void>;
  runDiff: () => Promise<void>;
  reset: () => void;
}

/**
 * Bumped whenever the open project changes (or is reset), a preparation starts anywhere, or Prepare is run through
 * the store: a preparation published later than any of these belongs to a project, or a request, that is gone.
 */
let prepareRevision = 0;
/** Bumped whenever the chosen setup changes or is dropped. A response made under an older value is discarded. */
let setupSeq = 0;

export const useSession = create<SessionState>((set, get) => ({
  file: null,
  doctor: blank(),
  convert: blank(),
  prepareMode: "preserve",
  settingsSummary: null,
  preview: blank(),
  diff: blank(),
  prepareSetup: NO_SETUP(0),

  setFile: (path) => {
    // A sliced file opened beside another project is not this project's slice.
    if (get().file?.path !== path) useSliced.getState().clear();
    requestGeneration++;
    prepareRevision++;
    // The setup belongs to the project it was chosen for, even when the same path is opened again.
    set({ file: toFileRef(path), doctor: blank(), convert: blank(), diff: blank(), prepareMode: "preserve", settingsSummary: null, preview: blank(), prepareSetup: NO_SETUP(++setupSeq) });
    void get().runDoctor();
  },

  runDoctor: async () => {
    const file = get().file;
    if (!file) return;
    const p = file.path;
    const generation = ++requestGeneration;
    set({ doctor: { status: "loading", data: null, error: null } });
    try {
      const data = await apiDoctor(p);
      if (requestGeneration !== generation || get().file?.path !== p) return;
      set({ doctor: { status: "done", data, error: null } });
    } catch (e: any) {
      if (requestGeneration !== generation || get().file?.path !== p) return;
      set({ doctor: { status: "error", data: null, error: String(e?.message ?? e) } });
    }
  },

  setPrepareMode: (prepareMode) => set({ prepareMode }),

  runConvert: async (mode) => {
    const file = get().file;
    if (!file || get().doctor.data?.prepare_blocked) return;
    const p = file.path;
    const generation = ++requestGeneration;
    const prepareMode = mode ?? get().prepareMode;
    const revision = ++prepareRevision;
    const setup = get().prepareSetup;
    const blockedBy = prepareBlockedBy(setup, p);
    if (blockedBy) {
      set({ prepareMode, convert: { status: "error", data: null, error: blockedBy }, diff: blank(), settingsSummary: null });
      return;
    }
    const sent = setup.token;
    set({ prepareMode, convert: { status: "loading", data: null, error: null }, diff: blank(), settingsSummary: null });
    try {
      const topology = topologyToSend(setup, p);
      const data = await (topology ? apiConvert(p, undefined, prepareMode, false, undefined, topology) : apiConvert(p, undefined, prepareMode));
      if (requestGeneration !== generation || prepareRevision !== revision || setupSeq !== sent || get().file?.path !== p) return;
      set({ convert: { status: "done", data, error: null }, settingsSummary: data.settings_summary ?? null });
      // Auto-compare only when there's a source *project* to diff against.
      // STL inputs are wrapped into a brand-new U1 project — nothing to compare.
      if (file.ext === "3mf") void get().runDiff();
    } catch (e: any) {
      if (requestGeneration !== generation || prepareRevision !== revision || setupSeq !== sent || get().file?.path !== p) return;
      set({ convert: { status: "error", data: null, error: String(e?.message ?? e) }, settingsSummary: null });
    }
  },

  beginPrepare: (sourcePath) => {
    if (get().file?.path !== sourcePath) return null;
    const revision = ++prepareRevision;
    set({ convert: blank(), diff: blank(), settingsSummary: null });
    return revision;
  },

  publishPrepared: (revision, sourcePath, data) => {
    // The project may have changed (even to the same path again) or a newer preparation may have started while this one ran.
    if (revision == null || revision !== prepareRevision || get().file?.path !== sourcePath) return;
    const out = data?.output_path;
    const usable = !!data && !data.blocked && data.validated_ok === true && typeof out === "string" && out !== "" && out !== sourcePath;
    set(usable
      ? { convert: { status: "done", data, error: null }, diff: blank(), settingsSummary: data.settings_summary ?? null }
      : { convert: blank(), diff: blank(), settingsSummary: null });
    // The comparison belongs to this copy: same rule as runConvert (a 3MF has a project to compare against).
    if (usable && get().file?.ext === "3mf") void get().runDiff();
  },

  previewConvert: async () => {
    const file = get().file;
    if (!file || get().doctor.data?.prepare_blocked) return;
    const p = file.path;
    const generation = ++requestGeneration;
    const setup = get().prepareSetup;
    const blockedBy = prepareBlockedBy(setup, p);
    if (blockedBy) {
      set({ preview: { status: "error", data: null, error: blockedBy } });
      return;
    }
    const sent = setup.token;
    set({ preview: { status: "loading", data: null, error: null } });
    try {
      // The review shows what the final Prepare will do, so it is asked with the same setup.
      const topology = topologyToSend(setup, p);
      const data = await (topology ? apiConvert(p, undefined, "preserve", true, undefined, topology) : apiConvert(p, undefined, "preserve", true));
      if (requestGeneration !== generation || setupSeq !== sent || get().file?.path !== p) return;
      set({ preview: { status: "done", data, error: null }, settingsSummary: data.settings_summary ?? null });
    } catch (e: any) {
      if (requestGeneration !== generation || setupSeq !== sent || get().file?.path !== p) return;
      set({ preview: { status: "error", data: null, error: String(e?.message ?? e) } });
    }
  },

  runDiff: async () => {
    const file = get().file;
    const out = get().convert.data?.output_path;
    if (!file || !out) return;
    const p = file.path;
    const revision = prepareRevision;
    set({ diff: { status: "loading", data: null, error: null } });
    try {
      const data = await apiDiff(p, out);
      if (prepareRevision !== revision || get().file?.path !== p) return;
      set({ diff: { status: "done", data, error: null } });
    } catch (e: any) {
      if (prepareRevision !== revision || get().file?.path !== p) return;
      set({ diff: { status: "error", data: null, error: String(e?.message ?? e) } });
    }
  },

  readPrepareSetup: async (input, projectPath) => {
    // Screens that prepare a project other than the session's own pass its path; the setup is bound to that path.
    const p = projectPath ?? get().file?.path;
    if (!p) return;
    let body;
    try {
      body = buildEvaluateBody({ host: input.host, port: input.port, key: input.key });
    } catch (e) {
      throw e instanceof Error ? e : new Error("Check the host and port.");
    }
    const base = { token: ++setupSeq, projectPath: p, label: body.port ? `${body.host}:${body.port}` : body.host };
    // A new read drops the old choice and everything made under it before the answer arrives.
    prepareRevision++;
    set({ prepareSetup: { status: "reading", ...base }, convert: blank(), diff: blank(), preview: blank(), settingsSummary: null });
    // Opening another project, clearing, or a newer read all move setupSeq: this answer then belongs to nothing.
    const stale = () => setupSeq !== base.token;
    try {
      const res = await evaluateSetup(body);
      if (stale()) return;
      set({ prepareSetup: selectionFromEvaluate(base, res) });
    } catch (e) {
      if (stale()) return;
      set({ prepareSetup: selectionFromFailure(base, e) });
    }
  },

  clearPrepareSetup: () => {
    if (get().prepareSetup.status === "none") return;
    prepareRevision++;
    set({ prepareSetup: NO_SETUP(++setupSeq), convert: blank(), diff: blank(), preview: blank(), settingsSummary: null });
  },

  runConvertWithoutSetup: async (mode) => {
    get().clearPrepareSetup();
    await get().runConvert(mode);
  },

  reset: () => {
    prepareRevision++;
    set({ file: null, doctor: blank(), convert: blank(), diff: blank(), prepareMode: "preserve", settingsSummary: null, preview: blank(), prepareSetup: NO_SETUP(++setupSeq) });
  },
}));
