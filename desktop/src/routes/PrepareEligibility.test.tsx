// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "@/store/session";
import { buildFixPlan } from "@/components/FixPlan";

vi.mock("@/api", () => ({
  doctor: vi.fn(), convert: vi.fn(), diff: vi.fn(), openModelDialog: vi.fn(),
}));
vi.mock("@tanstack/react-query", async (original) => ({
  ...await original<typeof import("@tanstack/react-query")>(),
  useQuery: () => ({ data: undefined }),
}));
vi.mock("@/components/StrategyPicker", () => ({ StrategyPicker: () => null }));
vi.mock("@/components/BusinessDoctors", () => ({ BusinessDoctors: () => null }));
vi.mock("@/components/IntelligenceReport", () => ({ IntelligenceReport: () => null }));
vi.mock("@/components/PlacementCard", () => ({ PlacementCard: () => null }));
vi.mock("@/components/PreflightCard", () => ({ PreflightCard: () => null }));
vi.mock("@/components/ColorPlanCard", () => ({ ColorPlanCard: () => null }));
vi.mock("@/components/OrcaHandoff", () => ({ OrcaHandoff: () => null }));

import DesignInsights from "./DesignInsights";
import LiveWorkspace from "./LiveWorkspace";

const runConvert = vi.fn();
const previewConvert = vi.fn();
const summary = { source_has_creator_settings: true, kept_count: 1, compat_changed: [],
  could_not_carry: [], warnings: [], recommendations_available: true,
  recommended_changes: [{ key: "layer_height", old: "0.2", new: "0.16" }] };

beforeEach(() => {
  vi.clearAllMocks();
  useSession.setState({ file: { path: "sample.3mf", name: "sample.3mf", ext: "3mf" },
    doctor: { status: "done", data: { verdict: "REPAIRABLE", score: 100,
      prepare_blocked: true, validation_issues: ["Review the original in Snapmaker Orca."],
      compatibility_issues: [] }, error: null },
    convert: { status: "idle", data: null, error: null },
    preview: { status: "idle", data: null, error: null },
    diff: { status: "idle", data: null, error: null },
    prepareMode: "preserve", runConvert, previewConvert });
});
afterEach(cleanup);

function page(Route: typeof DesignInsights) {
  return render(<MemoryRouter><QueryClientProvider client={new QueryClient()}>
    <Route />
  </QueryClientProvider></MemoryRouter>);
}

describe.each([DesignInsights, LiveWorkspace])("Prepare eligibility in %s", (Route) => {
  it("disables every primary Prepare action and the settings preview", () => {
    page(Route);
    expect(screen.getAllByText("Review in Orca first").length).toBeGreaterThan(0);
    const actions = [...screen.getAllByRole("button", { name: "Prepare U1 copy" }),
      screen.getByRole("button", { name: "Review settings" })] as HTMLButtonElement[];
    expect(actions.length).toBeGreaterThanOrEqual(2);
    for (const action of actions) {
      expect(action.disabled).toBe(true);
      fireEvent.click(action);
    }
    expect(runConvert).not.toHaveBeenCalled();
    expect(previewConvert).not.toHaveBeenCalled();
    if (Route === DesignInsights) {
      expect(screen.queryByText("Prepare a U1 profile copy")).toBeNull();
      expect(screen.getByText("Review the original in Snapmaker Orca")).toBeTruthy();
    }
  });

  it("keeps a stale preview from offering either Prepare mode", () => {
    useSession.setState({ preview: { status: "done", data: { settings_summary: summary,
      prepare_mode: "preserve", schema_version: "convert/1", output_path: "sample-u1.3mf",
      output_name: "sample-u1.3mf", validated_ok: true }, error: null } });
    page(Route);
    expect(screen.getByText("Settings preview")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Prepare with preserved settings" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Prepare with recommended settings" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Prepare another copy with recommended settings" })).toBeNull();
  });

  it("keeps Prepare available for an eligible project", () => {
    useSession.setState({ doctor: { status: "done", data: { verdict: "REPAIRABLE",
      prepare_blocked: false, validation_issues: [], compatibility_issues: [] }, error: null } });
    page(Route);
    const action = screen.getAllByRole("button", { name: "Prepare U1 copy" })[0] as HTMLButtonElement;
    expect(action.disabled).toBe(false);
    fireEvent.click(action);
    expect(runConvert).toHaveBeenCalledOnce();
    expect((screen.getByRole("button", { name: "Review settings" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

it("disables Workspace's refusal retry for a known blocked project", () => {
  useSession.setState({ convert: { status: "error", data: null, error: "Review the original." } });
  page(LiveWorkspace);
  const retry = screen.getByRole("button", { name: "Retry" }) as HTMLButtonElement;
  expect(retry.disabled).toBe(true);
  fireEvent.click(retry);
  expect(runConvert).not.toHaveBeenCalled();
});

it("keeps the blocked project's review step even when other risks fill the fix plan", () => {
  const plan = buildFixPlan({ doctor: { prepare_blocked: true, object_count: 8 }, isStl: false,
    bed: { available: true, overall_level: "risk" },
    mm: { available: true, multi_material: true, overall_level: "risk" },
    mesh: { available: true, integrity: { watertight: false, holes: 1 },
      overhang: { supports_likely: true } } });
  expect(plan).toHaveLength(5);
  expect(plan[plan.length - 1]).toMatchObject({ title: "Review the original in Snapmaker Orca", where: "Orca" });
  expect(plan.some(step => step.title === "Prepare a U1 profile copy")).toBe(false);
});
