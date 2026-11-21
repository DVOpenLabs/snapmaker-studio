// @vitest-environment jsdom
import { useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("@/lib/calibrationApi", () => ({ evaluateCalibration: vi.fn(), calibrationHistory: vi.fn() }));
import { evaluateCalibration } from "@/lib/calibrationApi";
import CalibrationView from "./CalibrationView";
import { useCalibrationDraft } from "./draft";
beforeEach(() => { vi.clearAllMocks(); useCalibrationDraft.getState().reset(); }); afterEach(cleanup);
function Shell() { const [here, setHere] = useState(true); return <><button onClick={() => setHere(!here)}>Switch tool</button>{here ? <CalibrationView /> : <p>Another tool</p>}</>; }
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const value = (label: string) => (screen.getByLabelText(label) as HTMLInputElement).value;
it("unsaved readings and basis survive tool navigation without evaluating automatically", () => {
  render(<Shell />); type("Material", "PETG"); type("Calibration model", "synthetic-model-A"); type("Physical colors", "#123456"); type("Owned filaments", "Synthetic #112233");
  fireEvent.click(screen.getByText("Switch tool")); fireEvent.click(screen.getByText("Switch tool"));
  expect(value("Physical colors")).toBe("#123456"); expect(value("Material")).toBe("PETG"); expect(value("Calibration model")).toBe("synthetic-model-A"); expect(value("Owned filaments")).toBe("Synthetic #112233");
  expect(evaluateCalibration).not.toHaveBeenCalled();
});
it("changing the basis after returning still clears physical readings", () => {
  render(<Shell />); type("Physical colors", "#123456"); fireEvent.click(screen.getByText("Switch tool")); fireEvent.click(screen.getByText("Switch tool"));
  type("Nozzle diameter", "0.6"); expect(value("Physical colors")).toBe("");
});
it("explicit Clear removes unsaved observations but writes no browser storage", () => {
  const storage = vi.spyOn(Storage.prototype, "setItem"); render(<Shell />); type("Physical colors", "#123456"); type("Owned filaments", "Synthetic #112233");
  fireEvent.click(screen.getByRole("button", { name: "Clear calibration inputs" }));
  expect(value("Physical colors")).toBe(""); expect(value("Owned filaments")).toBe(""); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
});
it("a comparison completed after Clear cannot restore the old result", async () => {
  let resolve!: (value: unknown) => void; vi.mocked(evaluateCalibration).mockReturnValue(new Promise(r => { resolve = r; }) as never);
  render(<Shell />); fireEvent.click(screen.getByRole("button", { name: "Compare palette" })); fireEvent.click(screen.getByRole("button", { name: "Clear calibration inputs" }));
  await act(async () => resolve({ status: "unknown", result: null, decoded: { diagnostics: [{ code: "stale-result" }] } }));
  expect(screen.queryByText("Palette version not evaluated")).toBeNull();
});
it("a palette file completed after unmount cannot overwrite newer draft inputs", async () => {
  let resolve!: (value: string) => void; render(<Shell />);
  fireEvent.change(screen.getByLabelText("Load palette file"), { target: { files: [{ name: "synthetic.txt", size: 30, text: () => new Promise<string>(r => { resolve = r; }) }] } });
  fireEvent.click(screen.getByText("Switch tool")); fireEvent.click(screen.getByText("Switch tool")); type("Palette content", "#aabbcc 1.2 New target");
  await act(async () => resolve("#112233 0.8 Earlier target")); expect(value("Palette content")).toBe("#aabbcc 1.2 New target");
});
