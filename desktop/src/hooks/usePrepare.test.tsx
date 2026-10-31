// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ doctor: vi.fn(), convert: vi.fn(), diff: vi.fn() }));
const setups = vi.hoisted(() => ({ evaluateSetup: vi.fn() }));
vi.mock("@/api", () => api);
vi.mock("@/lib/setupsApi", async (orig) => ({ ...(await orig<typeof import("@/lib/setupsApi")>()), evaluateSetup: setups.evaluateSetup }));

import { useSession } from "@/store/session";
import { usePrepare } from "./usePrepare";

const A = "C:/p/a.3mf";
const S = () => useSession.getState();
const deferred = <T,>() => {
  let resolve!: (v: T) => void; let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};
const topo = (heads: number, slots: number) => ({
  schema_version: "topology/1", snapshot_id: "snap-synthetic", received_at: "2026-01-01T12:00:00Z", observed_at: null, mapping_revision: null,
  complete: true, evidence: [], diagnostics: [], bindings: [], units: [],
  heads: Array.from({ length: heads }, (_, i) => ({ id: `head:${i}`, index: i, nozzle_mm: 0.4, evidence: [] })),
  slots: Array.from({ length: slots }, (_, i) => ({ id: `slot:${i}`, index: i, binding: null, nozzle_mm: null })),
});
const result = (tag: string, extra: object = {}) => ({
  schema_version: "convert/2", prepare_mode: "preserve", output_path: `C:/p/${tag}_U1.3mf`, output_name: `${tag}_U1.3mf`,
  validated_ok: true, settings_summary: { warnings: [] }, ...extra,
});
const read = (host = "u1-demo.local") => S().readPrepareSetup({ host, port: "7125", key: "synthetic" }, A);

beforeEach(() => {
  vi.clearAllMocks();
  api.doctor.mockResolvedValue({ verdict: "READY", prepare_blocked: false });
  api.diff.mockResolvedValue({});
  S().reset();
  S().setFile(A);
});
afterEach(cleanup);

