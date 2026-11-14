// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { usePreviewFetcher } from "@/hooks/usePreviewFetcher";
import type { PaintedPreview } from "@/lib/paintedPreview";

vi.mock("@/api", () => ({ paintedPreview: vi.fn() }));

const answer = (tag: string) => ({ schema: tag } as unknown as PaintedPreview);

describe("usePreviewFetcher", () => {
  it("reads the open project's file once and reuses it", async () => {
    const read = vi.fn(async () => answer("a"));
    const { result } = renderHook(() => usePreviewFetcher("C:\a.3mf", read));
    const [one, two] = await Promise.all([result.current("C:\a.3mf"), result.current("C:\a.3mf")]);
    expect(one).toBe(two);
    await result.current("C:\a.3mf");
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("reads a written copy every time, since the same name can hold new colours", async () => {
    let n = 0;
    const read = vi.fn(async () => answer(String(++n)));
    const { result } = renderHook(() => usePreviewFetcher("C:\a.3mf", read));
    expect((await result.current("C:\a_U1.3mf")).schema).toBe("1");
    expect((await result.current("C:\a_U1.3mf")).schema).toBe("2");
  });

  it("does not keep a failure: the next ask tries again", async () => {
    const read = vi.fn().mockRejectedValueOnce(new Error("busy")).mockResolvedValueOnce(answer("ok"));
    const { result } = renderHook(() => usePreviewFetcher("C:\a.3mf", read));
    await expect(result.current("C:\a.3mf")).rejects.toThrow("busy");
    await Promise.resolve();
    expect((await result.current("C:\a.3mf")).schema).toBe("ok");
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("another project path starts over", async () => {
    const read = vi.fn(async (p: string) => answer(p));
    const { result, rerender } = renderHook(({ p }) => usePreviewFetcher(p, read), { initialProps: { p: "C:\a.3mf" } });
    await result.current("C:\a.3mf");
    rerender({ p: "C:\b.3mf" });
    expect((await result.current("C:\b.3mf")).schema).toBe("C:\b.3mf");
    expect(read).toHaveBeenCalledTimes(2);
  });
});
