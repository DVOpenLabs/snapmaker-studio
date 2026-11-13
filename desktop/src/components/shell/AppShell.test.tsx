// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { Home } from "lucide-react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/webview", () => ({ getCurrentWebview: () => { throw new Error("not in Tauri"); } }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 1, token: "t" }) }));
vi.mock("@/api", () => ({ library: vi.fn().mockResolvedValue([]), health: vi.fn().mockResolvedValue({}) }));
vi.mock("@/routes/ext/meta", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/routes/ext/meta")>(),
  extensionTitleFor: (path: string) => path === "/synthetic" || path.startsWith("/synthetic/") ? "Synthetic Tool" : undefined,
}));
import * as api from "@/api";
const openFile = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useOpenFile", () => ({ useOpenFile: () => openFile }));
declare const __APP_VERSION__: string;
(globalThis as any).__APP_VERSION__ = "test";

import { AppShell } from "@/components/shell/AppShell";
import { AdvancedNav } from "@/components/shell/Sidebar";

function GoThis() {
  const nav = useNavigate();
  const { pathname } = useLocation();
  return <><button onClick={() => nav("/this-print")}>go</button><output data-testid="path">{pathname}</output></>;
}

const mount = (start = "/") => render(
  <QueryClientProvider client={new QueryClient()}>
    <MemoryRouter initialEntries={[start]}>
      <Routes><Route element={<AppShell />}><Route path="*" element={<GoThis />} /></Route></Routes>
    </MemoryRouter>
  </QueryClientProvider>,
);
afterEach(cleanup);

describe("Studio+ sidebar heading", () => {
  it("renders a group heading only when grouped items exist", () => {
    const emptyMarkup = renderToStaticMarkup(<MemoryRouter><AdvancedNav items={[]} /></MemoryRouter>);
    expect(emptyMarkup).not.toContain("Studio+");
    const groupedMarkup = renderToStaticMarkup(<MemoryRouter><AdvancedNav items={[
      { to: "/synthetic", label: "Synthetic", icon: Home, group: "Studio+" },
    ]} /></MemoryRouter>);
    expect(groupedMarkup).toMatch(/role="group" aria-labelledby="(nav-group-[^"]*-studio-[^"]*)"/);
    const id = /aria-labelledby="([^"]+)"/.exec(groupedMarkup)?.[1];
    expect(groupedMarkup).toContain(`id="${id}"`);
    expect(groupedMarkup.match(/>Studio\+<\/div>/g)).toHaveLength(1);
  });

  it("gives two simultaneously mounted navs distinct heading ids", () => {
    const items = [{ to: "/synthetic", label: "Synthetic", icon: Home, group: "Studio+" }];
    const markup = renderToStaticMarkup(<MemoryRouter><AdvancedNav items={items} /><AdvancedNav items={items} /></MemoryRouter>);
    const ids = [...markup.matchAll(/aria-labelledby="([^"]+)"/g)].map((m) => m[1]);
    expect(ids).toHaveLength(2);
    expect(new Set(ids).size).toBe(2);
  });
});

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
    expect(within(dialog).getByRole("link", { name: "This job" })).toBeTruthy();
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

  it("aria-controls is present only while its target exists", () => {
    mount();
    const menu = screen.getByRole("button", { name: "Menu" });
    expect(menu.getAttribute("aria-controls")).toBeNull();
    act(() => { fireEvent.click(menu); });
    const id = menu.getAttribute("aria-controls");
    expect(id).toBe("nav-drawer");
    expect(document.getElementById(id!)).toBeTruthy();
    act(() => { fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" }); });
    expect(menu.getAttribute("aria-controls")).toBeNull();
  });

  it("choosing a recent project closes the drawer and focuses the page, even when the route does not change", async () => {
    vi.mocked(api.library).mockResolvedValue([{ id: 1, name: "Bracket.3mf", source_path: "C:\w\Bracket.3mf" }] as any);
    mount("/this-print");
    await act(async () => {});
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Menu" })); });
    await act(async () => {});
    const recent = within(screen.getByRole("dialog")).getByRole("button", { name: "Bracket.3mf" });
    act(() => { fireEvent.click(recent); });
    // Started on the job screen and the recent opens the job screen: the pathname does not change.
    expect(screen.getByTestId("path").textContent).toBe("/this-print");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("main"));
  });

  it.each([
    ["a file is chosen", () => Promise.resolve()],
    ["the picker is cancelled", () => Promise.resolve(undefined)],
  ])("Open a model in the drawer closes it and focuses the page when %s", async (_label, impl) => {
    openFile.mockReset(); openFile.mockImplementation(impl);
    mount();
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Menu" })); });
    act(() => { fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /Open a model/ })); });
    await act(async () => {});
    expect(openFile).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
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

  it("uses the metadata title for extension route segments", () => {
    mount("/synthetic/child");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Synthetic Tool");
  });
});
