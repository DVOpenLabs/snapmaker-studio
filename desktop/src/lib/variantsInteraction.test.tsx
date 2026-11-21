// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import route from "@/routes/ext/variants.route";
import { compareVariants } from "./variantsApi";
vi.mock("@/lib/variantsApi", () => ({ compareVariants: vi.fn() }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const output = { artifact: { artifact_id: "synthetic-artifact" }, freshness: "current", format: "gcode", tools_used: { value: [0], status: "computed" }, tool_changes: { value: 0, status: "computed" }, grams_by_tool: [], time: { value: 60, status: "reported" }, waste: { value: null, status: "unknown" } };
const report = { outputs: [output, output], stale: false, settings_diff: [], advisory: "old-report" };
function choose() {
  render(<route.Component />);
  fireEvent.change(screen.getByLabelText("Output 1 path"), { target: { value: "first.gcode" } });
  fireEvent.change(screen.getByLabelText("Output 2 path"), { target: { value: "second.gcode" } });
  fireEvent.click(screen.getByText("Compare outputs"));
}
it("discards results for files that have since changed", async () => {
  let finish!: (r: never) => void;
  vi.mocked(compareVariants).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  choose();
  fireEvent.change(screen.getByLabelText("Output 1 path"), { target: { value: "new.gcode" } });
  await act(async () => finish(report as never));
  expect(screen.queryByText("old-report")).toBeNull();
  expect(screen.getByText("Compare outputs").hasAttribute("disabled")).toBe(false);
});
it("discards errors for files that have since changed", async () => {
  let fail!: (r: Error) => void;
  vi.mocked(compareVariants).mockReturnValue(new Promise((_, reject) => { fail = reject; }));
  choose();
  fireEvent.change(screen.getByLabelText("Output 2 path"), { target: { value: "new.gcode" } });
  await act(async () => fail(new Error("old-error")));
  expect(screen.queryByRole("alert")).toBeNull();
});
it("renders a completed comparison for unchanged inputs", async () => {
  vi.mocked(compareVariants).mockResolvedValue(report as never);
  choose();
  expect(await screen.findByText("old-report")).toBeTruthy();
});
