import { afterEach, describe, expect, it, vi } from "vitest";
import { buildInspectBody, inspectCreative, originSentence } from "./creativeApi";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4321, token: "test-token" }) }));
const originalFetch = globalThis.fetch;
Object.defineProperty(globalThis, "location", { configurable: true, value: { search: "" } });
afterEach(() => { globalThis.fetch = originalFetch; vi.restoreAllMocks(); });

describe("creative API client", () => {
  it("trims the path and strips pasted quotes; omits the format when it is auto", () => {
    expect(buildInspectBody('  "C:\\x\\a.3mf" ')).toEqual({ path: "C:\\x\\a.3mf" });
    expect(buildInspectBody("a.3mf", "lixnix")).toEqual({ path: "a.3mf", format: "lixnix" });
  });

  it("says a blank path in words", () => {
    expect(() => buildInspectBody("   ")).toThrow("Enter the path of a .3mf project file.");
  });

  it("posts to /creative/inspect through the authenticated helper", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ origin: { generator: "unknown" } }), {
      status: 200, headers: { "Content-Type": "application/json" },
    }));
    globalThis.fetch = fetchMock;
    await inspectCreative("a.3mf");
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:4321/creative/inspect", expect.objectContaining({
      method: "POST", body: JSON.stringify({ path: "a.3mf" }),
    }));
  });

  it("maps a backend refusal to its message", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ error: "invalid", message: "That path is not a file Studio can read." }), { status: 400 }));
    await expect(inspectCreative("nope.3mf")).rejects.toMatchObject({ message: "That path is not a file Studio can read." });
  });

  it("keeps an unknown origin unknown and an ambiguous one undecided", () => {
    expect(originSentence({ generator: "unknown", status: "unknown", candidates: [] })).toContain("Origin unknown");
    expect(originSentence({ generator: "unknown", status: "ambiguous", candidates: ["forcaslicer", "lixnix"] }))
      .toBe("Origin not decided: the settings match FOrcaSlicer and LixNix Full Multi-Nozzle.");
    expect(originSentence({ generator: "fullspectrum", status: "detected", candidates: ["fullspectrum"] })).toContain("Looks like FullSpectrum");
  });
});
