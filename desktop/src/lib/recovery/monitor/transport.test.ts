import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { apiInfo } from "@/api";
import { requestMonitoring } from "./transport";
vi.mock("@/api", () => ({ apiInfo: vi.fn() }));
Object.defineProperty(globalThis, "location", { configurable: true, value: { search: "" } });
const originalFetch = globalThis.fetch;
beforeEach(() => { vi.mocked(apiInfo).mockResolvedValue({ port: 4321, token: "synthetic-monitor-token" }); });
afterEach(() => { globalThis.fetch = originalFetch; vi.restoreAllMocks(); vi.useRealTimers(); });
it("uses only the local engine monitoring routes and preserves the chosen endpoint", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok", print_state: "standby" })));
  globalThis.fetch = fetch;
  await requestMonitoring("read", { host: "synthetic.local", port: 9411, previous_state: "printing" }, new AbortController().signal);
  expect(fetch.mock.calls[0][0]).toBe("http://127.0.0.1:4321/monitoring/read");
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ host: "synthetic.local", port: 9411, previous_state: "printing" });
  expect(fetch.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
});
it("refuses a malformed engine reply", async () => {
  globalThis.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok" })));
  await expect(requestMonitoring("read", { host: "synthetic.local", port: 9411 }, new AbortController().signal)).rejects.toThrow(/not usable/);
});
it("bounds discovery without AbortSignal.any or AbortSignal.timeout", async () => {
  vi.useFakeTimers();
  vi.spyOn(AbortSignal, "timeout").mockImplementation(() => { throw new Error("unsupported API"); });
  vi.spyOn(AbortSignal, "any").mockImplementation(() => { throw new Error("unsupported API"); });
  vi.mocked(apiInfo).mockReturnValue(new Promise(() => {}));
  const pending = requestMonitoring("read", { host: "synthetic.local", port: 9411 }, new AbortController().signal);
  const refused = expect(pending).rejects.toThrow(/timed out/);
  await vi.advanceTimersByTimeAsync(4000);
  await refused;
});
it("cancels a pending fetch when the monitor stops", async () => {
  globalThis.fetch = vi.fn().mockImplementation((_, options) => new Promise((_, reject) => {
    options.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
  }));
  const stop = new AbortController();
  const pending = requestMonitoring("history", { host: "synthetic.local", port: 9411 }, stop.signal);
  await Promise.resolve(); await Promise.resolve();
  stop.abort();
  await expect(pending).rejects.toThrow(/stopped/);
});


it("shows the engine's bounded refusal explanation instead of only an HTTP code", async () => {
  globalThis.fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify({message:"Use a local network host."}),{status:422}));
  await expect(requestMonitoring("read",{host:"synthetic.local",port:9411},new AbortController().signal)).rejects.toThrow("Use a local network host.");
});
