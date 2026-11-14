// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

async function freshStore() {
  vi.resetModules();
  return (await import("@/store/printer")).usePrinter;
}

beforeEach(() => localStorage.clear());
afterEach(() => localStorage.clear());

describe("printer store", () => {
  it("an untouched profile is not set up: no address, and nothing is written", async () => {
    const usePrinter = await freshStore();
    expect(usePrinter.getState().host).toBe("");
    expect(localStorage.getItem("u1Host")).toBeNull();
  });

  it("migration: an address saved by an earlier version is still the address", async () => {
    localStorage.setItem("u1Host", "192.168.1.20");
    const usePrinter = await freshStore();
    expect(usePrinter.getState().host).toBe("192.168.1.20");
  });

  it("migration: a stored but blank value is treated as not set up", async () => {
    localStorage.setItem("u1Host", "   ");
    const usePrinter = await freshStore();
    expect(usePrinter.getState().host).toBe("");
  });

  it("saving an address is the explicit act that sets it up; blank removes it, with no default put back", async () => {
    const usePrinter = await freshStore();
    usePrinter.getState().setHost("  U1.local ");
    expect(usePrinter.getState().host).toBe("U1.local");
    expect(localStorage.getItem("u1Host")).toBe("U1.local");
    usePrinter.getState().setHost("");
    expect(usePrinter.getState().host).toBe("");
    expect(localStorage.getItem("u1Host")).toBeNull();
  });
});
