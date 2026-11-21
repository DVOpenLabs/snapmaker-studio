// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(async () => { throw new Error("No native shell in browser"); }) }));
import { invoke } from "@tauri-apps/api/core";
afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState({}, "", "/"); });
it("uses the shared dev engine connection after SPA navigation removes the query", async () => {
  vi.resetModules(); vi.mocked(invoke).mockClear();
  window.history.replaceState({}, "", "/creative?api=4321:synthetic-navigation-token");
  const { apiInfo } = await import("@/api");
  expect((await apiInfo()).port).toBe(4321);
  window.history.pushState({}, "", "/recovery");
  const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ status: "ok", last_job: null })));
  vi.stubGlobal("fetch", fetch);
  const { requestMonitoring } = await import("./transport");
  await requestMonitoring("history", { host: "synthetic.local", port: 9411 }, new AbortController().signal);
  expect(invoke).not.toHaveBeenCalled();
  expect(fetch.mock.calls[0][0]).toBe("http://127.0.0.1:4321/monitoring/history");
});
