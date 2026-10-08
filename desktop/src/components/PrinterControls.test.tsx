// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

// Every printer call is a mock. No request leaves the test, and no printer is contacted.
const api = vi.hoisted(() => ({
  printerPause: vi.fn(), printerResume: vi.fn(), printerCancel: vi.fn(), printerStartPrint: vi.fn(),
  printerEmergencyStop: vi.fn(), printerUploadGcode: vi.fn(), openGcodeDialog: vi.fn(),
}));
vi.mock("@/api", () => api);

import { PrinterControls } from "./PrinterControls";
import type { PrintState } from "@/lib/printerControl";

// jsdom does not implement the dialog methods. This stands in for the browser's behaviour that the
// component relies on: showModal() opens it, close() closes it. What the browser does beyond that
// (making the rest of the page inert, keeping focus inside, Escape raising a "cancel" event) is checked
// in a real browser engine, not here.
beforeAll(() => {
  const proto = HTMLDialogElement.prototype as unknown as Record<string, unknown>;
  proto.showModal = function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
  proto.close = function (this: HTMLDialogElement) { this.removeAttribute("open"); this.dispatchEvent(new Event("close")); };
});
beforeEach(() => { vi.clearAllMocks(); });
afterEach(cleanup);

const deferred = <T,>() => {
  let resolve!: (v: T) => void; let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};

type Props = { host: string | null; printState: PrintState; online: boolean };
function setup(initial: Partial<Props> = {}) {
  const onChanged = vi.fn();
  const props: Props = { host: "printer-a", printState: "printing", online: true, ...initial };
  const view = render(<PrinterControls {...props} onChanged={onChanged} />);
  const update = (next: Partial<Props>) => view.rerender(<PrinterControls {...{ ...props, ...next }} onChanged={onChanged} />);
  return { onChanged, update };
}
const openCancelPrompt = () => {
  const button = screen.getByRole("button", { name: /Cancel print/ });
  button.focus();
  fireEvent.click(button);
  return button;
};
const dialog = () => screen.queryByRole("alertdialog");
const confirmButton = () => within(screen.getByRole("alertdialog")).getByRole("button", { name: "Yes, do it" });

