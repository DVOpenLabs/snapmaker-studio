// @vitest-environment jsdom
import React from "react";
import { act, cleanup, render } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/webview", () => ({ getCurrentWebview: () => { throw new Error("not in Tauri"); } }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 1, token: "t" }) }));
vi.mock("@/api", () => ({ library: vi.fn().mockResolvedValue([]), health: vi.fn().mockResolvedValue({}) }));
vi.mock("@/hooks/useOpenFile", () => ({ useOpenFile: () => vi.fn() }));
(globalThis as any).__APP_VERSION__ = "test";

import { AppShell } from "@/components/shell/AppShell";

let go: (to: string) => void = () => {};
function Probe() {
  const nav = useNavigate();
  go = (to) => nav(to);
  return <div>page</div>;
}

const mount = () => render(
  <QueryClientProvider client={new QueryClient()}>
    <MemoryRouter initialEntries={["/"]}>
      <Routes><Route element={<AppShell />}><Route path="*" element={<Probe />} /></Route></Routes>
    </MemoryRouter>
  </QueryClientProvider>,
);
afterEach(cleanup);

describe("scrolling between pages", () => {
  it("a different page starts at the top of the scrolling area; the same page keeps its place", () => {
    const { container } = mount();
    const main = container.querySelector("main") as HTMLElement;
    main.scrollTop = 600;
    act(() => go("/this-print"));
    expect(main.scrollTop).toBe(0);
    main.scrollTop = 450;
    act(() => go("/this-print?tab=2"));           // same page, only the query changed
    expect(main.scrollTop).toBe(450);
    act(() => go("/this-print#anchor"));          // same page, an anchor decides the position
    expect(main.scrollTop).toBe(450);
    act(() => go("/after-slicing"));
    expect(main.scrollTop).toBe(0);
  });
});
