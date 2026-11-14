import { describe, expect, it } from "vitest";
import { shouldResetScroll } from "@/lib/scrollReset";

describe("when a route change starts at the top", () => {
  it("a different page does", () => expect(shouldResetScroll("/", "/this-print", "")).toBe(true));
  it("the first render does not (nothing to reset)", () => expect(shouldResetScroll(null, "/", "")).toBe(false));
  it("the same page keeps its place (query, state or re-selecting it)", () => expect(shouldResetScroll("/workspace", "/workspace", "")).toBe(false));
  it("an in-page anchor is left to scroll to its target", () => expect(shouldResetScroll("/help", "/settings", "#printer")).toBe(false));
});