describe("PrinterControls confirmation", () => {
  it("opens as a named, described alert dialog that says which printer is affected", () => {
    setup();
    openCancelPrompt();
    const d = screen.getByRole("alertdialog", { name: "Cancel this print?" });
    expect(d.getAttribute("aria-describedby")).toBeTruthy();
    expect(d.textContent).toContain("You can't resume a cancelled print.");
    expect(d.textContent).toContain("Printer: printer-a");
  });

  it("puts initial focus on Cancel, and opening it sends nothing", () => {
    setup();
    openCancelPrompt();
    expect(document.activeElement).toBe(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
    expect(api.printerCancel).not.toHaveBeenCalled();
  });

  it("Escape dismisses without sending, and focus returns to the control that opened it", () => {
    setup();
    const opener = openCancelPrompt();
    fireEvent(screen.getByRole("alertdialog"), new Event("cancel", { cancelable: true }));
    expect(dialog()).toBeNull();
    expect(api.printerCancel).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(opener);
  });

  it("the Cancel button dismisses without sending", () => {
    setup();
    const opener = openCancelPrompt();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
    expect(dialog()).toBeNull();
    expect(api.printerCancel).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(opener);
  });

  it("confirming sends one request to the printer that was shown, even on a rapid double click", async () => {
    const slow = deferred<unknown>();
    api.printerCancel.mockReturnValue(slow.promise);
    const { onChanged } = setup();
    openCancelPrompt();
    const yes = confirmButton();
    // Three clicks inside one render pass, before React can disable the button: only the in-flight
    // guard (not the disabled button) can stop the second and third from sending.
    act(() => { yes.click(); yes.click(); yes.click(); });
    expect(api.printerCancel).toHaveBeenCalledTimes(1);
    expect(api.printerCancel).toHaveBeenCalledWith("printer-a");
    await act(async () => { slow.resolve({ ok: true }); await slow.promise; });
    await waitFor(() => expect(dialog()).toBeNull());
    expect(api.printerCancel).toHaveBeenCalledTimes(1);
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("Escape does nothing while the request is in flight", async () => {
    const slow = deferred<unknown>();
    api.printerCancel.mockReturnValue(slow.promise);
    setup();
    openCancelPrompt();
    fireEvent.click(confirmButton());
    fireEvent(screen.getByRole("alertdialog"), new Event("cancel", { cancelable: true }));
    expect(dialog()).not.toBeNull();
    await act(async () => { slow.resolve({ ok: true }); await slow.promise; });
    await waitFor(() => expect(dialog()).toBeNull());
  });

  it("is withdrawn, and sends nothing, when the connected printer changes", () => {
    const { update } = setup();
    openCancelPrompt();
    update({ host: "printer-b" });
    expect(dialog()).toBeNull();
    expect(api.printerCancel).not.toHaveBeenCalled();
  });

  it("does not come back when the first printer is selected again", () => {
    const { update } = setup();
    openCancelPrompt();
    update({ host: "printer-b" });
    update({ host: "printer-a" });
    expect(dialog()).toBeNull();
  });

  it("is withdrawn when the printer stops answering", () => {
    const { update } = setup();
    openCancelPrompt();
    update({ online: false });
    expect(dialog()).toBeNull();
    expect(api.printerCancel).not.toHaveBeenCalled();
  });

  it("is withdrawn when the printer can no longer take the action", () => {
    const { update } = setup();
    openCancelPrompt();
    update({ printState: "complete" });
    expect(dialog()).toBeNull();
    expect(api.printerCancel).not.toHaveBeenCalled();
  });

  it("a request already sent is not retargeted when the printer changes; the person is told, and B's controls wait for it", async () => {
    const slow = deferred<unknown>();
    api.printerCancel.mockReturnValue(slow.promise);
    const { update } = setup();
    openCancelPrompt();
    fireEvent.click(confirmButton());
    expect(api.printerCancel).toHaveBeenCalledWith("printer-a");
    update({ host: "printer-b" });
    expect(dialog()).toBeNull();
    // the notice is about what they just did, so it is shown even though they are now looking at printer B
    expect(screen.getByRole("status").textContent).toContain("Cancel was already sent to printer-a");
    // printer B's controls stay disabled until A's request settles, so a second prompt cannot overlap it
    expect((screen.getByRole("button", { name: /Cancel print/ }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { slow.resolve({ ok: true }); await slow.promise; });
    openCancelPrompt();
    expect(dialog()).not.toBeNull();
    expect(api.printerCancel).toHaveBeenCalledTimes(1);
  });

  it("a prompt the browser closes by itself while a request is in flight is put back; otherwise it counts as dismissed", async () => {
    const slow = deferred<unknown>();
    api.printerCancel.mockReturnValue(slow.promise);
    setup();
    openCancelPrompt();
    fireEvent.click(confirmButton());
    const d = screen.getByRole("alertdialog");
    d.removeAttribute("open"); // what a second Escape does in Chromium
    fireEvent(d, new Event("close"));
    expect(d.hasAttribute("open")).toBe(true);
    await act(async () => { slow.resolve({ ok: true }); await slow.promise; });
    await waitFor(() => expect(dialog()).toBeNull());
    // not in flight: the same native close is a plain dismissal
    openCancelPrompt();
    const d2 = screen.getByRole("alertdialog");
    d2.removeAttribute("open");
    fireEvent(d2, new Event("close"));
    expect(dialog()).toBeNull();
    expect(api.printerCancel).toHaveBeenCalledTimes(1);
  });

  it("a rejected request shows the error and is not retried", async () => {
    api.printerCancel.mockRejectedValue(new Error("the printer refused"));
    setup();
    openCancelPrompt();
    fireEvent.click(confirmButton());
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("the printer refused"));
    expect(api.printerCancel).toHaveBeenCalledTimes(1);
    expect(dialog()).toBeNull();
  });

  it("an error from one printer is not shown for another", async () => {
    api.printerCancel.mockRejectedValue(new Error("the printer refused"));
    const { update } = setup();
    openCancelPrompt();
    fireEvent.click(confirmButton());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    update({ host: "printer-b" });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("falls back to the card heading when the control that opened the prompt is gone", () => {
    const { update } = setup();
    openCancelPrompt();
    update({ printState: "complete" }); // the Cancel button disappears with the print
    expect(document.activeElement).toBe(screen.getByText("Printer controls"));
  });

  it("emergency stop also asks first and names the printer", () => {
    setup({ printState: "standby" });
    fireEvent.click(screen.getByRole("button", { name: /^Emergency stop$/ }));
    const d = screen.getByRole("alertdialog", { name: "EMERGENCY STOP" });
    expect(d.textContent).toContain("Printer: printer-a");
    expect(api.printerEmergencyStop).not.toHaveBeenCalled();
    fireEvent.click(within(d).getByRole("button", { name: "Yes, do it" }));
    expect(api.printerEmergencyStop).toHaveBeenCalledWith("printer-a");
  });

  it("pause is sent without a second prompt", async () => {
    api.printerPause.mockResolvedValue({ ok: true });
    setup();
    fireEvent.click(screen.getByRole("button", { name: /Pause/ }));
    expect(dialog()).toBeNull();
    expect(api.printerPause).toHaveBeenCalledWith("printer-a");
  });
});

describe("PrinterControls uploaded file", () => {
  async function uploadOnPrinterA() {
    api.openGcodeDialog.mockResolvedValue("C:/anything/job.gcode");
    api.printerUploadGcode.mockResolvedValue({ filename: "job.gcode" });
    const ctl = setup({ printState: "standby" });
    fireEvent.click(screen.getByRole("button", { name: /Upload sliced gcode/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Start this print/ })).toBeTruthy());
    return ctl;
  }

  it("offers Start for the printer that received the file, naming the file in the prompt", async () => {
    await uploadOnPrinterA();
    expect(api.printerUploadGcode).toHaveBeenCalledWith("printer-a", "C:/anything/job.gcode");
    fireEvent.click(screen.getByRole("button", { name: /Start this print/ }));
    const d = screen.getByRole("alertdialog", { name: "Start printing job.gcode?" });
    expect(d.textContent).toContain("File: job.gcode");
    expect(d.textContent).toContain("Printer: printer-a");
    fireEvent.click(within(d).getByRole("button", { name: "Confirm" }));
    expect(api.printerStartPrint).toHaveBeenCalledWith("printer-a", "job.gcode");
  });

  it("does not offer that file as Start for a different printer", async () => {
    const { update } = await uploadOnPrinterA();
    update({ host: "printer-b", printState: "standby" });
    expect(screen.queryByRole("button", { name: /Start this print/ })).toBeNull();
    update({ host: "printer-a", printState: "standby" });
    expect(screen.getByRole("button", { name: /Start this print/ })).toBeTruthy();
  });

  it("a file uploaded while the printer changes stays with the printer that received it", async () => {
    const slow = deferred<{ filename: string }>();
    api.openGcodeDialog.mockResolvedValue("C:/anything/job.gcode");
    api.printerUploadGcode.mockReturnValue(slow.promise);
    const { update } = setup({ printState: "standby" });
    fireEvent.click(screen.getByRole("button", { name: /Upload sliced gcode/ }));
    await waitFor(() => expect(api.printerUploadGcode).toHaveBeenCalled());
    update({ host: "printer-b", printState: "standby" });
    await act(async () => { slow.resolve({ filename: "job.gcode" }); await slow.promise; });
    expect(screen.queryByRole("button", { name: /Start this print/ })).toBeNull();
  });
});
