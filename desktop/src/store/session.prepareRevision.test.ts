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
