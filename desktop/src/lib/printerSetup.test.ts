import { describe, expect, it } from "vitest";
import { hostFromStorage, isPrinterSetUp, normalizeHost, PrinterNotSetUpError, requirePrinterHost } from "@/lib/printerSetup";

describe("printer set-up state", () => {
  it("blank, missing and whitespace addresses are all 'not set up'", () => {
    for (const v of [null, undefined, "", "   ", "\t\n"]) {
      expect(isPrinterSetUp(v)).toBe(false);
      expect(normalizeHost(v)).toBe("");
    }
  });

  it("a real address, even the stock name, counts as set up once it is saved", () => {
    expect(isPrinterSetUp("U1.local")).toBe(true);
    expect(isPrinterSetUp(" 192.168.1.20 ")).toBe(true);
    expect(normalizeHost(" 192.168.1.20 ")).toBe("192.168.1.20");
  });

  it("migration: a value stored by an earlier version is kept exactly; no stored value is not set up", () => {
    expect(hostFromStorage("U1.local")).toBe("U1.local");
    expect(hostFromStorage("192.168.1.20")).toBe("192.168.1.20");
    expect(hostFromStorage(null)).toBe("");
    expect(hostFromStorage("")).toBe("");
  });

  it("requirePrinterHost refuses a blank address before any request could be built", () => {
    expect(() => requirePrinterHost("")).toThrow(PrinterNotSetUpError);
    expect(() => requirePrinterHost(null)).toThrow(/No printer is set up yet/);
    expect(requirePrinterHost(" u1.local ")).toBe("u1.local");
  });
});
