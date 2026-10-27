import { afterEach, describe, expect, it, vi } from "vitest";
import { buildEvaluateBody, evaluateSetup } from "./setupsApi";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4321, token: "test-token" }) }));
const originalFetch = globalThis.fetch;
Object.defineProperty(globalThis, "location", { configurable: true, value: { search: "" } });
afterEach(() => { globalThis.fetch = originalFetch; vi.restoreAllMocks(); });

describe("setups API", () => {
  it("rejects a port that is not a whole number in range instead of sending null", () => {
    for (const bad of ["abc", "0", "70000", "71.5", "-1"]) {
      expect(() => buildEvaluateBody({ host: "h", port: bad })).toThrow(/port must be a whole number/i);
    }
  });

  it("leaves blank fields out and includes the key only when typed", () => {
    expect(buildEvaluateBody({ host: " u1.local ", port: "", key: "  ", materials: ["", " "] })).toEqual({ host: "u1.local" });
    expect(buildEvaluateBody({ host: "h", port: "7125", key: "k1", materials: ["PLA", " PETG "] })).toEqual({
      host: "h", port: 7125, api_key: "k1", requirements: [{ material: "PLA" }, { material: "PETG" }],
    });
  });

  it("posts to /setups/evaluate and writes nothing to storage", async () => {
    const stored: string[] = [];
    (globalThis as any).localStorage = { setItem: (k: string) => stored.push(k), getItem: () => null };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ report: {}, read: {} }), { status: 200 }));
    globalThis.fetch = fetchMock;
    await evaluateSetup({ host: "h", api_key: "k1" });
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://127.0.0.1:4321/setups/evaluate");
    expect(stored).toEqual([]);
  });
});
