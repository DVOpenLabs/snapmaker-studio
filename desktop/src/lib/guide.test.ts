import { describe, expect, it } from "vitest";
import { USER_GUIDE_BLURB, USER_GUIDE_LABEL, USER_GUIDE_URL } from "@/lib/guide";

describe("the user guide link", () => {
  it("is one https address with no query string or credentials", () => {
    const url = new URL(USER_GUIDE_URL);
    expect(url.protocol).toBe("https:");
    expect(url.search).toBe("");
    expect(url.username + url.password).toBe("");
  });
  it("tells the truth about what opening it does", () => {
    expect(USER_GUIDE_BLURB).toMatch(/opens in your browser/i);
    expect(USER_GUIDE_BLURB).not.toMatch(/guarantee|100%/i);
    expect(USER_GUIDE_LABEL.length).toBeGreaterThan(5);
  });
});
