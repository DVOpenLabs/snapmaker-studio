import { useCallback, useEffect, useRef, useState } from "react";
import { convert, type ConversionResult, type PrepareMode } from "@/api";
import type { MaterialSelection } from "@/lib/projectMaterials";
import { useSession } from "@/store/session";

export interface PrepareController {
  /** What the last Prepare answered, or null. Never set while Prepare is closed. */
  result: ConversionResult | null;
  pending: boolean;
  /** Why the last Prepare could not run at all (not the same as a refusal, which is a `result`). */
  error: unknown;
  /** The settings review for "custom" preparation. */
  preview: ConversionResult | null;
  previewing: boolean;
  previewError: unknown;
  start: (path: string, mode: PrepareMode, materials?: MaterialSelection[]) => Promise<ConversionResult | undefined>;
  startPreview: (path: string) => void;
  /** Forget everything shown and drop any request still in flight. */
  reset: () => void;
  clearResult: () => void;
}

/**
 * Prepare for one open project, shared by every screen that offers it.
 *
 * It owns what a screen needs around a Prepare: the last answer, a refusal, a settings
 * preview, and the guards that stop a late answer from appearing for something else.
 * The shared session store still decides what counts as "the prepared copy": a result is
 * published there only for the project that is open and only if it was validated.
 *
 * `closed` is the engine saying Studio cannot prepare this project. While it is set,
 * nothing starts and nothing already shown or in flight is kept.
 */
export function usePrepare(closed: boolean): PrepareController {
  const [result, setResult] = useState<ConversionResult | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [preview, setPreview] = useState<ConversionResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<unknown>(null);

  // epoch: bumped by reset/close/unmount (invalidates everything); seq: newest request of each kind.
  const epoch = useRef(0);
  const prepSeq = useRef(0);
  const previewSeq = useRef(0);
  const closedRef = useRef(closed);
  closedRef.current = closed;
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; epoch.current++; }; }, []);

  const reset = useCallback(() => {
    epoch.current++;
    setResult(null); setError(null); setPending(false);
    setPreview(null); setPreviewError(null); setPreviewing(false);
  }, []);

  const start = useCallback(async (path: string, mode: PrepareMode, materials?: MaterialSelection[]) => {
    if (closedRef.current) throw new Error("Studio cannot prepare a U1 copy of this project.");
    const e0 = epoch.current;
    const mine = ++prepSeq.current;
    const current = () => alive.current && e0 === epoch.current && mine === prepSeq.current && !closedRef.current;
    // The store hands back the revision this request belongs to; it is the only thing that lets its result in later.
    const revision = useSession.getState().beginPrepare(path);
    setResult(null); setError(null); setPending(true);
    try {
      const data = await convert(path, undefined, mode, false, materials);
      if (!current()) return undefined;
      setResult(data);
      // Share it with the job screen and After slicing; the store accepts it only for the open project and only if validated.
      useSession.getState().publishPrepared(revision, path, data);
      return data;
    } catch (e) {
      if (current()) setError(e);
      throw e;
    } finally {
      if (alive.current && e0 === epoch.current && mine === prepSeq.current) setPending(false);
    }
  }, []);

  const startPreview = useCallback((path: string) => {
    if (closedRef.current) return;
    const e0 = epoch.current;
    const mine = ++previewSeq.current;
    const current = () => alive.current && e0 === epoch.current && mine === previewSeq.current && !closedRef.current;
    setPreview(null); setPreviewError(null); setPreviewing(true);
    convert(path, undefined, "preserve", true).then(
      (d) => { if (current()) setPreview(d); },
      (e) => { if (current()) setPreviewError(e); },
    ).finally(() => { if (alive.current && e0 === epoch.current && mine === previewSeq.current) setPreviewing(false); });
  }, []);

  // Eligibility closing clears what was prepared or previewed and invalidates anything still in flight.
  useEffect(() => { if (closed) reset(); }, [closed, reset]);

  const clearResult = useCallback(() => setResult(null), []);

  return {
    result: closed ? null : result, pending, error: closed ? null : error,
    preview: closed ? null : preview, previewing, previewError: closed ? null : previewError,
    start, startPreview, reset, clearResult,
  };
}
