// @vitest-environment jsdom
import React from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 1, token: "t" }) }));
vi.mock("@/api", () => ({
  library: vi.fn(), printerStatus: vi.fn(), demoReport: vi.fn(), jobCheck: vi.fn(),
}));
vi.mock("@/hooks/useOpenFile", () => ({ useOpenFile: () => vi.fn() }));
vi.mock("@/components/Workflow", () => ({ Workflow: () => <div /> }));
vi.mock("@/components/HeroMark", () => ({ HeroMark: () => <div /> }));
vi.mock("@/components/DoctorsGrid", () => ({ DoctorsGrid: () => <div /> }));
vi.mock("@/components/FirstPrintCard", () => ({ FirstPrintCard: () => <div /> }));
vi.mock("@/components/IntelligenceReport", () => ({ IntelligenceReport: () => <div /> }));

import * as api from "@/api";
import Dashboard from "@/routes/Dashboard";
import { usePrinter } from "@/store/printer";

const mount = async () => {
  const view = render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><Dashboard /></MemoryRouter>
    </QueryClientProvider>,
  );
  await act(async () => {});
  return view;
};

beforeEach(() => {
  vi.mocked(api.library).mockResolvedValue([]);
  vi.mocked(api.printerStatus).mockReset();
});
afterEach(() => { cleanup(); usePrinter.setState({ host: "" }); });

describe("Home and the printer", () => {
  it("an untouched profile never looks a printer up, and says no printer is set up", async () => {
    usePrinter.setState({ host: "" });
    await mount();
    expect(api.printerStatus).not.toHaveBeenCalled();
    expect(screen.getByText(/No printer is set up yet/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /Set up your printer/ })).toBeTruthy();
    expect(screen.queryByText(/Checking/)).toBeNull();
  });

  it("a saved address is looked up, and 'could not reach' is a different message from 'not set up'", async () => {
    usePrinter.setState({ host: "u1.example" });
    vi.mocked(api.printerStatus).mockRejectedValue(new Error("offline"));
    await mount();
    expect(await screen.findByText(/Could not reach u1\.example/)).toBeTruthy();
    expect(api.printerStatus).toHaveBeenCalledWith("u1.example");
    expect(screen.queryByText(/No printer is set up yet/)).toBeNull();
  });
});