describe("usePrepare with a chosen printer setup", () => {
  it("with no setup the request keeps its old shape for Prepare and for the review", async () => {
    api.convert.mockResolvedValue(result("a"));
    const { result: hook } = renderHook(() => usePrepare(false));
    await act(async () => { await hook.current.start(A, "preserve"); });
    expect(api.convert).toHaveBeenCalledWith(A, undefined, "preserve", false, undefined);
    act(() => hook.current.startPreview(A));
    await waitFor(() => expect(hook.current.preview).not.toBeNull());
    expect(api.convert).toHaveBeenLastCalledWith(A, undefined, "preserve", true);
  });

  it("a ready setup: the review and the final Prepare both send the topology that was shown", async () => {
    const t = topo(4, 8);
    setups.evaluateSetup.mockResolvedValue({ report: {}, read: {}, topology: t });
    await act(async () => { await read(); });
    api.convert.mockResolvedValue(result("a", { settings_summary: { warnings: [], setup: { state: "valid", heads: 4, slots: 8, unbound: [] } } }));
    const { result: hook } = renderHook(() => usePrepare(false));
    act(() => hook.current.startPreview(A));
    await waitFor(() => expect(hook.current.preview).not.toBeNull());
    expect(api.convert).toHaveBeenLastCalledWith(A, undefined, "preserve", true, undefined, t);
    await act(async () => { await hook.current.start(A, "recommended"); });
    expect(api.convert).toHaveBeenLastCalledWith(A, undefined, "recommended", false, undefined, t);
    expect(hook.current.result?.settings_summary.setup?.state).toBe("valid");
  });

  it("an unusable setup pauses Prepare and the review: nothing is sent and the reason is shown", async () => {
    setups.evaluateSetup.mockRejectedValue(new Error("Setup check failed"));
    await act(async () => { await read(); });
    expect(S().prepareSetup.status).toBe("failed");
    const { result: hook } = renderHook(() => usePrepare(false));
    await act(async () => { await expect(hook.current.start(A, "preserve")).rejects.toThrow(/cannot be used|can.t be used/); });
    act(() => hook.current.startPreview(A));
    expect(api.convert).not.toHaveBeenCalled();
    expect((hook.current.error as Error).message).toMatch(/Setup check failed/);
    expect((hook.current.previewError as Error).message).toMatch(/Setup check failed/);
    expect(hook.current.result).toBeNull();
  });

  it("changing the setup while Prepare is in flight discards the late copy", async () => {
    setups.evaluateSetup.mockResolvedValue({ report: {}, read: {}, topology: topo(4, 8) });
    await act(async () => { await read(); });
    const late = deferred<ReturnType<typeof result>>();
    api.convert.mockReturnValueOnce(late.promise);
    const { result: hook } = renderHook(() => usePrepare(false));
    let started!: Promise<unknown>;
    act(() => { started = hook.current.start(A, "preserve"); });
    act(() => S().clearPrepareSetup());
    await act(async () => { late.resolve(result("old")); await started; });
    expect(hook.current.result).toBeNull();
  });

  it("two reviews answering out of order: only the newest, made under the current setup, is shown", async () => {
    const t8 = topo(4, 8);
    setups.evaluateSetup.mockResolvedValueOnce({ report: {}, read: {}, topology: topo(4, 4) });
    await act(async () => { await read("one.local"); });
    const first = deferred<ReturnType<typeof result>>();
    const second = deferred<ReturnType<typeof result>>();
    api.convert.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result: hook } = renderHook(() => usePrepare(false));
    act(() => hook.current.startPreview(A));
    setups.evaluateSetup.mockResolvedValueOnce({ report: {}, read: {}, topology: t8 });
    await act(async () => { await read("two.local"); });
    act(() => hook.current.startPreview(A));
    expect(api.convert).toHaveBeenLastCalledWith(A, undefined, "preserve", true, undefined, t8);
    await act(async () => { second.resolve(result("new")); });
    await waitFor(() => expect(hook.current.preview?.output_name).toBe("new_U1.3mf"));
    await act(async () => { first.resolve(result("old")); });
    expect(hook.current.preview?.output_name).toBe("new_U1.3mf");
  });

  it("a review answered under the old setup never shows after the setup moves on", async () => {
    setups.evaluateSetup.mockResolvedValue({ report: {}, read: {}, topology: topo(4, 8) });
    await act(async () => { await read(); });
    const old = deferred<ReturnType<typeof result>>();
    api.convert.mockReturnValueOnce(old.promise);
    const { result: hook } = renderHook(() => usePrepare(false));
    act(() => hook.current.startPreview(A));
    act(() => S().clearPrepareSetup());
    await act(async () => { old.resolve(result("old")); });
    expect(hook.current.preview).toBeNull();
  });

  it("a finished copy is hidden at once when the setup is cleared or the project changes", async () => {
    setups.evaluateSetup.mockResolvedValue({ report: {}, read: {}, topology: topo(4, 8) });
    await act(async () => { await read(); });
    api.convert.mockResolvedValue(result("a"));
    const { result: hook } = renderHook(() => usePrepare(false));
    await act(async () => { await hook.current.start(A, "preserve"); });
    expect(hook.current.result).not.toBeNull();
    act(() => S().clearPrepareSetup());
    expect(hook.current.result).toBeNull();
    await act(async () => { await read(); });
    await act(async () => { await hook.current.start(A, "preserve"); });
    expect(hook.current.result).not.toBeNull();
    act(() => S().setFile("C:/p/b.3mf"));
    expect(hook.current.result).toBeNull();
  });

  it("Prepare without a setup drops the choice and sends the old request", async () => {
    setups.evaluateSetup.mockResolvedValue({ report: {}, read: {}, topology: topo(4, 8) });
    await act(async () => { await read(); });
    api.convert.mockResolvedValue(result("a"));
    const { result: hook } = renderHook(() => usePrepare(false));
    await act(async () => { await hook.current.startWithoutSetup(A, "preserve"); });
    expect(S().prepareSetup.status).toBe("none");
    expect(api.convert).toHaveBeenLastCalledWith(A, undefined, "preserve", false, undefined);
  });

  it("a setup read for another project is not sent for this one", async () => {
    setups.evaluateSetup.mockResolvedValue({ report: {}, read: {}, topology: topo(4, 8) });
    await act(async () => { await S().readPrepareSetup({ host: "u1-demo.local" }, "C:/p/other.3mf"); });
    api.convert.mockResolvedValue(result("a"));
    const { result: hook } = renderHook(() => usePrepare(false));
    await act(async () => { await hook.current.start(A, "preserve"); });
    expect(api.convert).toHaveBeenLastCalledWith(A, undefined, "preserve", false, undefined);
  });
});
