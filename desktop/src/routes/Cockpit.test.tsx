// @vitest-environment jsdom
import React from "react";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 1, token: "t" }) }));
vi.mock("@/api", () => ({ doctor: vi.fn(), convert: vi.fn(), diff: vi.fn() }));
vi.mock("@/components/PlacementCard", () => ({ PlacementCard: () => null }));
vi.mock("@/components/PreflightCard", () => ({ PreflightCard: () => null }));
vi.mock("@/components/ColorPlanCard", () => ({ ColorPlanCard: () => null }));
vi.mock("@/components/FidelityCard", () => ({ FidelityCard: () => null }));
vi.mock("@/components/FixLedgerCard", () => ({ FixLedgerCard: () => null }));
vi.mock("@/components/OrcaRoundTrip", () => ({ OrcaRoundTrip: () => null }));
vi.mock("@/components/SlicedJobCards", () => ({ SlicedJobCards: () => null }));
// The real handoff talks to Tauri; here only whether and for what it is offered matters.
vi.mock("@/components/OrcaHandoff", () => ({
  OrcaHandoff: (p: { outputPath: string }) => <div data-testid="handoff">{p.outputPath}</div>,
}));

import Cockpit from "@/routes/Cockpit";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";

const FILE = { path: "C:\\work\\p.3mf", name: "p.3mf", ext: "3mf" };
const convert = (data: object | null, status = "done") => ({ status, data, error: null }) as any;
const view = () => render(<MemoryRouter><Cockpit /></MemoryRouter>);

beforeEach(() => {
  useSession.setState({ file: FILE as any, doctor: { status: "done", data: { verdict: "READY" }, error: null } as any, convert: convert(null, "idle") });
  useSliced.setState({ path: null, name: null });
});
afterEach(cleanup);

describe("This job", () => {
  it("leads with the job header: the project, the steps and one next action", () => {
    view();
    expect(screen.getByRole("heading", { name: /p\.3mf/ })).toBeTruthy();
    expect(screen.getByRole("list", { name: "Job progress" })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Prepare a U1 copy");
  });

  it("offers no Orca handoff before a prepared copy exists", () => {
    view();
    expect(screen.queryByTestId("handoff")).toBeNull();
    expect(screen.getByText("Nothing prepared yet.")).toBeTruthy();
  });

  it("offers the handoff for the validated copy, and names it", () => {
    useSession.setState({ convert: convert({ validated_ok: true, blocked: false, output_path: "C:\\work\\p_U1.3mf", output_name: "p_U1.3mf" }) });
    view();
    expect(screen.getByTestId("handoff").textContent).toBe("C:\\work\\p_U1.3mf");
    expect(screen.getByRole("status").textContent).toContain("Open p_U1.3mf in Snapmaker Orca");
  });

  it.each([
    ["not validated", { validated_ok: false, blocked: false, output_path: "C:\\work\\p_U1.3mf" }],
    ["blocked", { validated_ok: true, blocked: true, output_path: "C:\\work\\p_U1.3mf" }],
  ])("a %s result is not handed to Orca", (_label, data) => {
    useSession.setState({ convert: convert(data) });
    view();
    expect(screen.queryByTestId("handoff")).toBeNull();
  });

  it("a written but unvalidated copy is named as such, never as nothing prepared", () => {
    useSession.setState({ convert: convert({ validated_ok: false, blocked: false, output_path: "C:\work\p_U1.3mf", output_name: "p_U1.3mf" }) });
    view();
    const stage = screen.getByRole("region", { name: "2. Prepared" });
    expect(within(stage).getByText(/A copy was written, but its check found issues./)).toBeTruthy();
    expect(within(stage).getByText(/not offered to Snapmaker Orca/)).toBeTruthy();
    expect(within(stage).queryByText("Nothing prepared yet.")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("A copy was written, but its check found issues");
  });

  it("a refused prepare is not shown as an unvalidated copy", () => {
    useSession.setState({ convert: convert({ validated_ok: true, blocked: true, output_path: null }) });
    view();
    const stage = screen.getByRole("region", { name: "2. Prepared" });
    expect(within(stage).queryByText(/A copy was written/)).toBeNull();
  });

  it("keeps the stages and the full-checks route reachable, once", () => {
    view();
    expect(screen.getAllByRole("link", { name: /Open the full checks/ })).toHaveLength(1);
    expect(screen.getByRole("link", { name: /Open the full checks/ }).getAttribute("href")).toBe("/compatibility");
    expect(screen.getByRole("region", { name: "2. Prepared" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "3. After slicing" })).toBeTruthy();
  });

  it("without a project it asks for one and keeps the route to My designs", () => {
    useSession.setState({ file: null });
    view();
    expect(screen.getByText("Open a model to start")).toBeTruthy();
    expect(screen.getByRole("link", { name: "My designs" }).getAttribute("href")).toBe("/projects");
  });
});
