import { describe, expect, it } from "vitest";
import route from "@/routes/ext/calibration.route";

describe("calibration route", () => {
  it("exports the {path, Component} shape the extension loader joins", () => {
    expect(route.path).toBe("/calibration");
    expect(typeof route.Component).toBe("function");
  });
});
