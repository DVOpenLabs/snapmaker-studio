// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/webview", () => ({ getCurrentWebview: () => { throw new Error("not in Tauri"); } }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 1, token: "t" }) }));
vi.mock("@/api", () => ({ library: vi.fn().mockResolvedValue([]), health: vi.fn().mockResolvedValue({}) }));
vi.mock("@/hooks/useOpenFile", () => ({ useOpenFile: () => vi.fn() }));
declare const __APP_VERSION__: string;
(globalThis as any).__APP_VERSION__ = "test";

import { AppShell } from "@/components/shell/AppShell";

function GoThis() {
  const nav = useNavigate();
  return <button onClick={() => nav("/this-print")}>go</button>;
}

const mount = () => render(
  <QueryClientProvider client={new QueryClient()}>
    <MemoryRouter initialEntries={["/"]}>
      <Routes><Route element={<AppShell />}><Route path="*" element={<GoThis />} /></Route></Routes>
    </MemoryRouter>
  </QueryClientProvider>,
);
afterEach(cleanup);

describe("narrow navigation", () => {
  it("keeps the menu closed until asked, and exposes its state", () => {
    mount();
    const menu = screen.getByRole("button", { name: "Menu" });
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens a modal drawer with the real navigation and puts focus inside it", () => {
    mount();
    const menu = screen.getByRole("button", { name: "Menu" });
    act(() => { fireEvent.click(menu); });
    expect(menu.getAttribute("aria-expanded")).toBe("true");
    const dialog = screen.getByRole("dialog", { name: "Menu" });
    expect(within(dialog).getByRole("link", { name: /This print|This Print/ })).toBeTruthy();
    expect(dialog.contains(document.activeElement)).toBe(true);
    // Focus starts on the first destination, not the scrim.
    expect((document.activeElement as HTMLElement).getAttribute("aria-label")).not.toBe("Close menu");
    expect(document.activeElement?.closest("#nav-drawer")).toBeTruthy();
  });

  it("Escape closes the drawer and returns focus to the Menu button", () => {
    mount();
    const menu = screen.getByRole("button", { name: "Menu" });
    act(() => { fireEvent.click(menu); });
    act(() => { fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" }); });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(menu);
  });

  it("the scrim closes it too", () => {
    mount();
    const menu = screen.getByRole("button", { name: "Menu" });
    act(() => { fireEvent.click(menu); });
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Close menu" })); });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(menu);
  });

  it("choosing a destination closes the drawer and keeps the real route", () => {
    mount();
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Menu" })); });
    const link = within(screen.getByRole("dialog")).getAllByRole("link").find((a) => a.getAttribute("href") === "/this-print")!;
    act(() => { fireEvent.click(link); });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("This job");
    // The link that held focus is gone: focus follows the page, not <body>.
    expect(document.activeElement).toBe(screen.getByRole("main"));
  });

  it("Tab wraps inside the open drawer", () => {
    mount();
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Menu" })); });
    const dialog = screen.getByRole("dialog");
    const items = [...dialog.querySelectorAll<HTMLElement>("a[href],button:not([disabled]):not([tabindex=\"-1\"]),summary,input")];
    items[items.length - 1].focus();
    act(() => { fireEvent.keyDown(dialog, { key: "Tab" }); });
    expect(document.activeElement).toBe(items[0]);
    act(() => { fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true }); });
    expect(document.activeElement).toBe(items[items.length - 1]);
  });

  it("titles the page by what it is", () => {
    mount();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Home");
  });
});
