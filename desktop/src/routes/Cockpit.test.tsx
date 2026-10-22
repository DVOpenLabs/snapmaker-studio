// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 1, token: "t" }) }));
vi.mock("@/api", () => ({
  doctor: vi.fn(), convert: vi.fn(), diff: vi.fn(), detectOrca: vi.fn(), openInOrca: vi.fn(), openModelDialog: vi.fn(), compatibilityCheck: vi.fn(),
}));
vi.mock("@/components/PlacementCard", () => ({
  usePlacement: () => ({ check: null, failed: false, fix: null, fixing: false, runFix: vi.fn() }),
  PlacementView: () => <div data-testid="placement-view" />,
}));
vi.mock("@/components/PreflightCard", () => ({ PreflightCard: () => <div data-testid="preflight" /> }));
vi.mock("@/components/ColorPlanCard", () => ({ ColorPlanCard: () => <div data-testid="colorplan" /> }));
vi.mock("@/components/FidelityCard", () => ({ FidelityCard: () => null }));
vi.mock("@/components/FixLedgerCard", () => ({ FixLedgerCard: () => null }));
vi.mock("@/components/JobWorkspaceCard", () => ({ JobWorkspaceCard: () => <div data-testid="job-record" /> }));
vi.mock("@/components/job/SliceCompare", () => ({ SliceCompare: (p: { preparedPath: string | null }) => <div data-testid="slice-compare">{p.preparedPath ?? "none"}</div> }));
// Project Materials has its own tests. Here only the contract with the job screen matters: it hands choices to Prepare.
vi.mock("@/components/ProjectMaterialsCard", () => ({
  ProjectMaterialsCard: (p: { onPrepare: (m: unknown[]) => Promise<unknown>; onActiveChange?: (a: boolean) => void; busy?: boolean }) => (
    <div data-testid="materials" data-busy={String(!!p.busy)}>
      <button onClick={() => p.onActiveChange?.(true)}>choose</button>
      <button onClick={() => void p.onPrepare([{ slot: 0 }]).catch(() => {})}>prepare with choices</button>
    </div>
  ),
  BlockedPanel: () => <div data-testid="blocked-panel" />,
  ProjectMaterialsFidelity: () => null,
}));

import * as api from "@/api";
import Cockpit from "@/routes/Cockpit";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";

const A = { path: "C:\\work\\a.3mf", name: "a.3mf", ext: "3mf" };
const B = { path: "C:\\work\\b.3mf", name: "b.3mf", ext: "3mf" };
const copyOf = (p: { path: string }, over: object = {}) => {
  const out = p.path.replace(".3mf", "_U1.3mf");
  return { blocked: false, validated_ok: true, output_path: out, output_name: out.split("\\").pop(), prepare_mode: "preserve", settings_summary: null, ...over } as any;
};
const view = () => render(<MemoryRouter><Cockpit /></MemoryRouter>);
const settle = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });
const open = (file: typeof A) => act(() => { useSession.getState().setFile(file.path); });
const create = () => fireEvent.click(screen.getByRole("button", { name: "Create U1 copy" }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.doctor).mockResolvedValue({ verdict: "READY", prepare_blocked: false } as any);
  vi.mocked(api.diff).mockResolvedValue({} as any);
  vi.mocked(api.compatibilityCheck).mockResolvedValue({ findings: [] } as any);
  vi.mocked(api.detectOrca).mockResolvedValue("C:\\Orca\\orca.exe");
  vi.mocked(api.openInOrca).mockResolvedValue(undefined);
  useSession.getState().reset();
  useSliced.setState({ path: null, name: null });
});
afterEach(cleanup);

async function openChecked(file = A) {
  view();
  await open(file);
  await settle();
}

