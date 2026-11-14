import { onAppStart } from "@/lib/extLifecycle";
import { restoreCheckpoint, type RestoreResult } from "./api";

/**
 * Recovery registers with the application lifecycle seam, never in App.tsx. At app start it only
 * READS the last checkpoint so the Recovery page can show it; nothing is restored or replayed.
 */
export type Preview = { status: "idle" | "loading" | "ready" | "failed"; data: RestoreResult | null; error: string };

let preview: Preview = { status: "idle", data: null, error: "" };
const listeners = new Set<() => void>();
let registered = false;

function set(next: Preview): void { preview = next; for (const listener of [...listeners]) listener(); }

export const getPreview = (): Preview => preview;
export function subscribePreview(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Read the checkpoint now (also used by the page's refresh button). */
export async function refreshPreview(): Promise<void> {
  set({ ...preview, status: "loading", error: "" });
  try { set({ status: "ready", data: await restoreCheckpoint(), error: "" }); }
  catch (error) { set({ status: "failed", data: preview.data, error: error instanceof Error ? error.message : "Could not read the checkpoint" }); }
}

/** Idempotent. Returns the lifecycle unsubscribe. */
export function registerRecoverySubscriber(): () => void {
  if (registered) return () => undefined;
  registered = true;
  const off = onAppStart(() => { void refreshPreview(); });
  return () => { off(); registered = false; };
}

export function __resetRecoverySubscriberForTests(): void {
  preview = { status: "idle", data: null, error: "" }; listeners.clear(); registered = false;
}
