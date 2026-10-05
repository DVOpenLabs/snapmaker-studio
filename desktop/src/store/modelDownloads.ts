import { create } from "zustand";
import { pushRecent, type AddedItem } from "@/lib/modelDownloads";

// What arrived from the Model Browser this session. In memory only: the library itself
// (SQLite) is the record; this just drives the "Added from <site>" cards.
interface ModelDownloadsState {
  recent: AddedItem[];
  refusal: string | null;
  failure: string | null;
  add: (item: AddedItem) => void;
  setRefusal: (message: string | null) => void;
  setFailure: (message: string | null) => void;
  dismiss: (path: string) => void;
}

export const useModelDownloads = create<ModelDownloadsState>((set, get) => ({
  recent: [],
  refusal: null,
  failure: null,
  add: (item) => set({ recent: pushRecent(get().recent, item), refusal: null, failure: null }),
  setRefusal: (refusal) => set({ refusal }),
  setFailure: (failure) => set({ failure }),
  dismiss: (path) => set({ recent: get().recent.filter((i) => i.path !== path) }),
}));
