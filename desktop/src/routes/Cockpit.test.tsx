// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 1, token: "t" }) }));
vi.mock("@/api", () => ({
  doctor: vi.fn(), convert: vi.fn(), diff: vi.fn(), detectOrca: vi.fn(), openInOrca: vi.fn(), openModelDialog: vi.fn(), compatibilityCheck: vi.fn(), paintedPreview: vi.fn(),
}));
vi.mock("@/components/PlacementCard", () => ({
  usePlacement: () => ({ check: null, failed: false, fix: null, fixing: false, runFix: vi.fn() }),
  PlacementView: () => <div data-testid="placement-view" />,
}));
const preflightMounted = vi.hoisted(() => vi.fn());
vi.mock("@/components/PreflightCard", () => ({ PreflightCard: () => { preflightMounted(); return <div data-testid="preflight" />; } }));
vi.mock("@/components/ColorPlanCard", () => ({ ColorPlanCard: () => <div data-testid="colorplan" /> }));
vi.mock("@/components/FidelityCard", () => ({ FidelityCard: () => null }));
vi.mock("@/components/FixLedgerCard", () => ({ FixLedgerCard: () => null }));
vi.mock("@/components/JobWorkspaceCard", () => ({ JobWorkspaceCard: () => <div data-testid="job-record" /> }));
// The model pane has its own tests. Here only what the job screen hands it matters.
vi.mock("@/components/job/ModelPane", () => ({
  ModelPane: (p: { path: string; selections: { slot: number; colour: string | null }[]; preparedPath: string | null }) => (
    <div data-testid="model-pane" data-path={p.path} data-prepared={p.preparedPath ?? ""} data-choices={p.selections.map((s) => `${s.slot}:${s.colour}`).join(",")} />
  ),
}));
vi.mock("@/components/job/SliceCompare", () => ({ SliceCompare: (p: { preparedPath: string | null }) => <div data-testid="slice-compare">{p.preparedPath ?? "none"}</div> }));
// Project Materials has its own tests. Here only the contract with the job screen matters: it hands choices to Prepare.
vi.mock("@/components/ProjectMaterialsCard", () => ({
  ProjectMaterialsCard: (p: { onPrepare: (m: unknown[]) => Promise<unknown>; onActiveChange?: (a: boolean) => void; onSelectionsChange?: (s: unknown[]) => void; busy?: boolean }) => (
    <div data-testid="materials" data-busy={String(!!p.busy)}>
      <button onClick={() => p.onActiveChange?.(true)}>choose</button>
      <button onClick={() => p.onSelectionsChange?.([{ slot: 1, colour: "#112233" }])}>pick a colour</button>
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

  it("a check that could not run is not a verdict about the file", async () => {
    vi.mocked(api.doctor).mockRejectedValue(new Error("service down"));
    await openChecked();
    expect(screen.queryByTestId("job-blocked")).toBeNull();            // a failed read is not a verdict about the file
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

describe("This job: the model pane", () => {
  it("is given the open project and the material choices made so far, and not another project's", async () => {
    await openChecked(A);
    const pane = () => screen.getByTestId("model-pane");
    expect(pane().getAttribute("data-path")).toBe(A.path);
    expect(pane().getAttribute("data-choices")).toBe("");
    await act(async () => { fireEvent.click(screen.getByText("pick a colour")); });
    expect(pane().getAttribute("data-choices")).toBe("1:#112233");
    // Opening another project starts the screen over: A's choices are not shown against B.
    await open(B); await settle();
    expect(screen.getByTestId("model-pane").getAttribute("data-path")).toBe(B.path);
    expect(screen.getByTestId("model-pane").getAttribute("data-choices")).toBe("");
  });
});

describe("This job: when things change or fail underneath", () => {
  it("control: with no choices held, a finished copy does offer another", async () => {
    vi.mocked(api.convert).mockResolvedValue(copyOf(A));
    await openChecked();
    create(); await settle();
    expect(screen.getByRole("button", { name: /Create another copy/ })).toBeTruthy();
  });

  it("choices made while a copy is being created are not applied to it, and a second plain copy is not offered over them", async () => {
    let finish!: (v: unknown) => void;
    vi.mocked(api.convert).mockImplementation(() => new Promise((r) => { finish = r; }) as any);
    await openChecked();
    create(); await settle();
    expect(vi.mocked(api.convert).mock.calls[0][4]).toBeUndefined();            // the request carried no materials
    fireEvent.click(screen.getByRole("button", { name: "choose" }));            // …and the person now chooses some
    await act(async () => { finish(copyOf(A)); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByTestId("copy-name").textContent).toBe("a_U1.3mf");        // the copy is the one that was asked for
    expect(screen.queryByRole("button", { name: /Create another copy/ })).toBeNull();   // choices held: use Review materials
    expect(api.convert).toHaveBeenCalledTimes(1);
  });

  it("an expired session is said plainly, nothing is shown as created, and the next attempt works", async () => {
    vi.mocked(api.convert).mockRejectedValueOnce(new Error("Studio's local engine rejected this session (401). Reopen the app."));
    vi.mocked(api.convert).mockResolvedValueOnce(copyOf(A));
    await openChecked();
    create(); await settle();
    expect(screen.getByTestId("prepare-refusal").textContent).toContain("rejected this session");
    expect(screen.queryByTestId("copy-name")).toBeNull();
    expect(screen.queryByRole("button", { name: "Open in Orca" })).toBeNull();
    expect(useSession.getState().convert.status).not.toBe("done");
    // Create is available again.
    fireEvent.click(document.querySelector("[data-primary]")!); await settle();
    expect(screen.getByTestId("copy-name").textContent).toBe("a_U1.3mf");
  });

  it("a project with no printer set up, and one whose slicer is not found, can still be opened and given a copy", async () => {
    vi.mocked(api.detectOrca).mockResolvedValue(null as any);
    vi.mocked(api.convert).mockResolvedValue(copyOf(A));
    await openChecked();
    create(); await settle();
    expect(screen.getByTestId("copy-name").textContent).toBe("a_U1.3mf");
    expect(api.openInOrca).not.toHaveBeenCalled();
  });
});

describe("This job: what opening a project does and does not touch", () => {
  it("opening a job does not run the printer comparison; it runs when the Target tab is opened", async () => {
    await openChecked();
    expect(preflightMounted).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("tab", { name: "Target" }));
    expect(preflightMounted).toHaveBeenCalled();
  });

  it("an unusable file offers no materials, and the refusal is said once", async () => {
    vi.mocked(api.doctor).mockResolvedValue({ verdict: "HIGH_RISK", prepare_blocked: false, recommended_action: "This file is not a 3MF project." } as any);
    await openChecked();
    expect(screen.queryByTestId("materials")).toBeNull();
    expect(screen.getByTestId("no-materials").textContent).toMatch(/not offered/);
    expect(screen.getAllByText(/This file is not a 3MF project\./)).toHaveLength(1);
  });

  it("a G-code sliced for project A is not shown as project B's slice", async () => {
    await openChecked(A);
    await act(async () => { useSliced.setState({ path: "C:\out\a.gcode", name: "a.gcode" }); });
    expect(screen.getByTestId("slice-compare")).toBeTruthy();
    await open(B); await settle();
    expect(screen.queryByTestId("slice-compare")).toBeNull();
    expect(screen.getByRole("button", { name: "Create U1 copy" })).toBeTruthy();
  });
});

const UNUSABLE = { verdict: "HIGH_RISK", prepare_blocked: false, recommended_action: "This file is not a 3MF project and cannot be diagnosed." } as any;
const primaryButton = () => screen.getByRole("button", { name: "Create U1 copy" }) as HTMLButtonElement;

describe("This job: a project the engine already calls unusable is not prepared", () => {
  it.each([
    ["not a ZIP .3mf", () => vi.mocked(api.compatibilityCheck).mockRejectedValue(new Error("not a zip"))],
    ["a missing file", () => vi.mocked(api.compatibilityCheck).mockRejectedValue(new Error("no such file"))],
    ["an eligibility answer that looks open", () => vi.mocked(api.compatibilityCheck).mockResolvedValue({ findings: [] } as any)],
  ])("%s: the verdict closes Create, the mode and settings controls and every start, and sends no request", async (_label, setup) => {
    setup();
    vi.mocked(api.doctor).mockResolvedValue(UNUSABLE);
    await openChecked();
    expect(screen.getByTestId("job-blocked").textContent).toContain("cannot be diagnosed");
    expect(primaryButton().disabled).toBe(true);
    fireEvent.click(primaryButton());
    expect(screen.queryByTestId("materials")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Copy settings" }));
    expect((screen.getByRole("button", { name: "Review settings" }) as HTMLButtonElement).disabled).toBe(true);
    for (const radio of screen.getAllByRole("radio")) expect((radio as HTMLInputElement).disabled).toBe(true);
    expect(api.convert).not.toHaveBeenCalled();
  });

  it("says the refusal once and offers a way out: open another project", async () => {
    vi.mocked(api.doctor).mockResolvedValue(UNUSABLE);
    vi.mocked(api.openModelDialog).mockResolvedValue(B.path);
    await openChecked();
    expect(screen.getAllByText(/cannot be diagnosed/)).toHaveLength(1);
    expect(screen.queryByTestId("job-high-risk")).toBeNull();
    expect(screen.queryByRole("link", { name: "See the full checks" })).toBeNull();  // nothing the checks could add for a file that is not a project
    await act(async () => { fireEvent.click(screen.getByTestId("open-another")); await Promise.resolve(); });
    await settle();
    expect(api.openModelDialog).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { name: "b.3mf" })).toBeTruthy();
    expect(api.convert).not.toHaveBeenCalled();                                 // opening another project prepares nothing
  });

  it("controls: a readable or repairable project is still prepared", async () => {
    vi.mocked(api.doctor).mockResolvedValue({ verdict: "REPAIRABLE", prepare_blocked: false, recommended_action: "Prepare a U1 profile copy." } as any);
    vi.mocked(api.convert).mockResolvedValue(copyOf(A));
    await openChecked();
    expect(screen.queryByTestId("job-blocked")).toBeNull();
    expect(primaryButton().disabled).toBe(false);
    create(); await settle();
    expect(screen.getByTestId("copy-name").textContent).toBe("a_U1.3mf");
  });

  it("control: an STL (never an unusable-archive verdict) is prepared", async () => {
    vi.mocked(api.doctor).mockResolvedValue({ verdict: "CONVERTIBLE", prepare_blocked: false, recommended_action: "Create a U1 profile copy." } as any);
    vi.mocked(api.convert).mockResolvedValue({ blocked: false, validated_ok: true, output_path: "C:\work\m_U1.3mf", output_name: "m_U1.3mf", prepare_mode: "preserve", settings_summary: null } as any);
    view();
    await act(async () => { useSession.getState().setFile("C:\work\m.stl"); });
    await settle();
    expect(primaryButton().disabled).toBe(false);
    create(); await settle();
    expect(screen.getByTestId("copy-name").textContent).toBe("m_U1.3mf");
  });

  it("control: an unavailable compatibility service alone does not make a usable project unreadable", async () => {
    vi.mocked(api.compatibilityCheck).mockRejectedValue(new Error("service unavailable"));
    vi.mocked(api.convert).mockResolvedValue(copyOf(A));
    await openChecked();
    expect(screen.queryByTestId("job-blocked")).toBeNull();
    expect(primaryButton().disabled).toBe(false);
    expect(screen.getByTestId("materials")).toBeTruthy();
    create(); await settle();
    expect(screen.getByTestId("copy-name").textContent).toBe("a_U1.3mf");
  });

  it("control: a transport failure of the project check is a failed check, not an unusable project", async () => {
    vi.mocked(api.doctor).mockRejectedValue(new Error("connection refused"));
    await openChecked();
    expect(screen.queryByTestId("job-blocked")).toBeNull();
    expect(screen.queryByTestId("open-another")).toBeNull();
    expect(screen.getByRole("button", { name: "Check again" })).toBeTruthy();
  });

  it("the verdict arriving while a copy is being made drops that copy: it is never published as the current one", async () => {
    let finish!: (v: unknown) => void;
    vi.mocked(api.convert).mockReturnValue(new Promise((r) => { finish = r; }) as any);
    await openChecked();
    create(); await settle();
    expect(screen.getByText("Creating the U1 copy…")).toBeTruthy();
    vi.mocked(api.doctor).mockResolvedValue(UNUSABLE);
    await act(async () => { await useSession.getState().runDoctor(); });
    await settle();
    await act(async () => { finish(copyOf(A)); await Promise.resolve(); });
    await settle();
    expect(screen.queryByText("Creating the U1 copy…")).toBeNull();
    expect(screen.queryByTestId("copy-name")).toBeNull();
    expect(screen.queryByRole("button", { name: "Open in Orca" })).toBeNull();
    expect(useSession.getState().convert.status).not.toBe("done");              // the shared store never took it either
    expect(primaryButton().disabled).toBe(true);
  });

  it("opening another project after the guard closed starts clean: nothing from the refused one carries over", async () => {
    vi.mocked(api.doctor).mockResolvedValueOnce(UNUSABLE).mockResolvedValue({ verdict: "READY", prepare_blocked: false } as any);
    await openChecked(A);
    expect(primaryButton().disabled).toBe(true);
    await open(B); await settle();
    expect(screen.getByRole("heading", { name: "b.3mf" })).toBeTruthy();
    expect(screen.queryByTestId("job-blocked")).toBeNull();
    expect(primaryButton().disabled).toBe(false);
  });
});
