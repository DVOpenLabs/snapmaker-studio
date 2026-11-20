import { create } from "zustand";
export type CalibrationDraft = {
  source: "ditherforge_txt" | "kromacut_json"; content: string; family: "frontlit" | "backlit";
  layerHeight: string; measurementText: string; ownedText: string; nozzle: string; material: string; model: string; firstLayer: string;
};
const empty = (): CalibrationDraft => ({ source: "ditherforge_txt", content: "#E94B35 td=0.8 Vermilion\n#2878B8 td Blue\n#F2C14E td=1.1 Ochre",
  family: "frontlit", layerHeight: "0.20", measurementText: "", ownedText: "", nozzle: "0.4", material: "PLA", model: "", firstLayer: "0.20" });
/** Unsaved inputs only, in app memory. No browser storage or automatic evaluation. */
export const useCalibrationDraft = create<{ draft: CalibrationDraft; update: (changes: Partial<CalibrationDraft>) => void; reset: () => void }>(set => ({
  draft: empty(), update: changes => set(state => ({ draft: { ...state.draft, ...changes } })), reset: () => set({ draft: empty() }),
}));
