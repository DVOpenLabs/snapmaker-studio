// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import MonitoringPanel, { REFRESH_MS, STALE_MS } from "./MonitoringPanel";
import { requestMonitoring } from "./transport";
vi.mock("./transport", () => ({ requestMonitoring: vi.fn() }));
vi.mock("@/store/printer", () => ({ usePrinter: (select: (v: { host: string }) => unknown) => select({ host: "configured.local" }) }));
const current = { status: "ok", print_state: "standby", filename: "synthetic.gcode", association: "unverified" };
const history = { status: "ok", last_job: { filename: "older.gcode", outcome: "completed" } };
beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); vi.mocked(requestMonitoring).mockImplementation(async route => (route === "read" ? current : history) as never); });
afterEach(() => { cleanup(); vi.useRealTimers(); });
async function settle() { await act(async () => { await Promise.resolve(); }); }
function address() { fireEvent.change(screen.getByLabelText("Configured printer host"), { target: { value: "synthetic.local" } }); }
it("makes no request until explicit read and reads status plus history", async () => {
  render(<MonitoringPanel />);
  expect(requestMonitoring).not.toHaveBeenCalled();
  address(); fireEvent.click(screen.getByText("Read status")); await settle();
  expect(requestMonitoring).toHaveBeenCalledTimes(2);
  expect(screen.getByText(/older.gcode: completed/)).toBeTruthy();
  expect(screen.getByText(/Filename reported: synthetic.gcode/)).toBeTruthy();
});
it("discards a response after the host changes and aborts its transport", async () => {
  let finish!: (value: never) => void;
  let signal!: AbortSignal;
  vi.mocked(requestMonitoring).mockImplementation((route, _, abort) => { signal = abort; return route === "read" ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(history as never); });
  render(<MonitoringPanel />); address(); fireEvent.click(screen.getByText("Read status"));
  fireEvent.change(screen.getByLabelText("Configured printer host"), { target: { value: "different.local" } });
  expect(signal.aborted).toBe(true);
  await act(async () => finish(current as never));
  expect(screen.queryByText(/Filename reported/)).toBeNull();
});
it("refreshes serially with per-host previous-state reconciliation", async () => {
  render(<MonitoringPanel />); address();
  fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(screen.getByText("Start monitoring")); await settle();
  await act(async () => { await vi.advanceTimersByTimeAsync(REFRESH_MS); });
  const reads = vi.mocked(requestMonitoring).mock.calls.filter(call => call[0] === "read");
  expect(reads).toHaveLength(2);
  expect(reads[1][1]).toMatchObject({ previous_state: "standby" });
  fireEvent.click(screen.getByText("Stop monitoring"));
  await act(async () => { await vi.advanceTimersByTimeAsync(REFRESH_MS * 3); });
  expect(vi.mocked(requestMonitoring).mock.calls.filter(call => call[0] === "read")).toHaveLength(2);
});
it("does not overlap refreshes while a read is pending and stops on unmount", async () => {
  let signal!: AbortSignal;
  vi.mocked(requestMonitoring).mockImplementation((_, __, abort) => { signal = abort; return new Promise(() => {}); });
  const view = render(<MonitoringPanel />); address(); fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(screen.getByText("Start monitoring"));
  await act(async () => { await vi.advanceTimersByTimeAsync(REFRESH_MS * 3); });
  expect(requestMonitoring).toHaveBeenCalledTimes(2);
  view.unmount(); expect(signal.aborted).toBe(true);
});
it("labels ageing receipt time stale without pretending it is source time", async () => {
  render(<MonitoringPanel />); address(); fireEvent.click(screen.getByText("Read status")); await settle();
  await act(async () => { await vi.advanceTimersByTimeAsync(STALE_MS); });
  expect(screen.getByText(/stale; read again/)).toBeTruthy();
  expect(screen.getByTestId("history-age").textContent).toContain("stale; read history again");
});
it("keeps history usable when the status request fails", async () => {
  vi.mocked(requestMonitoring).mockImplementation(async route => { if (route === "read") throw new Error("Synthetic status failure"); return history as never; });
  render(<MonitoringPanel />); address(); fireEvent.click(screen.getByText("Read status")); await settle();
  expect(screen.getByRole("alert").textContent).toContain("Synthetic status failure");
  expect(screen.getByText(/older.gcode: completed/)).toBeTruthy();
});


it("history ages independently when status rejects, including after stopping", async () => {
  vi.mocked(requestMonitoring).mockImplementation(async route => { if (route === "read") throw new Error("Synthetic status failure"); return history as never; });
  render(<MonitoringPanel />); address(); fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(screen.getByText("Start monitoring")); await settle();
  fireEvent.click(screen.getByText("Stop monitoring"));
  await act(async () => { await vi.advanceTimersByTimeAsync(STALE_MS); });
  expect(screen.getByText(/older.gcode: completed/)).toBeTruthy();
  expect(screen.getByTestId("history-age").textContent).toContain("stale; read history again");
  expect(screen.queryByText(/Last response received/)).toBeNull();
});
