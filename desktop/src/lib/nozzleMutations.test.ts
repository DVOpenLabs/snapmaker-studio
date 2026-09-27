import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api";

const { bumpNozzleNotes, nozzleConfirm, nozzleClear } = vi.hoisted(() => ({
  bumpNozzleNotes: vi.fn(),
  nozzleConfirm: vi.fn(),
  nozzleClear: vi.fn(),
}));

vi.mock("@/store/nozzleRevision", () => ({ bumpNozzleNotes }));
vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, nozzleConfirm, nozzleClear };
});

const { confirmNozzles, clearNozzles } = await import("./nozzleMutations");

describe("lib/nozzleMutations (F2: bump only when the mutation's outcome changed or is unknown)", () => {
  beforeEach(() => {
    bumpNozzleNotes.mockClear();
    nozzleConfirm.mockReset();
    nozzleClear.mockReset();
  });

  it("bumps on a successful confirm, even though no component needs to be mounted to observe it", async () => {
    nozzleConfirm.mockResolvedValue({ revision: 2 });
    const result = await confirmNozzles("u1.local", 7125, [0.4], 1);
    expect(result.ok).toBe(true);
    expect(bumpNozzleNotes).toHaveBeenCalledTimes(1);
  });

  it("bumps on a successful clear", async () => {
    nozzleClear.mockResolvedValue({ revision: 3 });
    const result = await clearNozzles("u1.local", 7125, 2);
    expect(result.ok).toBe(true);
    expect(bumpNozzleNotes).toHaveBeenCalledTimes(1);
  });

  it("bumps on an uncertain failure (a plain network error, not a backend response)", async () => {
    nozzleConfirm.mockRejectedValue(new TypeError("Failed to fetch"));
    const result = await confirmNozzles("u1.local", 7125, [0.4], 1);
    expect(result.ok).toBe(false);
    expect(bumpNozzleNotes).toHaveBeenCalledTimes(1);
  });

  it("shows the fixed uncertain-failure text, never the raw error message (R4-D7)", async () => {
    nozzleConfirm.mockRejectedValue(new TypeError("Failed to fetch"));
    const result = await confirmNozzles("u1.local", 7125, [0.4], 1);
    if (result.ok) throw new Error("expected a failure");
    expect(result.error.message).toBe("Studio couldn't reach its local service. Try again.");
    expect(result.error.message).not.toContain("Failed to fetch");
  });

  it("shows the same fixed text for a clear's uncertain failure too", async () => {
    nozzleClear.mockRejectedValue(new Error("ECONNRESET"));
    const result = await clearNozzles("u1.local", 7125, 1);
    if (result.ok) throw new Error("expected a failure");
    expect(result.error.message).toBe("Studio couldn't reach its local service. Try again.");
  });

  it("does NOT bump on a definite 409 stale failure (the recovery fetch handles reconciling, not a bump)", async () => {
    nozzleConfirm.mockRejectedValue(new ApiError("Nozzle notes changed elsewhere. Reload and try again.", "stale", { current_revision: 5 }));
    const result = await confirmNozzles("u1.local", 7125, [0.4], 1);
    expect(result.ok).toBe(false);
    expect(bumpNozzleNotes).not.toHaveBeenCalled();
  });

  it("does NOT bump on a definite 400 validation failure", async () => {
    nozzleConfirm.mockRejectedValue(new ApiError("Nozzle sizes must be between 0 and 2 mm, one per toolhead, up to 8.", "invalid_diameters"));
    const result = await confirmNozzles("u1.local", 7125, [99], 1);
    expect(result.ok).toBe(false);
    expect(bumpNozzleNotes).not.toHaveBeenCalled();
  });

  it("N13: bumps on an ApiError that carries NO code — treated as uncertain, same as a network error", async () => {
    // A malformed/incomplete backend response (a body with `message` but no
    // `error` field) still reaches here as an ApiError, just one with
    // `code === undefined` — the controller already treats that as uncertain
    // (recovery-fetch-worthy); this module must agree, or the two halves of
    // the same decision drift apart.
    nozzleConfirm.mockRejectedValue(new ApiError("Something went wrong."));
    const result = await confirmNozzles("u1.local", 7125, [0.4], 1);
    expect(result.ok).toBe(false);
    expect(bumpNozzleNotes).toHaveBeenCalledTimes(1);
    if (result.ok) throw new Error("expected a failure");
    expect(result.error.code).toBeUndefined();
  });

  it("exposes only the two mutations — no read/status helper lives here to accidentally bump on", async () => {
    const mod = await import("./nozzleMutations");
    expect(Object.keys(mod).sort()).toEqual(["clearNozzles", "confirmNozzles"]);
  });
});
