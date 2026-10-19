// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", () => ({ settingsReceipt: vi.fn() }));

import { settingsReceipt } from "@/api";
import type { ReceiptFact, ReceiptStep, SettingsReceipt } from "@/api";
import { SettingsReceiptCard } from "@/components/SettingsReceiptCard";

// Authored test data shaped like the engine's answer. Not slicer output.
const step = (over: Partial<ReceiptStep>): ReceiptStep =>
  ({ from: "original", to: "sliced", from_value: null, to_value: null, status: "unchanged", detail: "", next_action: null, ...over });
const fact = (id: ReceiptFact["id"], label: string, steps: ReceiptStep[]): ReceiptFact => {
  const rank = { changed: 3, missing: 2, not_checked: 1, unchanged: 0 } as const;
  const status = steps.length ? steps.map((s) => s.status).sort((a, b) => rank[b] - rank[a])[0] : "not_checked";
  return { id, label, status, steps };
};
const receipt = (facts: ReceiptFact[], summary = "1 changed."): SettingsReceipt => ({
  schema_version: "settings-receipt/1", scope: "project", scope_note: "Compared as whole-project settings.",
  stages: { original: { state: "read" }, prepared: { state: "not_provided" }, sliced: { state: "read" } },
  facts, summary, separate_from: "This compares settings only.",
});

