import { describe, expect, it } from "vitest";
import route from "@/routes/ext/recovery.route";
import meta from "@/routes/ext/recovery.meta";

describe("recovery route seam", () => {
  it("exports the { path, Component } shape the ext loader joins", () => {
    expect(route.path).toBe("/recovery");
    expect(typeof route.Component).toBe("function");
    expect(meta.path).toBe(route.path);
  });
});
