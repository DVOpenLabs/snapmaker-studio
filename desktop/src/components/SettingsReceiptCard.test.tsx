// @vitest-environment jsdom
import React from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
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
    expect(screen.getAllByText("Not stated").length).toBe(1);
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
    expect(screen.getByText("Not stated")).toBeTruthy();
    expect(screen.getByText("Not checked")).toBeTruthy();
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
it("discloses a saved prepared copy that is not part of the comparison, and only then", async () => {
    vi.mocked(settingsReceipt).mockResolvedValue(MISMATCH);
    const { rerender } = render(<SettingsReceiptCard original={"C:\a.3mf"} prepared={null} sliced={"C:\a.gcode"} preparedOmitted />);
    await act(async () => {});
    expect(screen.getByTestId("receipt-prepared-omitted").textContent).toMatch(/saved prepared copy that was not reopened/);
    rerender(<SettingsReceiptCard original={"C:\a.3mf"} prepared={null} sliced={"C:\a.gcode"} />);
    expect(screen.queryByTestId("receipt-prepared-omitted")).toBeNull();
  });
});
