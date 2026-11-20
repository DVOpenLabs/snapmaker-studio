// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("@/lib/variantsApi", () => ({ compareVariants: vi.fn() }));
import { open } from "@tauri-apps/plugin-dialog";
import variants from "@/routes/ext/variants.route";
const deferred = () => { let resolve!: (v: string | null) => void, reject!: (e: Error) => void; const promise = new Promise<string | null>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
beforeEach(() => vi.clearAllMocks()); afterEach(cleanup);
const value = (n: number) => (screen.getByLabelText(`Output ${n} path`) as HTMLInputElement).value;
it("a late native picker cannot replace a manually edited path", async () => {
  const pick = deferred(); vi.mocked(open).mockReturnValue(pick.promise);
  render(<variants.Component />); fireEvent.click(screen.getAllByRole("button", { name: "Choose 3MF or G-code" })[0]);
  fireEvent.change(screen.getByLabelText("Output 1 path"), { target: { value: "synthetic-new.gcode" } });
  await act(async () => pick.resolve("synthetic-old.gcode")); expect(value(1)).toBe("synthetic-new.gcode");
});
it("a stale picker error cannot replace feedback for newer manual inputs", async () => {
  const pick = deferred(); vi.mocked(open).mockReturnValue(pick.promise);
  render(<variants.Component />); fireEvent.click(screen.getAllByRole("button", { name: "Choose 3MF or G-code" })[0]);
  fireEvent.change(screen.getByLabelText("Output 2 path"), { target: { value: "synthetic-new.gcode" } });
  await act(async () => pick.reject(new Error("Synthetic old native error"))); expect(screen.queryByRole("alert")).toBeNull();
});
it("the latest requested picker wins even when an earlier dialog completes first", async () => {
  const older = deferred(), latest = deferred(); vi.mocked(open).mockReturnValueOnce(older.promise).mockReturnValueOnce(latest.promise);
  render(<variants.Component />); const buttons = screen.getAllByRole("button", { name: "Choose 3MF or G-code" });
  fireEvent.click(buttons[0]); fireEvent.click(buttons[1]);
  await act(async () => older.resolve("synthetic-old.gcode")); expect(value(1)).toBe("");
  await act(async () => latest.resolve("synthetic-latest.gcode")); expect(value(2)).toBe("synthetic-latest.gcode");
});
it("a picker completed after leaving the page cannot affect a remounted comparison", async () => {
  const pick = deferred(); vi.mocked(open).mockReturnValue(pick.promise);
  const view = render(<variants.Component />); fireEvent.click(screen.getAllByRole("button", { name: "Choose 3MF or G-code" })[0]);
  view.unmount(); render(<variants.Component />); await act(async () => pick.resolve("synthetic-old.gcode")); expect(value(1)).toBe("");
});
it("cancel preserves the paths already selected", async () => {
  vi.mocked(open).mockResolvedValue(null); render(<variants.Component />);
  fireEvent.change(screen.getByLabelText("Output 1 path"), { target: { value: "synthetic-existing.gcode" } });
  await act(async () => fireEvent.click(screen.getAllByRole("button", { name: "Choose 3MF or G-code" })[0])); expect(value(1)).toBe("synthetic-existing.gcode");
});