const MISMATCH = receipt([
  fact("nozzles", "Nozzle diameter per tool", [step({ status: "changed", detail: "Tool 1: 0.4 mm → 0.2 mm", next_action: "Check the printer profile in Snapmaker Orca." })]),
  fact("layer_height", "Layer height", [step({ status: "changed", detail: "0.2 mm → 0.08 mm", next_action: "Set the layer height, slice again." })]),
  fact("supports", "Supports", [step({ status: "missing", detail: "The slice does not record a supports setting.", next_action: "Check this setting in Snapmaker Orca directly." })]),
  fact("prime_tower", "Prime tower (declared on/off only)", [step({ status: "unchanged", detail: "Same: on." })]),
], "2 changed, 1 missing, 0 not checked, 1 unchanged.");

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("the settings receipt card", () => {
  it("shows each difference with its explanation and next action", async () => {
    vi.mocked(settingsReceipt).mockResolvedValue(MISMATCH);
    render(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={null} sliced={"C:\\a.gcode"} />);
    await act(async () => {});
    expect(screen.getByText("Nozzle diameter per tool")).toBeTruthy();
    expect(screen.getByText("Tool 1: 0.4 mm → 0.2 mm")).toBeTruthy();
    expect(screen.getByText(/Check the printer profile/)).toBeTruthy();
    expect(screen.getAllByText("Different").length).toBe(2);
    expect(screen.getByText("Same")).toBeTruthy();
  });

  it("a missing or unchecked setting is never worded as a match", async () => {
    vi.mocked(settingsReceipt).mockResolvedValue(receipt([
      fact("supports", "Supports", [step({ status: "missing", detail: "Not recorded." })]),
      fact("layer_height", "Layer height", [step({ status: "not_checked", detail: "Could not read the prepared copy." })]),
    ]));
    render(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={"C:\\b.3mf"} sliced={"C:\\a.gcode"} />);
    await act(async () => {});
    expect(screen.queryByText("Same")).toBeNull();
    expect(screen.getAllByText("Not stated").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Not checked").length).toBeGreaterThan(0);
  });

  it("states that it is about settings only, and its scope", async () => {
    vi.mocked(settingsReceipt).mockResolvedValue(MISMATCH);
    render(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={null} sliced={"C:\\a.gcode"} />);
    await act(async () => {});
    expect(screen.getByText("This compares settings only.")).toBeTruthy();
    expect(screen.getByText("Compared as whole-project settings.")).toBeTruthy();
  });

  it("an answer about earlier files is never shown beside later ones", async () => {
    const pending: Record<string, (v: SettingsReceipt) => void> = {};
    vi.mocked(settingsReceipt).mockImplementation((o, _p, s) => new Promise((resolve) => { pending[`${o}|${s}`] = resolve; }));
    const view = render(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={null} sliced={"C:\\a.gcode"} />);
    await act(async () => {});
    view.rerender(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={null} sliced={"C:\\b.gcode"} />);
    await act(async () => {});
    await act(async () => pending["C:\\a.3mf|C:\\a.gcode"](MISMATCH));
    expect(screen.queryByText("Layer height")).toBeNull();
    expect(screen.getByText("Comparing…")).toBeTruthy();
    await act(async () => pending["C:\\a.3mf|C:\\b.gcode"](receipt([fact("layer_height", "Layer height", [step({ status: "unchanged", detail: "Same: 0.2 mm." })])], "0 changed.")));
    expect(screen.getByText("Same: 0.2 mm.")).toBeTruthy();
  });

  it("a revision bump re-reads the same paths", async () => {
    vi.mocked(settingsReceipt).mockResolvedValue(MISMATCH);
    const view = render(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={null} sliced={"C:\\a.gcode"} revision={0} />);
    await act(async () => {});
    view.rerender(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={null} sliced={"C:\\a.gcode"} revision={1} />);
    await act(async () => {});
    expect(settingsReceipt).toHaveBeenCalledTimes(2);
  });

  it("a failed comparison says so and shows no stale result", async () => {
    vi.mocked(settingsReceipt).mockRejectedValue(new Error("down"));
    render(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={null} sliced={"C:\\a.gcode"} />);
    await act(async () => {});
    expect(screen.getByText(/could not compare/)).toBeTruthy();
    expect(screen.queryByText("Layer height")).toBeNull();
  });

  it("without a sliced file the steps say to open one", async () => {
    vi.mocked(settingsReceipt).mockResolvedValue(receipt([fact("layer_height", "Layer height", [])], "0 changed, 0 missing, 1 not checked, 0 unchanged."));
    render(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={null} sliced={null} />);
    await act(async () => {});
    expect(screen.getByText("Open a sliced G-code to compare.")).toBeTruthy();
  });
  it("lays the three files' values side by side, with Tool 1 to Tool 4 in order", async () => {
    vi.mocked(settingsReceipt).mockResolvedValue({
      ...receipt([
        fact("nozzles", "Nozzle diameter per tool", [
          step({ from: "original", to: "prepared", from_value: [0.4, 0.4, 0.4, 0.4], to_value: [0.4, 0.4, 0.4, 0.4], status: "unchanged", detail: "Same." }),
          step({ from: "prepared", to: "sliced", from_value: [0.4, 0.4, 0.4, 0.4], to_value: [0.4, 0.2, 0.4, 0.4], status: "changed", detail: "Tool 2: 0.4 mm → 0.2 mm" }),
        ]),
      ]),
      stages: { original: { state: "read" }, prepared: { state: "read" }, sliced: { state: "read" } },
    });
    render(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={"C:\\b.3mf"} sliced={"C:\\a.gcode"} />);
    await act(async () => {});
    for (const label of ["Project", "Prepared copy", "Sliced G-code"]) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    const tool2 = screen.getAllByText(/^Tool 2: [0-9.]+ mm$/).map((n) => n.textContent);
    expect(tool2).toEqual(["Tool 2: 0.4 mm", "Tool 2: 0.4 mm", "Tool 2: 0.2 mm"]);   // project, prepared, sliced
    expect(screen.getByText("Project → Prepared copy")).toBeTruthy();
    expect(screen.getByText("Prepared copy → Sliced G-code")).toBeTruthy();
  });

  it("a file that was not included is 'Not included', not 'Not stated'", async () => {
    vi.mocked(settingsReceipt).mockResolvedValue(MISMATCH);
    render(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={null} sliced={"C:\\a.gcode"} />);
    await act(async () => {});
    expect(screen.getAllByText("Not included").length).toBe(4);       // the prepared column of each setting
  });

  it("shows the project-level scope before and after the answer arrives", async () => {
    let resolve!: (r: SettingsReceipt) => void;
    vi.mocked(settingsReceipt).mockImplementation(() => new Promise((r) => { resolve = r; }));
    render(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={null} sliced={"C:\\a.gcode"} />);
    expect(screen.getByTestId("receipt-scope").textContent).toMatch(/per-plate and per-object overrides are not compared/);
    expect(screen.getByRole("status").textContent).toBe("Comparing…");
    await act(async () => resolve(MISMATCH));
    expect(screen.getByTestId("receipt-scope").textContent).toBe("Compared as whole-project settings.");
  });

  it("a failed comparison can be tried again", async () => {
    vi.mocked(settingsReceipt).mockRejectedValueOnce(new Error("down")).mockResolvedValue(MISMATCH);
    render(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={null} sliced={"C:\\a.gcode"} />);
    await act(async () => {});
    expect(screen.getByRole("alert")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Try again" })); });
    expect(screen.getByText("Nozzle diameter per tool")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not call the saved copy omitted while a new one is being prepared", async () => {
    vi.mocked(settingsReceipt).mockResolvedValue(MISMATCH);
    render(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={null} sliced={"C:\\a.gcode"} preparedOmitted preparing />);
    await act(async () => {});
    expect(screen.getByTestId("receipt-preparing")).toBeTruthy();
    expect(screen.queryByTestId("receipt-prepared-omitted")).toBeNull();
  });

  it("does not credit Studio with the prepared copy", async () => {
    vi.mocked(settingsReceipt).mockResolvedValue(MISMATCH);
    render(<SettingsReceiptCard original={"C:\\a.3mf"} prepared={null} sliced={"C:\\a.gcode"} />);
    await act(async () => {});
    expect(screen.queryByText(/what Studio prepared/)).toBeNull();
  });

it("discloses a saved prepared copy that is not part of the comparison, and only then", async () => {
    vi.mocked(settingsReceipt).mockResolvedValue(MISMATCH);
    const { rerender } = render(<SettingsReceiptCard original={"C:\a.3mf"} prepared={null} sliced={"C:\a.gcode"} preparedOmitted />);
    await act(async () => {});
    expect(screen.getByTestId("receipt-prepared-omitted").textContent).toMatch(/saved prepared copy that was not reopened/);
    rerender(<SettingsReceiptCard original={"C:\a.3mf"} prepared={null} sliced={"C:\a.gcode"} />);
    expect(screen.queryByTestId("receipt-prepared-omitted")).toBeNull();
  });
});
