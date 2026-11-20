import { create } from "zustand";
import type { Dispatch, SetStateAction } from "react";
import type { AssemblyDocument, Supply } from "./editor";

type Draft = { document: AssemblyDocument; supply: Supply[]; current: { id: number; revision: number } | null; filePath: string; sampleMode: boolean };
const empty = (): Draft => ({ document: { name: "New assembly", tiles: [], bindings: {} }, supply: [], current: null, filePath: "", sampleMode: false });
/** Editor inputs only, in memory. Observation timestamps are retained, never renewed. No credentials or reports. */
export const useAssemblyDraft = create<{ draft: Draft; field: <K extends keyof Draft>(key: K, value: SetStateAction<Draft[K]>) => void; reset: () => void }>(set => ({
  draft: empty(),
  field: (key, value) => set(state => ({ draft: { ...state.draft, [key]: typeof value === "function" ? value(state.draft[key]) : value } })),
  reset: () => set({ draft: empty() }),
}));
export function useAssemblyDraftField<K extends keyof Draft>(key: K): [Draft[K], Dispatch<SetStateAction<Draft[K]>>] {
  const value = useAssemblyDraft(state => state.draft[key]);
  return [value, next => useAssemblyDraft.getState().field(key, next)];
}
