import { create } from "zustand";
import { hostFromStorage, normalizeHost } from "@/lib/printerSetup";

// The U1 the user monitors. Persisted so the Printer Hub, Dashboard, and
// Settings all agree on one address.
//
// "" means NOT SET UP: Studio makes no printer request of any kind (no status
// poll, no capability or nozzle read) until the person saves an address in
// Settings or presses Connect in the Printer Hub. "U1.local" is only a hint
// shown in those inputs, never a value Studio looks up on its own.
//
// Migration rule: a saved address from an earlier version is kept exactly as
// it was (the old store only ever wrote the key when the person typed an
// address in Settings or pressed Connect, so a stored value is explicit
// intent). A profile with no stored address was relying on the old built-in
// default and is now "not set up" until the person connects once.
export const KEY = "u1Host";

function readInitial(): string {
  try { return hostFromStorage(localStorage.getItem(KEY)); } catch { return ""; }
}

interface PrinterState {
  /** "" = not set up. */
  host: string;
  /** Save an address (explicit intent). A blank value clears it. */
  setHost: (h: string) => void;
}

export const usePrinter = create<PrinterState>((set) => ({
  host: readInitial(),
  setHost: (h) => {
    const v = normalizeHost(h);
    try {
      if (v) localStorage.setItem(KEY, v);
      else localStorage.removeItem(KEY);
    } catch { /* storage unavailable: keep the in-memory choice */ }
    set({ host: v });
  },
}));
