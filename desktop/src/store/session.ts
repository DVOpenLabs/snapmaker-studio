import { create } from "zustand";
import { doctor as apiDoctor, convert as apiConvert, diff as apiDiff, type ConversionResult, type PrepareMode, type SettingsSummary } from "@/api";

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
  /** Select a file and immediately run Doctor on it. */
  setFile: (path: string) => void;
  runDoctor: () => Promise<void>;
  setPrepareMode: (mode: PrepareMode) => void;
  runConvert: (mode?: PrepareMode) => Promise<void>;
  previewConvert: () => Promise<void>;
  runDiff: () => Promise<void>;
  reset: () => void;
}

export const useSession = create<SessionState>((set, get) => ({
  file: null,
  doctor: blank(),
  convert: blank(),
  prepareMode: "preserve",
  settingsSummary: null,
  preview: blank(),
  diff: blank(),

  setFile: (path) => {
    requestGeneration++;
    set({ file: toFileRef(path), doctor: blank(), convert: blank(), diff: blank(), prepareMode: "preserve", settingsSummary: null, preview: blank() });
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
    set({ prepareMode, convert: { status: "loading", data: null, error: null }, diff: blank(), settingsSummary: null });
    try {
      const data = await apiConvert(p, undefined, prepareMode);
      if (requestGeneration !== generation || get().file?.path !== p) return;
      set({ convert: { status: "done", data, error: null }, settingsSummary: data.settings_summary ?? null });
      // Auto-compare only when there's a source *project* to diff against.
      // STL inputs are wrapped into a brand-new U1 project — nothing to compare.
      if (file.ext === "3mf") void get().runDiff();
    } catch (e: any) {
      if (requestGeneration !== generation || get().file?.path !== p) return;
      set({ convert: { status: "error", data: null, error: String(e?.message ?? e) }, settingsSummary: null });
    }
  },

  previewConvert: async () => {
    const file = get().file;
    if (!file || get().doctor.data?.prepare_blocked) return;
    const p = file.path;
    const generation = ++requestGeneration;
    set({ preview: { status: "loading", data: null, error: null } });
    try {
      const data = await apiConvert(p, undefined, "preserve", true);
      if (requestGeneration !== generation || get().file?.path !== p) return;
      set({ preview: { status: "done", data, error: null }, settingsSummary: data.settings_summary ?? null });
    } catch (e: any) {
      if (requestGeneration !== generation || get().file?.path !== p) return;
      set({ preview: { status: "error", data: null, error: String(e?.message ?? e) } });
    }
  },

  runDiff: async () => {
    const file = get().file;
    const out = get().convert.data?.output_path;
    if (!file || !out) return;
    const p = file.path;
    set({ diff: { status: "loading", data: null, error: null } });
    try {
      const data = await apiDiff(p, out);
      if (get().file?.path !== p) return;
      set({ diff: { status: "done", data, error: null } });
    } catch (e: any) {
      if (get().file?.path !== p) return;
      set({ diff: { status: "error", data: null, error: String(e?.message ?? e) } });
    }
  },

  reset: () => set({ file: null, doctor: blank(), convert: blank(), diff: blank(), prepareMode: "preserve", settingsSummary: null, preview: blank() }),
}));
