// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CalibrationView from "./CalibrationView";
import { calibrationHistory, evaluateCalibration } from "@/lib/calibrationApi";
vi.mock("@/lib/calibrationApi", () => ({ evaluateCalibration: vi.fn(), calibrationHistory: vi.fn() }));
const unknown = { status: "unknown", decoded: { diagnostics: [{ code: "old-result" }] }, result: null };
beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

it("starts without invented physical readings and sends the visible basis", async () => {
  vi.mocked(evaluateCalibration).mockResolvedValue(unknown as never);
  render(<CalibrationView />);
  expect((screen.getByLabelText("Physical colors") as HTMLTextAreaElement).value).toBe("");
  expect((screen.getByLabelText("Owned filaments") as HTMLTextAreaElement).value).toBe("");
  fireEvent.change(screen.getByLabelText("Nozzle diameter"), { target: { value: "0.6" } });
  fireEvent.change(screen.getByLabelText("Material"), { target: { value: "PETG" } });
  fireEvent.change(screen.getByLabelText("Calibration model"), { target: { value: "swatch-B" } });
  fireEvent.change(screen.getByLabelText("First layer height"), { target: { value: "0.3" } });
  fireEvent.click(screen.getByText("Compare palette"));
  await waitFor(() => expect(evaluateCalibration).toHaveBeenCalledWith(expect.objectContaining({ nozzle_mm: 0.6, material: "PETG", model: "swatch-B", first_layer_height_mm: 0.3, physical_colors: {} })));
});

it("clears readings when palette content or format changes", () => {
  render(<CalibrationView />);
  const readings = screen.getByLabelText("Physical colors") as HTMLTextAreaElement;
  fireEvent.change(readings, { target: { value: "#123456" } });
  fireEvent.change(screen.getByLabelText("Palette content"), { target: { value: "#abcdef 1.2 New" } });
  expect(readings.value).toBe("");
  fireEvent.change(readings, { target: { value: "#123456" } });
  fireEvent.change(screen.getByLabelText("Palette format"), { target: { value: "kromacut_json" } });
  expect(readings.value).toBe("");
});

it("ignores an evaluation completed after inputs change", async () => {
  let finish!: (r: never) => void;
  vi.mocked(evaluateCalibration).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  render(<CalibrationView />);
  fireEvent.click(screen.getByText("Compare palette"));
  fireEvent.change(screen.getByLabelText("Layer height"), { target: { value: "0.3" } });
  await act(async () => finish(unknown as never));
  expect(screen.queryByText("Palette version not evaluated")).toBeNull();
});

it("loads kpal with the correct format and clears old observations", async () => {
  render(<CalibrationView />);
  fireEvent.change(screen.getByLabelText("Physical colors"), { target: { value: "#123456" } });
  const text = JSON.stringify({ version: 2, colors: ["#aabbcc"] });
  const file = { name: "synthetic.kpal", size: text.length, text: () => Promise.resolve(text) };
  fireEvent.change(screen.getByLabelText("Load palette file"), { target: { files: [file] } });
  await waitFor(() => expect((screen.getByLabelText("Palette content") as HTMLTextAreaElement).value).toBe(text));
  expect((screen.getByLabelText("Palette format") as HTMLSelectElement).value).toBe("kromacut_json");
  expect((screen.getByLabelText("Physical colors") as HTMLTextAreaElement).value).toBe("");
});

it("browses saved readings without applying them to current inputs", async () => {
  vi.mocked(calibrationHistory).mockResolvedValue({ runs: [{ calibration_basis: { calibration_basis_id: "saved-basis", family: "backlit", material: "PLA", layer_height_mm: 0.2, nozzle_mm: 0.4 }, entries: [{ label: "Saved red", simulated_color: "#ff0000", physical_color: "#ee0000" }], inputs_revision: { revision: "saved-revision" } }] } as never);
  render(<CalibrationView />);
  fireEvent.click(screen.getByText("Load saved comparisons"));
  await screen.findByText(/Saved red: target/);
  expect((screen.getByLabelText("Physical colors") as HTMLTextAreaElement).value).toBe("");
});
