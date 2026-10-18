// @vitest-environment jsdom
import React from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 1, token: "t" }) }));
vi.mock("@/api", () => ({
  library: vi.fn(), printerStatus: vi.fn().mockRejectedValue(new Error("offline")), demoReport: vi.fn(), jobCheck: vi.fn(),
}));
vi.mock("@/hooks/useOpenFile", () => ({ useOpenFile: () => vi.fn() }));
vi.mock("@/components/Workflow", () => ({ Workflow: () => <div data-testid="mock-Workflow" /> }));
vi.mock("@/components/HeroMark", () => ({ HeroMark: () => <div data-testid="mock-HeroMark" /> }));
vi.mock("@/components/DoctorsGrid", () => ({ DoctorsGrid: () => <div data-testid="mock-DoctorsGrid" /> }));
vi.mock("@/components/FirstPrintCard", () => ({ FirstPrintCard: () => <div data-testid="mock-FirstPrintCard" /> }));
vi.mock("@/components/IntelligenceReport", () => ({ IntelligenceReport: () => <div data-testid="mock-IntelligenceReport" /> }));

import * as api from "@/api";
import Dashboard from "@/routes/Dashboard";
import { useJob } from "@/store/job";
import { useSession } from "@/store/session";

const RECORD = {
  schema: "job/1", savedAt: "2026-01-01T00:00:00.000Z",
  original: { path: "C:\\work\\A.3mf", name: "A.3mf", fingerprint: { size_bytes: 1, sha256: "a".repeat(64) } },
  prepared: null, sliced: null,
};
const PROJECT = { id: 1, name: "Bracket.3mf", source_path: "C:\\work\\Bracket.3mf", source_family: "orca", output_path: null, verdict: "READY", score: 90, filament_count: 2, last_action: "doctor", updated_at: null };

const mount = async () => {
  const view = render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><Dashboard /></MemoryRouter>
    </QueryClientProvider>,
  );
  await act(async () => {});
  return view;
};
const before = (a: Node, b: Node) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

beforeEach(() => {
  vi.mocked(api.library).mockResolvedValue([]);
  useJob.setState({ record: null, phase: "idle", check: {}, error: null });
  useSession.setState({ file: null });
});
afterEach(cleanup);

describe("Home", () => {
  it("empty: Open a project comes first and the empty state says what to do", async () => {
    await mount();
    const open = screen.getByText("Open a project", { selector: "span.block" });
    expect(before(open, screen.getByText("Recent projects"))).toBe(true);
    expect(await screen.findByText("No projects yet")).toBeTruthy();
    expect(screen.getByText(/Studio reads it on this computer/)).toBeTruthy();
  });

  it("with a saved job: open, then the explicit restore, then recent projects", async () => {
    vi.mocked(api.library).mockResolvedValue([PROJECT] as any);
    useJob.setState({ record: RECORD as any });
    await mount();
    const open = screen.getByText("Open a project", { selector: "span.block" });
    const restore = screen.getByText("Pick up your last job");
    const recent = screen.getByText("Recent projects");
    expect(before(open, restore)).toBe(true);
    expect(before(restore, recent)).toBe(true);
    expect(await screen.findByText("Bracket.3mf")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Check these files" })).toBeTruthy();
    expect(screen.getByText(/Check first: Studio then lists exactly which files it will reopen/)).toBeTruthy();
  });

  it("restoring is never automatic: nothing is checked, opened or prepared until asked", async () => {
    useJob.setState({ record: RECORD as any });
    await mount();
    expect(api.jobCheck).not.toHaveBeenCalled();
    expect(useSession.getState().file).toBeNull();
  });

  it("a library that cannot load says so, with a retry, without losing the open-a-project action", async () => {
    vi.mocked(api.library).mockRejectedValue(new Error("down"));
    await mount();
    expect(screen.getByText("Open a project", { selector: "span.block" })).toBeTruthy();
    expect(await screen.findByText(/Couldn’t load your library/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Retry/ })).toBeTruthy();
  });

  it("keeps every other Home surface, below the action", async () => {
    await mount();
    expect(before(screen.getByText("Open a project", { selector: "span.block" }), screen.getByTestId("mock-DoctorsGrid"))).toBe(true);
    expect(screen.getByTestId("mock-FirstPrintCard")).toBeTruthy();
    expect(screen.getByText("Activity")).toBeTruthy();
  });
});
