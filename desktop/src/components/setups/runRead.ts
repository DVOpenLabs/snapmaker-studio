import type { EvaluateResponse } from "@/lib/setupsTypes";

export interface ReadState { busy: boolean; error: string | null; result: EvaluateResponse | null }

/** Run one read and report each state change through `set`.
 *
 *  The previous report is cleared before the request goes out, so a failed read can never leave an
 *  earlier host's observations on screen under new inputs. `isCurrent` is false once the view is gone
 *  or a newer read has started; a stale read then changes nothing, so a slow old answer cannot replace
 *  a newer one. */
export async function runRead(
  read: () => Promise<EvaluateResponse>,
  set: (patch: Partial<ReadState>) => void,
  isCurrent: () => boolean,
): Promise<void> {
  set({ busy: true, error: null, result: null });
  try {
    const res = await read();
    if (isCurrent()) set({ result: res });
  } catch (e) {
    if (isCurrent()) set({ error: e instanceof Error ? e.message : "The check failed." });
  } finally {
    if (isCurrent()) set({ busy: false });
  }
}
