// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import PrinterAddress from "@/components/PrinterAddress";
import { usePrinter } from "@/store/printer";

beforeEach(() => { localStorage.clear(); usePrinter.setState({ host: "" }); });
afterEach(() => { cleanup(); localStorage.clear(); usePrinter.setState({ host: "" }); });

describe("printer address in Settings", () => {
  it("typing only edits a draft: nothing is saved, so nothing is looked up, until Save", () => {
    render(<PrinterAddress />);
    const input = screen.getByLabelText("Printer network name or IP") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "U1.lo" } });
    fireEvent.change(input, { target: { value: "U1.local" } });
    expect(usePrinter.getState().host).toBe("");
    expect(localStorage.getItem("u1Host")).toBeNull();
    expect(screen.getByText(/Not set up\. Studio does not look for a printer/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save and connect" }));
    expect(usePrinter.getState().host).toBe("U1.local");
    expect(screen.getByText("Set up: U1.local")).toBeTruthy();
  });

  it("Save is off for a blank draft, and Remove returns the profile to not set up", () => {
    usePrinter.setState({ host: "192.168.1.20" });
    render(<PrinterAddress />);
    fireEvent.change(screen.getByLabelText("Printer network name or IP"), { target: { value: "  " } });
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(usePrinter.getState().host).toBe("");
    expect(localStorage.getItem("u1Host")).toBeNull();
  });
});
