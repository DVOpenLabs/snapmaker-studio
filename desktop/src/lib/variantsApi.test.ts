import { describe, expect, it, vi } from "vitest";
import { callExt } from "@/lib/extApi";
import { compareVariants } from "./variantsApi";

vi.mock("@/lib/extApi", () => ({ callExt: vi.fn() }));

describe("compareVariants", () => {
  it("sends the two user-selected local paths to the variants route", async () => {
    vi.mocked(callExt).mockResolvedValue({ outputs: [] } as never);
    await compareVariants({ outputs: [{ path: "first.gcode" }, { path: "second.3mf" }] });
    expect(callExt).toHaveBeenCalledWith("/variants/compare",
      { outputs: [{ path: "first.gcode" }, { path: "second.3mf" }] }, "compare sliced outputs");
  });
});
