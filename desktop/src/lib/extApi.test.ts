import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api";
import { callExt } from "./extApi";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4321, token: "test-token" }) }));
const originalFetch = globalThis.fetch;
Object.defineProperty(globalThis, "location", { configurable: true, value: { search: "" } });
afterEach(() => { globalThis.fetch = originalFetch; vi.restoreAllMocks(); });

describe("extension API wrapper", () => {
  it("uses the real authenticated POST helper and maps backend refusal code/message", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: "refusal", message: "The operation was refused." }), {
      status: 422, headers: { "Content-Type": "application/json" },
    }));
    globalThis.fetch = fetchMock;
    await expect(callExt("/setups/list", { host: "local" }, "setups"))
      .rejects.toMatchObject({ name: "Error", message: "The operation was refused.", code: "refusal" });
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:4321/setups/list", expect.objectContaining({
      method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": "test-token" },
      body: JSON.stringify({ host: "local" }),
    }));
  });

  it("maps known invalid errors and gives unknown internal errors the generic route message", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: "invalid_request" }), { status: 422 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: "internal" }), { status: 500 }));
    globalThis.fetch = fetchMock;
    await expect(callExt("/setups/list", {}, "setups")).rejects.toMatchObject({
      name: "Error", message: "That request isn't valid.", code: "invalid_request",
    });
    await expect(callExt("/setups/list", {}, "setups")).rejects.toMatchObject({
      name: "Error", message: "setups failed (500)", code: undefined,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retains the real ApiError class for structured failures", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: "refusal", message: "No." }), { status: 422 }));
    try { await callExt("/setups/list", {}, "setups"); }
    catch (error) { expect(error).toBeInstanceOf(ApiError); return; }
    throw new Error("Expected callExt to reject");
  });
});
