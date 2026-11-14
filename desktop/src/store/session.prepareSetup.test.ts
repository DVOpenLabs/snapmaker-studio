import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ doctor: vi.fn(), convert: vi.fn(), diff: vi.fn() }));
const setups = vi.hoisted(() => ({ evaluateSetup: vi.fn() }));
vi.mock("@/api", () => api);
vi.mock("@/lib/setupsApi", async (orig) => ({ ...(await orig<typeof import("@/lib/setupsApi")>()), evaluateSetup: setups.evaluateSetup }));

import { useSession } from "./session";

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
const A = "C:/p/a.3mf";
const S = () => useSession.getState();
const read = (host = "u1-demo.local") => S().readPrepareSetup({ host, port: "7125", key: "secret-key" });

beforeEach(() => {
  vi.clearAllMocks();
  api.doctor.mockResolvedValue({ verdict: "READY", prepare_blocked: false });
  api.diff.mockResolvedValue({});
  api.convert.mockResolvedValue({ blocked: false, validated_ok: true, output_path: "C:/p/a_U1.3mf", settings_summary: null });
  S().reset();
  S().setFile(A);
});

describe("chosen printer setup in the session store", () => {
  it("starts with no setup and sends nothing: the request keeps its old shape", async () => {
    expect(S().prepareSetup.status).toBe("none");
    await S().runConvert("preserve");
    expect(api.convert).toHaveBeenCalledWith(A, undefined, "preserve");
    await S().previewConvert();
    expect(api.convert).toHaveBeenLastCalledWith(A, undefined, "preserve", true);
  });

  it("sends the very topology it shows, for the review and for Prepare (eight slots, four heads)", async () => {
    const t = topo(4, 8);
    setups.evaluateSetup.mockResolvedValue({ report: {}, read: {}, topology: t });
    await read();
    const sel = S().prepareSetup;
    expect(sel.status).toBe("ready");
    expect(sel.status === "ready" && sel.summary).toMatchObject({ heads: 4, slots: 8 });
    expect(JSON.stringify(setups.evaluateSetup.mock.calls[0][0])).toContain("u1-demo.local");
    await S().previewConvert();
    expect(api.convert).toHaveBeenLastCalledWith(A, undefined, "preserve", true, undefined, t);
    await S().runConvert("recommended");
    expect(api.convert).toHaveBeenLastCalledWith(A, undefined, "recommended", false, undefined, t);
  });

  it("never keeps the key in state", async () => {
    setups.evaluateSetup.mockResolvedValue({ report: {}, read: {}, topology: topo(4, 4) });
    await read();
    expect(JSON.stringify(S().prepareSetup)).not.toContain("secret-key");
  });

  it("a failed read, an unknown setup and an invalid setup pause Prepare and the review; nothing is sent", async () => {
    setups.evaluateSetup.mockRejectedValueOnce(new Error("Setup check failed (502)"));
    await read();
    expect(S().prepareSetup).toMatchObject({ status: "failed", reason: "Setup check failed (502)" });
    await S().runConvert();
    expect(S().convert).toMatchObject({ status: "error", error: expect.stringMatching(/Prepare without a setup/) });
    await S().previewConvert();
    expect(S().preview.status).toBe("error");
    setups.evaluateSetup.mockResolvedValueOnce({ report: {}, read: {}, topology: null });
    await read();
    expect(S().prepareSetup.status).toBe("unknown");
    setups.evaluateSetup.mockResolvedValueOnce({ report: {}, read: {}, topology: { ...topo(4, 4), schema_version: "nope" } });
    await read();
    expect(S().prepareSetup.status).toBe("invalid");
    expect(api.convert).not.toHaveBeenCalled();
  });

  it("Prepare without a setup clears the choice first and sends no topology", async () => {
    setups.evaluateSetup.mockRejectedValueOnce(new Error("down"));
    await read();
    await S().runConvertWithoutSetup("preserve");
    expect(S().prepareSetup.status).toBe("none");
    expect(api.convert).toHaveBeenCalledWith(A, undefined, "preserve");
    expect(S().convert.status).toBe("done");
  });

  it("choosing, re-reading or clearing a setup discards the preview and the prepared copy made under the old one", async () => {
    await S().runConvert();
    await S().previewConvert();
    expect(S().convert.status).toBe("done");
    expect(S().preview.status).toBe("done");
    setups.evaluateSetup.mockResolvedValue({ report: {}, read: {}, topology: topo(4, 4) });
    await read();
    expect(S().convert.status).toBe("idle");
    expect(S().preview.status).toBe("idle");
    await S().runConvert();
    S().clearPrepareSetup();
    expect(S().convert.status).toBe("idle");
    expect(S().prepareSetup.status).toBe("none");
  });

  it("an answer that arrives after the setup changed is dropped (out-of-order reads and Prepare)", async () => {
    const slow = deferred<unknown>(); const fast = deferred<unknown>();
    setups.evaluateSetup.mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise);
    const first = read("old.local"); const second = read("new.local");
    fast.resolve({ report: {}, read: {}, topology: topo(4, 8) });
    await second;
    slow.resolve({ report: {}, read: {}, topology: topo(4, 4) });
    await first;
    const sel = S().prepareSetup;
    expect(sel.status === "ready" && sel.summary.slots).toBe(8);
    expect(sel.status === "ready" && sel.label).toContain("new.local");

    const late = deferred<unknown>();
    api.convert.mockReturnValueOnce(late.promise);
    const running = S().runConvert();
    S().clearPrepareSetup();
    late.resolve({ blocked: false, validated_ok: true, output_path: "C:/p/a_U1.3mf" });
    await running;
    expect(S().convert.status).toBe("idle");
  });

  it("opening another project drops the setup, and a read still in flight cannot land on it", async () => {
    const slow = deferred<unknown>();
    setups.evaluateSetup.mockReturnValueOnce(slow.promise);
    const pending = read();
    S().setFile("C:/p/b.3mf");
    slow.resolve({ report: {}, read: {}, topology: topo(4, 4) });
    await pending;
    expect(S().prepareSetup.status).toBe("none");
    await S().runConvert();
    expect(api.convert).toHaveBeenLastCalledWith("C:/p/b.3mf", undefined, "preserve");
  });
});