describe("This job: the screen", () => {
  it("without a project it offers Open project and keeps the route to My designs and the saved job", () => {
    view();
    expect(screen.getByRole("button", { name: /Open project/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: "My designs" }).getAttribute("href")).toBe("/projects");
    expect(screen.getByTestId("job-record")).toBeTruthy();
  });

  it("opening a file shows the file, the five stages and exactly one primary action", async () => {
    await openChecked();
    expect(screen.getByRole("heading", { name: "a.3mf" })).toBeTruthy();
    const steps = within(screen.getByRole("list", { name: "Job progress" })).getAllByRole("button");
    expect(steps.map((b) => b.textContent?.replace(/,.*$/, ""))).toEqual([
      "Open project", "Choose materials", "Create U1 copy", "Open in Orca", "Compare slice",
    ]);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Create U1 copy" })).toBeTruthy();
    expect(screen.getByRole("tablist", { name: "Job settings" })).toBeTruthy();
  });

  it("opening or restoring a job never prepares, launches or slices by itself", async () => {
    await openChecked();
    expect(api.convert).not.toHaveBeenCalled();
    expect(api.openInOrca).not.toHaveBeenCalled();
  });

  it("keeps the full checks reachable, once", async () => {
    await openChecked();
    expect(screen.getAllByRole("link", { name: /Full checks/ })).toHaveLength(1);
    expect(screen.getByRole("link", { name: /Full checks/ }).getAttribute("href")).toBe("/compatibility");
  });
});

