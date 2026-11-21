import { create } from "zustand";
import type { Dispatch, SetStateAction } from "react";
import type { CreativeFormat } from "@/lib/creativeApi";
type Inputs = { path: string; format: CreativeFormat; outDir: string };
const empty = (): Inputs => ({ path: "", format: "auto", outDir: "" });
/** Input draft only. Reports/material choices and credentials are not retained or replayed. */
export const useCreativeDraft = create<{ inputs: Inputs; revision: number; invalidate: () => void; field: <K extends keyof Inputs>(key: K, value: SetStateAction<Inputs[K]>) => void; reset: () => void }>(set => ({
  inputs: empty(), revision: 0, invalidate: () => set(state => ({ revision: state.revision + 1 })), field: (key, value) => set(state => ({ inputs: { ...state.inputs, [key]: typeof value === "function" ? value(state.inputs[key]) : value }, revision: state.revision + 1 })),
  reset: () => set(state => ({ inputs: empty(), revision: state.revision + 1 })),
}));
export function useCreativeDraftField<K extends keyof Inputs>(key: K): [Inputs[K], Dispatch<SetStateAction<Inputs[K]>>] {
  const value = useCreativeDraft(state => state.inputs[key]);
  return [value, next => useCreativeDraft.getState().field(key, next)];
}
