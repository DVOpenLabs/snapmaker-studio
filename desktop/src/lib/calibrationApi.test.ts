import { afterEach, describe, expect, it, vi } from "vitest";
import { evaluateCalibration } from "./calibrationApi";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4321, token: "test-token" }) }));

const originalFetch = globalThis.fetch;
Object.defineProperty(globalThis, "location", { configurable: true, value: { search: "" } });
afterEach(() => { globalThis.fetch = originalFetch; vi.restoreAllMocks(); });

describe("calibration API", () => {
  it("posts the palette and basis to the calibration route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "unknown" }), { status: 200 }));
    globalThis.fetch = fetchMock;
    await evaluateCalibration({ source: "ditherforge_txt", content: "#112233 td Ink", family: "frontlit", layer_height_mm: 0.2 });
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://127.0.0.1:4321/calibration/evaluate");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ family: "frontlit", layer_height_mm: 0.2 });
  });
});
