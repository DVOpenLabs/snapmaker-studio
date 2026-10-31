// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NO_SETUP, selectionFromEvaluate, type PrepareSetupSelection } from "@/lib/prepareSetup";
import { PrepareSetupSelector } from "./PrepareSetupSelector";

afterEach(cleanup);
const base = { token: 3, projectPath: "C:/p/a.3mf", label: "u1-demo.local:7125" };
const topo = (heads: number, slots: number) => ({
  schema_version: "topology/1", snapshot_id: "s", received_at: "2026-01-01T12:00:00Z", observed_at: null, mapping_revision: null, complete: true,
  evidence: [], diagnostics: [], bindings: [], units: [],
  heads: Array.from({ length: heads }, (_, i) => ({ id: `head:${i}`, index: i, nozzle_mm: 0.4, evidence: [] })),
  slots: Array.from({ length: slots }, (_, i) => ({ id: `slot:${i}`, index: i, binding: null, nozzle_mm: null })),
});
function view(selection: PrepareSetupSelection, extra: Partial<Parameters<typeof PrepareSetupSelector>[0]> = {}) {
  const props = { onRead: vi.fn(), onClear: vi.fn(), onPrepareWithoutSetup: vi.fn(), ...extra };
  render(<PrepareSetupSelector selection={selection} {...props} />);
  return props;
}
const status = () => screen.getByTestId("setup-status");

describe("PrepareSetupSelector", () => {
  it("with no setup it says Prepare is stock and offers no 'without a setup' action", () => {
    view(NO_SETUP());
    expect(status().dataset.state).toBe("none");
    expect(status().textContent).toMatch(/stock four-toolhead/);
    expect(screen.queryByTestId("prepare-without-setup")).toBeNull();
    expect(screen.queryByTestId("setup-clear")).toBeNull();
  });

  it("reads the typed host once and forgets the key straight away", async () => {
    const p = view(NO_SETUP());
    expect((screen.getByTestId("setup-read") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Setup host address"), { target: { value: "u1-demo.local" } });
    fireEvent.change(screen.getByLabelText("Setup port"), { target: { value: "7125" } });
    fireEvent.change(screen.getByLabelText("Setup OctoPrint API key"), { target: { value: "secret-key" } });
    fireEvent.click(screen.getByTestId("setup-read"));
    expect(p.onRead).toHaveBeenCalledWith({ host: "u1-demo.local", port: "7125", key: "secret-key" });
    await Promise.resolve();
    expect((screen.getByLabelText("Setup OctoPrint API key") as HTMLInputElement).value).toBe("");
  });

  it("shows a bad port from the read as an inline error", async () => {
    view(NO_SETUP(), { onRead: vi.fn().mockRejectedValue(new Error("The port must be a whole number from 1 to 65535.")) });
    fireEvent.change(screen.getByLabelText("Setup host address"), { target: { value: "h" } });
    fireEvent.click(screen.getByTestId("setup-read"));
    expect((await screen.findByTestId("setup-form-error")).textContent).toMatch(/port must be/);
  });

  it.each([[4, 4], [4, 8]])("shows what a ready %i-head, %i-slot setup reported and nothing more", (heads, slots) => {
    view(selectionFromEvaluate(base, { topology: topo(heads, slots) }));
    expect(status().dataset.state).toBe("ready");
    expect(status().textContent).toContain(`${heads} toolheads, ${slots} logical slots`);
    expect(status().textContent).toContain("0 of " + slots + " slots have a reported lane binding");
    expect(screen.queryByTestId("setup-paused")).toBeNull();
    expect(screen.getByTestId("prepare-without-setup")).toBeTruthy();
  });

  it.each(["unknown", "invalid", "failed"] as const)("a %s setup is an alert that pauses Prepare and offers the explicit way out", (s) => {
    const p = view({ status: s, ...base, reason: "the host said so" });
    expect(status().getAttribute("role")).toBe("alert");
    expect(status().textContent).toContain("the host said so");
    expect(screen.getByTestId("setup-paused").textContent).toMatch(/paused/);
    fireEvent.click(screen.getByTestId("prepare-without-setup"));
    expect(p.onPrepareWithoutSetup).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("setup-clear"));
    expect(p.onClear).toHaveBeenCalledTimes(1);
  });

  it("while reading it locks the form and the Prepare-without action", () => {
    view({ status: "reading", ...base });
    expect((screen.getByTestId("setup-read") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("prepare-without-setup") as HTMLButtonElement).disabled).toBe(true);
    expect(status().textContent).toMatch(/Reading/);
  });

  it("hides 'Prepare without a setup' when Prepare is not available", () => {
    view({ status: "failed", ...base, reason: "x" }, { onPrepareWithoutSetup: undefined });
    expect(screen.queryByTestId("prepare-without-setup")).toBeNull();
  });
});
