import { create } from "zustand";
import { buildGenerateBody, checkLuminaService, generateWithLumina, type LuminaForm, type LuminaFormat, type LuminaGenerateResponse, type LuminaStatusResponse } from "./luminaApi";

type SavedResult = { id: number; result: LuminaGenerateResponse; outDir?: string };
type State = {
  form: LuminaForm; busy: boolean; error: string | null; status: LuminaStatusResponse | null;
  result: LuminaGenerateResponse | null; resultDirectory?: string; earlierFiles: SavedResult[];
  change: (form: LuminaForm) => void;
  run: (kind: "check" | "generate", formats: readonly LuminaFormat[]) => Promise<void>;
  clear: () => void;
};
const emptyForm = (): LuminaForm => ({ serviceUrl: "", imagePath: "", lutName: "", format: "", widthMm: "60" });
let revision = 0;
let active = false;
let entrySequence = 0;

/** In-memory only. Navigation does not cancel or reissue a request. No disk persistence or automatic opening. */
export const useLuminaSession = create<State>((set, get) => ({
  form: emptyForm(), busy: false, error: null, status: null, result: null, earlierFiles: [],
  change: form => {
    revision++;
    set(state => ({ form: { ...form }, result: null, resultDirectory: undefined, status: null, error: null,
      earlierFiles: state.result ? [...state.earlierFiles, { id: ++entrySequence, result: state.result, outDir: state.resultDirectory }].slice(-10) : state.earlierFiles }));
  },
  run: async (kind, formats) => {
    if (active) return;
    active = true;
    const token = ++revision, form = { ...get().form };
    set(state => ({ busy: true, error: null, status: null, result: null, resultDirectory: undefined,
      earlierFiles: state.result ? [...state.earlierFiles, { id: ++entrySequence, result: state.result, outDir: state.resultDirectory }].slice(-10) : state.earlierFiles }));
    try {
      if (kind === "check") {
        const status = await checkLuminaService(form.serviceUrl);
        if (token === revision) set({ status });
      } else {
        const result = await generateWithLumina(buildGenerateBody(form, formats));
        if (token === revision) set({ result, resultDirectory: form.outDir });
        else set(state => ({ earlierFiles: [...state.earlierFiles, { id: ++entrySequence, result, outDir: form.outDir }].slice(-10) }));
      }
    } catch (cause) {
      if (token === revision) set({ error: cause instanceof Error ? cause.message : "The request failed." });
    } finally { active = false; set({ busy: false }); }
  },
  clear: () => {
    if (active) return; // This cannot cancel the service's work.
    revision++;
    set({ form: emptyForm(), busy: false, error: null, status: null, result: null, resultDirectory: undefined, earlierFiles: [] });
  },
}));
