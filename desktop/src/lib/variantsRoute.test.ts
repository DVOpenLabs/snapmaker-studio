import { describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

import route from "@/routes/ext/variants.route";

describe("variants route", () => {
  it("exports the {path, Component} shape the extension loader joins", () => {
    expect(route.path).toBe("/variants");
    expect(typeof route.Component).toBe("function");
  });
});
