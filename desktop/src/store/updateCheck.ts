import { create } from "zustand";
import type { UpdateInfo } from "@/api";

interface UpdateCheckState {
  /** The opt-in automatic check's result, if it has run and found something
   * to say this launch. Set once, by App's startup effect — never by the
   * manual "Check GitHub now" button, which keeps its own local state. */
  autoResult: UpdateInfo | null;
  setAutoResult: (info: UpdateInfo) => void;
}

export const useUpdateCheckStore = create<UpdateCheckState>((set) => ({
  autoResult: null,
  setAutoResult: (info) => set({ autoResult: info }),
}));
