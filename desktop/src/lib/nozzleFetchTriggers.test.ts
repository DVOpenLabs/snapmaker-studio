import { describe, expect, it } from "vitest";
import {
  preflightFetchTrigger, printerHubNozzleFetchTrigger, settingsNozzleFetchTrigger, shouldRefetch,
} from "./nozzleFetchTriggers";

// R4-D5: prove cross-component invalidation actually happens — and, just as
// important, that it does NOT happen where it shouldn't (PrinterNozzleSettings
// owns and applies its own mutations directly; A2). `shouldRefetch` mirrors
// React's own effect-dependency shallow comparison, so these tests describe
// exactly what re-running the real `useEffect` would do.

describe("shouldRefetch (mirrors React's dependency-array comparison)", () => {
  it("is false when nothing changed", () => {
    expect(shouldRefetch([1, "a", true], [1, "a", true])).toBe(false);
  });

  it("is true when any entry changed", () => {
    expect(shouldRefetch([1, "a"], [1, "b"])).toBe(true);
  });
});

describe("preflightFetchTrigger (PreflightCard subscribes to nozzleNotesVersion)", () => {
  it("a nozzleNotesVersion bump alone produces exactly one refetch", () => {
    const prev = preflightFetchTrigger("/model.stl", "u1.local", 1);
    const next = preflightFetchTrigger("/model.stl", "u1.local", 2);
    expect(shouldRefetch(prev, next)).toBe(true);
    // Re-rendering with the SAME version again must not refetch a second time.
    expect(shouldRefetch(next, preflightFetchTrigger("/model.stl", "u1.local", 2))).toBe(false);
  });

  it("still refetches on a path or host change, independent of the version", () => {
    const prev = preflightFetchTrigger("/a.stl", "u1.local", 5);
    expect(shouldRefetch(prev, preflightFetchTrigger("/b.stl", "u1.local", 5))).toBe(true);
    expect(shouldRefetch(prev, preflightFetchTrigger("/a.stl", "other.local", 5))).toBe(true);
  });
});

describe("printerHubNozzleFetchTrigger (Printer Hub subscribes to nozzleNotesVersion)", () => {
  it("a nozzleNotesVersion bump alone produces exactly one refetch", () => {
    const prev = printerHubNozzleFetchTrigger("u1.local", 3);
    const next = printerHubNozzleFetchTrigger("u1.local", 4);
    expect(shouldRefetch(prev, next)).toBe(true);
    expect(shouldRefetch(next, printerHubNozzleFetchTrigger("u1.local", 4))).toBe(false);
  });
});

describe("settingsNozzleFetchTrigger (PrinterNozzleSettings does NOT subscribe — A2)", () => {
  it("does not even accept a version, so a bump elsewhere produces zero refetches here", () => {
    const prev = settingsNozzleFetchTrigger("u1.local");
    const next = settingsNozzleFetchTrigger("u1.local");
    expect(shouldRefetch(prev, next)).toBe(false);
  });

  it("still refetches on its own host change", () => {
    const prev = settingsNozzleFetchTrigger("u1.local");
    const next = settingsNozzleFetchTrigger("other.local");
    expect(shouldRefetch(prev, next)).toBe(true);
  });
});
