// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4312, token: "t" }) }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

import * as api from "@/api";
import { PrinterNotSetUpError } from "@/lib/printerSetup";

const fetchSpy = vi.fn();
beforeEach(() => {
  fetchSpy.mockReset().mockResolvedValue({ ok: true, json: async () => ({}) });
  vi.stubGlobal("fetch", fetchSpy);
});
afterEach(() => vi.unstubAllGlobals());

describe("printer requests need an address", () => {
  it("printerStatus with no address rejects and makes no request at all", async () => {
    await expect(api.printerStatus("")).rejects.toBeInstanceOf(PrinterNotSetUpError);
    await expect(api.printerStatus("   ")).rejects.toBeInstanceOf(PrinterNotSetUpError);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("every printer-bound call refuses a blank address, including controls", async () => {
    const calls = [
      () => api.printerCapabilities(""), () => api.printerDiagnostics(""), () => api.printerHistory(""),
      () => api.printerHealth(""), () => api.printerFirmware(""), () => api.printerFailureInsights(""),
      () => api.printerJobQueue(""), () => api.printerPause(""), () => api.printerResume(""),
      () => api.printerCancel(""), () => api.printerEmergencyStop(""), () => api.nozzleStatus("", 7125, true),
    ];
    for (const call of calls) await expect(call()).rejects.toBeInstanceOf(PrinterNotSetUpError);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("a saved address still goes to the local engine, which is the only thing the app calls", async () => {
    await api.printerStatus("u1.local");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(String(fetchSpy.mock.calls[0][0])).toMatch(/^http:\/\/127\.0\.0\.1:4312\/printer\/status$/);
    expect(JSON.parse(fetchSpy.mock.calls[0][1].body)).toEqual({ host: "u1.local", port: 7125 });
  });

  it("a local-only nozzle read (no live probe) is not blocked", async () => {
    await api.nozzleStatus("", 7125, false).catch(() => undefined);
    expect(fetchSpy.mock.calls.every(([u]) => String(u).startsWith("http://127.0.0.1:"))).toBe(true);
  });
});
