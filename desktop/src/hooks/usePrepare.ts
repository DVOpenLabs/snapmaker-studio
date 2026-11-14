import { useCallback, useEffect, useRef, useState } from "react";
import { convert, type ConversionResult, type PrepareMode } from "@/api";
import type { MaterialSelection } from "@/lib/projectMaterials";
import { prepareBlockedBy, topologyToSend } from "@/lib/prepareSetup";
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
  /** Prepare with no printer setup: drops the chosen one first, so nothing from it is sent or shown. */
  startWithoutSetup: (path: string, mode: PrepareMode, materials?: MaterialSelection[]) => Promise<ConversionResult | undefined>;
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
 *
 * The chosen printer setup (shared session store) is read when a request starts and that same topology is sent. What is
 * shown or in flight is kept only while that selection is still current: choosing, re-reading, clearing or dropping a
 * setup, or opening another project, discards the preview, the prepared copy and any late answer made under the old one.
 * A setup that cannot be used pauses Prepare and its review rather than quietly falling back to the stock behaviour.
 */
interface Stamped<T> { v: T; token: number }

export function usePrepare(closed: boolean): PrepareController {
  // Each answer is stamped with the setup selection it was made under; a stamp that is no longer current hides it at once.
  const [result, setResultRaw] = useState<Stamped<ConversionResult> | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setErrorRaw] = useState<Stamped<unknown> | null>(null);
  const [preview, setPreviewRaw] = useState<Stamped<ConversionResult> | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewErrorRaw] = useState<Stamped<unknown> | null>(null);
  const setupToken = useSession((s) => s.prepareSetup.token);
  const setResult = (v: ConversionResult | null, token = setupToken) => setResultRaw(v ? { v, token } : null);
  const setError = (v: unknown, token = setupToken) => setErrorRaw(v == null ? null : { v, token });
  const setPreview = (v: ConversionResult | null, token = setupToken) => setPreviewRaw(v ? { v, token } : null);
  const setPreviewError = (v: unknown, token = setupToken) => setPreviewErrorRaw(v == null ? null : { v, token });

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
    setResultRaw(null); setErrorRaw(null); setPending(false);
    setPreviewRaw(null); setPreviewErrorRaw(null); setPreviewing(false);
  }, []);

  const start = useCallback(async (path: string, mode: PrepareMode, materials?: MaterialSelection[]) => {
    if (closedRef.current) throw new Error("Studio cannot prepare a U1 copy of this project.");
    const e0 = epoch.current;
    const mine = ++prepSeq.current;
    const setup = useSession.getState().prepareSetup;
    const token = setup.token;
    const current = () => alive.current && e0 === epoch.current && mine === prepSeq.current && !closedRef.current
      && useSession.getState().prepareSetup.token === token;
    const paused = prepareBlockedBy(setup, path);
    if (paused) {
      const refusal = new Error(paused);
      setResultRaw(null); setErrorRaw({ v: refusal, token }); setPending(false);
      throw refusal;
    }
    // The store hands back the revision this request belongs to; it is the only thing that lets its result in later.
    const revision = useSession.getState().beginPrepare(path);
    setResult(null); setError(null); setPending(true);
    try {
      // With no setup the request is exactly what it was before setups existed.
      const topology = topologyToSend(setup, path);
      const data = await (topology ? convert(path, undefined, mode, false, materials, topology) : convert(path, undefined, mode, false, materials));
      if (!current()) return undefined;
      setResult(data, token);
      // Share it with the job screen and After slicing; the store accepts it only for the open project and only if validated.
      useSession.getState().publishPrepared(revision, path, data);
      return data;
    } catch (e) {
      if (current()) setError(e, token);
      throw e;
    } finally {
      if (alive.current && e0 === epoch.current && mine === prepSeq.current) setPending(false);
    }
  }, []);

  const startPreview = useCallback((path: string) => {
    if (closedRef.current) return;
    const e0 = epoch.current;
    const mine = ++previewSeq.current;
    const setup = useSession.getState().prepareSetup;
    const token = setup.token;
    const current = () => alive.current && e0 === epoch.current && mine === previewSeq.current && !closedRef.current
      && useSession.getState().prepareSetup.token === token;
    const paused = prepareBlockedBy(setup, path);
    if (paused) { setPreviewRaw(null); setPreviewErrorRaw({ v: new Error(paused), token }); setPreviewing(false); return; }
    setPreview(null); setPreviewError(null); setPreviewing(true);
    // The review is asked with the same setup the final Prepare will send.
    const topology = topologyToSend(setup, path);
    (topology ? convert(path, undefined, "preserve", true, undefined, topology) : convert(path, undefined, "preserve", true)).then(
      (d) => { if (current()) setPreview(d, token); },
      (e) => { if (current()) setPreviewError(e, token); },
    ).finally(() => { if (alive.current && e0 === epoch.current && mine === previewSeq.current) setPreviewing(false); });
  }, []);

  // Eligibility closing clears what was prepared or previewed and invalidates anything still in flight.
  useEffect(() => { if (closed) reset(); }, [closed, reset]);

  const clearResult = useCallback(() => setResultRaw(null), []);

  const startWithoutSetup = useCallback((path: string, mode: PrepareMode, materials?: MaterialSelection[]) => {
    useSession.getState().clearPrepareSetup();
    return start(path, mode, materials);
  }, [start]);

  const fresh = <T,>(s: Stamped<T> | null): T | null => (!closed && s && s.token === setupToken ? s.v : null);
  return {
    result: fresh(result), pending, error: fresh(error),
    preview: fresh(preview), previewing, previewError: fresh(previewError),
    start, startPreview, startWithoutSetup, reset, clearResult,
  };
}