describe("This job: creating the copy", () => {
  it("Create U1 copy prepares once, in the chosen mode, then offers Open in Orca for the validated copy and names it", async () => {
    vi.mocked(api.convert).mockResolvedValue(copyOf(A));
    await openChecked();
    create(); await settle();
    expect(api.convert).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.convert).mock.calls[0].slice(0, 4)).toEqual([A.path, undefined, "preserve", false]);
    expect(screen.getByText("U1 copy created")).toBeTruthy();
    expect(screen.getByTestId("copy-name").textContent).toBe("a_U1.3mf");
    expect(screen.getByRole("button", { name: "Open in Orca" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Create U1 copy" })).toBeNull();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("the handoff is explicit: nothing opens until the button is pressed", async () => {
    vi.mocked(api.convert).mockResolvedValue(copyOf(A));
    await openChecked();
    create(); await settle();
    expect(api.openInOrca).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Open in Orca" })); });
    expect(api.openInOrca).toHaveBeenCalledWith("C:\\work\\a_U1.3mf");
  });

  it.each([
    ["not validated", { validated_ok: false }],
    ["blocked", { blocked: true, output_path: null }],
  ])("a %s result is never handed to Orca", async (_label, over) => {
    vi.mocked(api.convert).mockResolvedValue(copyOf(A, over));
    await openChecked();
    create(); await settle();
    expect(screen.queryByRole("button", { name: "Open in Orca" })).toBeNull();
  });

  it("a written but unvalidated copy is named as such and the original is said to be untouched", async () => {
    vi.mocked(api.convert).mockResolvedValue(copyOf(A, { validated_ok: false }));
    await openChecked();
    create(); await settle();
    const note = screen.getByTestId("copy-unvalidated");
    expect(note.textContent).toContain("A copy was written, but its check found issues.");
    expect(note.textContent).toContain("not offered to Snapmaker Orca");
    expect(note.textContent).toContain("original was not changed");
  });

  it("a refusal is shown where the result goes, with the plain reason", async () => {
    vi.mocked(api.convert).mockRejectedValue(new Error("This project uses a feature Studio cannot carry over."));
    await openChecked();
    create(); await settle();
    expect(screen.getByTestId("prepare-refusal").textContent).toContain("cannot carry over");
    expect(screen.queryByRole("button", { name: "Open in Orca" })).toBeNull();
  });

  it("an answer with no file is said so, not shown as success", async () => {
    vi.mocked(api.convert).mockResolvedValue(copyOf(A, { output_path: "" }));
    await openChecked();
    create(); await settle();
    expect(screen.getByTestId("prepare-no-file")).toBeTruthy();
  });

  it("material choices go through Prepare with the selections, and a plain Create is replaced by Review materials", async () => {
    vi.mocked(api.convert).mockResolvedValue(copyOf(A));
    await openChecked();
    fireEvent.click(screen.getByRole("button", { name: "choose" }));
    expect(screen.queryByRole("button", { name: "Create U1 copy" })).toBeNull();
    expect(screen.getByRole("button", { name: "Review materials" })).toBeTruthy();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "prepare with choices" })); });
    await settle();
    expect(vi.mocked(api.convert).mock.calls[0][4]).toEqual([{ slot: 0 }]);
  });

  it("a project Studio cannot prepare says why, offers no Create, and sends no request", async () => {
    vi.mocked(api.doctor).mockResolvedValue({ verdict: "HIGH_RISK", prepare_blocked: true, prepare_blocked_summary: "Studio can read this project but cannot prepare it." } as any);
    await openChecked();
    expect(screen.getByTestId("job-blocked").textContent).toContain("cannot prepare it");
    const primary = screen.getByRole("button", { name: "Create U1 copy" }) as HTMLButtonElement;
    expect(primary.disabled).toBe(true);
    fireEvent.click(primary);
    expect(api.convert).not.toHaveBeenCalled();
    expect(screen.queryByTestId("materials")).toBeNull();
  });

  it.each([
    ["unreadable", "project.unreadable", /cannot read this file as a project/],
    ["refused", "prepare.blocked", /cannot prepare a U1 copy of it yet/],
  ])("a %s project (engine eligibility) offers no Create and sends no request", async (_label, id, copy) => {
    vi.mocked(api.compatibilityCheck).mockResolvedValue({ findings: [{ id }] } as any);
    await openChecked();
    expect(screen.getByTestId("job-blocked").textContent).toMatch(copy);
    const primary = screen.getByRole("button", { name: "Create U1 copy" }) as HTMLButtonElement;
    expect(primary.disabled).toBe(true);
    fireEvent.click(primary);
    expect(api.convert).not.toHaveBeenCalled();
    expect(screen.queryByTestId("materials")).toBeNull();
  });

  it("Create waits for the eligibility answer, so a slow check can never be raced", async () => {
    let answer!: (v: unknown) => void;
    vi.mocked(api.compatibilityCheck).mockReturnValue(new Promise((r) => { answer = r; }) as any);
    await openChecked();
    expect((screen.getByRole("button", { name: "Create U1 copy" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { answer({ findings: [] }); await Promise.resolve(); });
    expect((screen.getByRole("button", { name: "Create U1 copy" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("an STL is not asked for 3MF eligibility and can be created", async () => {
    vi.mocked(api.convert).mockResolvedValue({ blocked: false, validated_ok: true, output_path: "C:\work\m_U1.3mf", output_name: "m_U1.3mf", prepare_mode: "preserve", settings_summary: null } as any);
    view();
    await act(async () => { useSession.getState().setFile("C:\work\m.stl"); });
    await settle();
    expect(api.compatibilityCheck).not.toHaveBeenCalled();
    create(); await settle();
    expect(screen.getByTestId("copy-name").textContent).toBe("m_U1.3mf");
  });

  it("an unusable file shows the engine's plain recommendation, and the engine still decides what Create does", async () => {
    vi.mocked(api.doctor).mockResolvedValue({ verdict: "HIGH_RISK", prepare_blocked: false, recommended_action: "This file is not a 3MF project and cannot be diagnosed." } as any);
    await openChecked();
    expect(screen.getByTestId("job-high-risk").textContent).toContain("cannot be diagnosed");
    expect((screen.getByRole("button", { name: "Create U1 copy" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("a failed check offers Check again and does not start a preparation", async () => {
    vi.mocked(api.doctor).mockRejectedValue(new Error("unreadable"));
    await openChecked();
    expect(screen.getByRole("alert").textContent).toContain("could not read this project");
    expect(screen.getByRole("button", { name: "Check again" })).toBeTruthy();
    expect(api.convert).not.toHaveBeenCalled();
  });
});

describe("This job: old results never look current", () => {
  it("project A, then B, then A again: nothing made for A reappears", async () => {
    vi.mocked(api.convert).mockResolvedValue(copyOf(A));
    await openChecked(A);
    create(); await settle();
    expect(screen.getByTestId("copy-name").textContent).toBe("a_U1.3mf");

    await open(B); await settle();
    expect(screen.getByRole("heading", { name: "b.3mf" })).toBeTruthy();
    expect(screen.queryByText("U1 copy created")).toBeNull();
    expect(screen.queryByRole("button", { name: "Open in Orca" })).toBeNull();
    expect(screen.getByRole("button", { name: "Create U1 copy" })).toBeTruthy();

    await open(A); await settle();
    expect(screen.queryByText("U1 copy created")).toBeNull();
    expect(screen.queryByRole("button", { name: "Open in Orca" })).toBeNull();
  });

  it("the same path opened again starts over, including a refusal that was on screen", async () => {
    vi.mocked(api.convert).mockRejectedValue(new Error("refused"));
    await openChecked(A);
    create(); await settle();
    expect(screen.getByTestId("prepare-refusal")).toBeTruthy();
    await open(A); await settle();
    expect(screen.queryByTestId("prepare-refusal")).toBeNull();
    expect(screen.getByRole("button", { name: "Create U1 copy" })).toBeTruthy();
  });

  it("a late answer for A is dropped after B is open, and is not published", async () => {
    let finish!: (v: unknown) => void;
    vi.mocked(api.convert).mockReturnValue(new Promise((r) => { finish = r; }) as any);
    await openChecked(A);
    create(); await settle();
    expect(screen.getByRole("status").textContent).toContain("Creating the U1 copy");
    await open(B); await settle();
    await act(async () => { finish(copyOf(A)); await Promise.resolve(); });
    expect(screen.queryByText("U1 copy created")).toBeNull();
    expect(useSession.getState().convert.status).toBe("idle");
    expect(screen.queryByRole("button", { name: "Open in Orca" })).toBeNull();
  });

  it("a second Create while the first is running: only the newer answer is shown", async () => {
    const answers: Array<(v: unknown) => void> = [];
    vi.mocked(api.convert).mockImplementation(() => new Promise((r) => { answers.push(r); }) as any);
    await openChecked(A);
    create(); await settle();
    // The first request is still in flight; a second one (for example through Review materials) supersedes it.
    fireEvent.click(screen.getByRole("button", { name: "prepare with choices" }));
    await settle();
    expect(answers).toHaveLength(2);
    await act(async () => { answers[0](copyOf(A, { output_path: "C:\\work\\old_U1.3mf", output_name: "old_U1.3mf" })); await Promise.resolve(); });
    expect(screen.queryByText("old_U1.3mf")).toBeNull();
    await act(async () => { answers[1](copyOf(A)); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByTestId("copy-name").textContent).toBe("a_U1.3mf");
  });

  it("a sliced file is compared with the project and the copy that is current", async () => {
    vi.mocked(api.convert).mockResolvedValue(copyOf(A));
    await openChecked(A);
    create(); await settle();
    await act(async () => { useSliced.setState({ path: "C:\\out\\a.gcode", name: "a.gcode" }); });
    // The comparison is already showing, so its button is not offered to press itself.
    expect(screen.getByTestId("slice-compare").textContent).toBe("C:\\work\\a_U1.3mf");
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
    // Looking at the plate again brings the one primary action back.
    fireEvent.click(within(screen.getByRole("list", { name: "Job progress" })).getByRole("button", { name: /Open project/ }));
    expect(screen.getByRole("button", { name: "Compare slice" })).toBeTruthy();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });
});
