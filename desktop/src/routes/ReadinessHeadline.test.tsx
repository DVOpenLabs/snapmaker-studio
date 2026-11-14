// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "@/store/session";

vi.mock("@/api", () => ({
  doctor: vi.fn(), convert: vi.fn(), diff: vi.fn(), openModelDialog: vi.fn(),
}));
// The honest readiness report says setup review remains; every other query is empty.
vi.mock("@tanstack/react-query", async (original) => ({
  ...await original<typeof import("@tanstack/react-query")>(),
  useQuery: (opts: { queryKey: unknown[] }) => ({
    data: opts.queryKey[0] === "report"
      ? { ready: false, readiness_score: 90, verdict: "READY", profile_verdict: "READY", checks: [], preserved: [], changes: [], warnings: [], at_risk: ["13 colours but the U1 has 4 toolheads"] }
      : undefined,
  }),
}));
vi.mock("@/components/StrategyPicker", () => ({ StrategyPicker: () => null }));
vi.mock("@/components/BusinessDoctors", () => ({ BusinessDoctors: () => null }));
vi.mock("@/components/IntelligenceReport", () => ({ IntelligenceReport: () => null }));
vi.mock("@/components/PlacementCard", () => ({ PlacementCard: () => null }));
vi.mock("@/components/PreflightCard", () => ({ PreflightCard: () => null }));
vi.mock("@/components/ColorPlanCard", () => ({ ColorPlanCard: () => null }));
vi.mock("@/components/OrcaHandoff", () => ({ OrcaHandoff: () => null }));

import DesignInsights from "./DesignInsights";

beforeEach(() => {
  useSession.setState({ file: { path: "sample.3mf", name: "sample.3mf", ext: "3mf" },
    doctor: { status: "done", data: { verdict: "READY", score: 100, prepare_blocked: false,
      validation_issues: [], compatibility_issues: [] }, error: null },
    convert: { status: "idle", data: null, error: null },
    preview: { status: "idle", data: null, error: null },
    diff: { status: "idle", data: null, error: null },
    prepareMode: "preserve", runConvert: vi.fn(), previewConvert: vi.fn() });
});
afterEach(cleanup);

describe("DesignInsights headline with a setup warning", () => {
  it("uses readiness wording for a READY project, never the unusable-project label", () => {
    render(<MemoryRouter><QueryClientProvider client={new QueryClient()}><DesignInsights /></QueryClientProvider></MemoryRouter>);
    const headlines = screen.getAllByText("Review before printing");
    expect(headlines.length).toBeGreaterThan(0);
    // review tone (amber), not the unusable-project tone (red) that verdictStatus("HIGH_RISK") has
    for (const el of headlines) {
      expect(el.className).toContain("text-repairable");
      expect(el.className).not.toContain("text-risk");
    }
    expect(screen.queryByText("Needs review")).toBeNull();          // HIGH_RISK's badge label
    expect(screen.queryByText("U1 compatible")).toBeNull();         // and not the green headline
  });
});
