import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ doctor: vi.fn(), convert: vi.fn(), diff: vi.fn() }));
vi.mock("@/api", () => api);

import { useSession } from "./session";

const A = "C:/p/a.3mf";
const ok = (out = "C:/p/a_U1.3mf") => ({ blocked: false, validated_ok: true, output_path: out, settings_summary: null });

beforeEach(() => {
  vi.clearAllMocks();
  api.doctor.mockResolvedValue({});
  api.diff.mockResolvedValue({});
  useSession.getState().reset();
  useSession.getState().setFile(A);
});

describe("a published preparation is bound to the revision it started under", () => {
  it("is accepted for the revision that started, once", () => {
    const rev = useSession.getState().beginPrepare(A);
    useSession.getState().publishPrepared(rev, A, ok());
    expect(useSession.getState().convert.status).toBe("done");
  });
  it("is refused with no revision (the project was not open when it started)", () => {
    expect(useSession.getState().beginPrepare("C:/p/other.3mf")).toBeNull();
    useSession.getState().publishPrepared(null, A, ok());
    expect(useSession.getState().convert.status).not.toBe("done");
  });
  it("is refused after the same project is reopened", () => {
    const rev = useSession.getState().beginPrepare(A);
    useSession.getState().setFile(A);
    useSession.getState().publishPrepared(rev, A, ok());
    expect(useSession.getState().convert.status).not.toBe("done");
  });
  it("is refused after reset", () => {
    const rev = useSession.getState().beginPrepare(A);
    useSession.getState().reset();
    useSession.getState().setFile(A);
    useSession.getState().publishPrepared(rev, A, ok());
    expect(useSession.getState().convert.status).not.toBe("done");
  });
  it("is refused after a newer preparation began", () => {
    const old = useSession.getState().beginPrepare(A);
    const newer = useSession.getState().beginPrepare(A);
    useSession.getState().publishPrepared(newer, A, ok("C:/p/new.3mf"));
    useSession.getState().publishPrepared(old, A, ok("C:/p/old.3mf"));
    expect(useSession.getState().convert.data?.output_path).toBe("C:/p/new.3mf");
  });
  it("is refused after Prepare was run through the store", async () => {
    const rev = useSession.getState().beginPrepare(A);
    api.convert.mockResolvedValue(ok("C:/p/store.3mf"));
    await useSession.getState().runConvert();
    useSession.getState().publishPrepared(rev, A, ok("C:/p/late.3mf"));
    expect(useSession.getState().convert.data?.output_path).toBe("C:/p/store.3mf");
  });
});

const deferred = <T,>() => { let resolve!: (v: T) => void; let reject!: (e: unknown) => void; const promise = new Promise<T>((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const flush = async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); };

describe("the store's own Prepare and the published one cannot overwrite each other", () => {
  it("an older runConvert that resolves after a newer published Prepare is dropped", async () => {
    const old = deferred<unknown>();
    api.convert.mockReturnValueOnce(old.promise);
    const running = useSession.getState().runConvert();
    const rev = useSession.getState().beginPrepare(A);
    useSession.getState().publishPrepared(rev, A, ok("C:/p/newer.3mf"));
    old.resolve(ok("C:/p/older.3mf"));
    await running; await flush();
    expect(useSession.getState().convert.data?.output_path).toBe("C:/p/newer.3mf");
  });
  it("an older runConvert that rejects after a newer published Prepare does not clear it", async () => {
    const old = deferred<unknown>();
    api.convert.mockReturnValueOnce(old.promise);
    const running = useSession.getState().runConvert();
    const rev = useSession.getState().beginPrepare(A);
    useSession.getState().publishPrepared(rev, A, ok("C:/p/newer.3mf"));
    old.reject(new Error("engine went away"));
    await running; await flush();
    expect(useSession.getState().convert.status).toBe("done");
    expect(useSession.getState().convert.data?.output_path).toBe("C:/p/newer.3mf");
  });
});

describe("the comparison always belongs to the current prepared copy", () => {
  it("a new preparation drops the previous copy's comparison and compares the replacement", async () => {
    api.convert.mockResolvedValueOnce(ok("C:/p/first.3mf"));
    api.diff.mockResolvedValueOnce({ for: "first" });
    await useSession.getState().runConvert(); await flush();
    expect(useSession.getState().diff.data).toEqual({ for: "first" });
    api.diff.mockResolvedValueOnce({ for: "second" });
    const rev = useSession.getState().beginPrepare(A);
    expect(useSession.getState().diff.status).not.toBe("done");
    useSession.getState().publishPrepared(rev, A, ok("C:/p/second.3mf"));
    await flush();
    expect(api.diff).toHaveBeenLastCalledWith(A, "C:/p/second.3mf");
    expect(useSession.getState().diff.data).toEqual({ for: "second" });
  });
  it("an earlier comparison that finishes after the replacement was published is dropped", async () => {
    api.convert.mockResolvedValueOnce(ok("C:/p/first.3mf"));
    const slow = deferred<unknown>();
    api.diff.mockReturnValueOnce(slow.promise);
    await useSession.getState().runConvert(); await flush();
    api.diff.mockResolvedValueOnce({ for: "second" });
    const rev = useSession.getState().beginPrepare(A);
    useSession.getState().publishPrepared(rev, A, ok("C:/p/second.3mf"));
    await flush();
    slow.resolve({ for: "first" });
    await flush();
    expect(useSession.getState().diff.data).toEqual({ for: "second" });
  });
  it("a published copy that is not usable leaves no comparison behind", async () => {
    api.convert.mockResolvedValueOnce(ok("C:/p/first.3mf"));
    api.diff.mockResolvedValueOnce({ for: "first" });
    await useSession.getState().runConvert(); await flush();
    const rev = useSession.getState().beginPrepare(A);
    useSession.getState().publishPrepared(rev, A, { ...ok("C:/p/bad.3mf"), validated_ok: false });
    await flush();
    expect(useSession.getState().diff.status).not.toBe("done");
  });
});
