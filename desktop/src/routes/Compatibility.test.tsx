// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { COMPAT_COPY } from "@/lib/compatibility";
import { candidate, slot } from "@/lib/projectMaterials.fixtures";
import type { ProjectMaterialsAnalysis } from "@/lib/projectMaterials";
import { useProvider } from "@/store/provider";
import { useSession } from "@/store/session";

const api = vi.hoisted(() => ({
  open3mfDialog: vi.fn(), compatibilityCheck: vi.fn(), convert: vi.fn(),
  projectMaterials: vi.fn(), materialPresets: vi.fn(), confirmMaterialMapping: vi.fn(),
}));
vi.mock("@/api", () => api);
vi.mock("@/components/PlacementCard", () => ({ PlacementCard: () => null }));
vi.mock("@/components/PreflightCard", () => ({ PreflightCard: () => null }));
vi.mock("@/components/OrcaHandoff", () => ({ OrcaHandoff: () => null }));

import Compatibility from "./Compatibility";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  useProvider.setState({ kind: "spoolman", url: "127.0.0.1:7912", slotMap: {}, slotBase: 1, key: "" });
  useSession.setState({ file: { path: "C:/p/model.3mf", name: "model.3mf", ext: "3mf" } });
  api.materialPresets.mockResolvedValue({ available: true, nozzle: "0.4", presets: [
    { base_name: "Generic PETG", preset_name: "Generic PETG", vendor: "Generic", filament_type: "PETG", fingerprint: "a" }] });
});

const FINDING = { id: "f1", severity: "warning", title: "Printer profile is for another machine", explanation: "x", suggested_action: "y",
  setting_path: "printer_model", evidence: "z" };
const CLEAN = { findings: [], summary: "Nothing to fix.", recommendation: "Looks compatible." };
const WITH_FINDINGS = { findings: [FINDING], summary: "One thing to fix.", recommendation: "Prepare a U1 copy." };

function analysis(over: Partial<ProjectMaterialsAnalysis> = {}): ProjectMaterialsAnalysis {
  return { schema: "project-materials/1", supported: true, nozzle: "0.4",
    catalog: { available: true, source: null, fingerprint: "x" },
    provider: { kind: "spoolman", available: true, error_code: null }, slots: [slot()], ...over };
}

function page() {
  return render(
    <MemoryRouter><QueryClientProvider client={new QueryClient()}><Compatibility /></QueryClientProvider></MemoryRouter>,
  );
}
const materialsCard = () => screen.queryByText("Project materials");
const plainPrepare = () => screen.queryByRole("button", { name: /Prepare U1 copy/ }) as HTMLButtonElement | null;

describe("Project Materials does not depend on compatibility findings", () => {
  it("a compatible project with filament slots still shows Project Materials, and it is not framed as a problem", async () => {
    api.compatibilityCheck.mockResolvedValue(CLEAN);
    api.projectMaterials.mockResolvedValue(analysis());
    page();
    await screen.findByText("Slot 1");
    expect(materialsCard()).toBeTruthy();
    expect(plainPrepare()).toBeNull();                                  // nothing to fix, so no compatibility Prepare
    const card = screen.getByText("Project materials").closest("div[class*='rounded']") as HTMLElement;
    expect(card.innerHTML).not.toMatch(/border-risk|bg-risk\/|text-risk/);   // not an error or a warning
  });

  it("a project with findings and filament slots shows both", async () => {
    api.compatibilityCheck.mockResolvedValue(WITH_FINDINGS);
    api.projectMaterials.mockResolvedValue(analysis());
    page();
    await screen.findByText("Slot 1");
    expect(materialsCard()).toBeTruthy();
    await screen.findByText("Printer profile is for another machine");
    expect(plainPrepare()).toBeTruthy();
  });

  it("the card comes before the compatibility findings", async () => {
    api.compatibilityCheck.mockResolvedValue(WITH_FINDINGS);
    api.projectMaterials.mockResolvedValue(analysis());
    page();
    await screen.findByText("Printer profile is for another machine");
    await screen.findByText("Slot 1");
    const cardNode = materialsCard()!;
    const finding = screen.getByText("Printer profile is for another machine");
    expect(cardNode.compareDocumentPosition(finding) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("no filament slots or an unsupported analysis shows no empty picker, and normal Prepare is unchanged", async () => {
    api.compatibilityCheck.mockResolvedValue(WITH_FINDINGS);
    api.projectMaterials.mockResolvedValue({ schema: "project-materials/1", supported: false, reason: "no slots" });
    const first = page();
    await screen.findByText("Printer profile is for another machine");
    await waitFor(() => expect(api.projectMaterials).toHaveBeenCalled());
    await waitFor(() => expect(materialsCard()).toBeNull());
    expect(plainPrepare()?.disabled).toBe(false);
    first.unmount();
    api.projectMaterials.mockResolvedValue(analysis({ slots: [] }));
    page();
    await screen.findByText("Printer profile is for another machine");
    await waitFor(() => expect(api.projectMaterials).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(materialsCard()).toBeNull());
    expect(plainPrepare()?.disabled).toBe(false);
  });

  it("a clean project with no filament slots shows neither the card nor a Prepare button", async () => {
    api.compatibilityCheck.mockResolvedValue(CLEAN);
    api.projectMaterials.mockResolvedValue({ schema: "project-materials/1", supported: false, reason: "no slots" });
    page();
    await screen.findByText(COMPAT_COPY.cleanTitle);
    await waitFor(() => expect(api.projectMaterials).toHaveBeenCalled());
    expect(materialsCard()).toBeNull();
    expect(plainPrepare()).toBeNull();
  });
});

describe("Project Materials never dead-ends Prepare", () => {
  it("provider unavailable: Keep project's filament is offered and plain Prepare still works", async () => {
    api.compatibilityCheck.mockResolvedValue(WITH_FINDINGS);
    api.projectMaterials.mockResolvedValue(analysis({ provider: { kind: "spoolman", available: false, error_code: "unreachable" },
      slots: [slot({ candidates: [], candidate_count: 0 })] }));
    api.convert.mockResolvedValue({ output_path: "C:/p/out.3mf", output_name: "out.3mf", prepare_mode: "preserve", validated_ok: true,
      settings_summary: { source_has_creator_settings: true, kept_count: 0, compat_changed: [], mapped_to_u1: [], could_not_carry: [],
        warnings: [], recommendations_available: false, recommended_changes: [] }, errors: [] });
    page();
    await screen.findByTestId("provider-down");
    fireEvent.click(screen.getByRole("button", { name: /Keep project's filament/ }));
    expect(screen.getByTestId("keep-own-notice")).toBeTruthy();
    expect(plainPrepare()?.disabled).toBe(false);                       // keeping the project's filament sends nothing, so plain Prepare stands
    fireEvent.click(plainPrepare()!);
    await waitFor(() => expect(api.convert).toHaveBeenCalledWith("C:/p/model.3mf", undefined, "preserve", false, undefined));
  });

  it("no candidates: the person can still pick an installed preset, and plain Prepare is available", async () => {
    api.compatibilityCheck.mockResolvedValue(WITH_FINDINGS);
    api.projectMaterials.mockResolvedValue(analysis({ slots: [slot({ candidates: [], candidate_count: 0 })] }));
    page();
    await screen.findByTestId("no-candidates");
    expect(screen.getByRole("button", { name: "Choose an installed preset" })).toBeTruthy();
    expect(plainPrepare()?.disabled).toBe(false);
  });

  it("nothing is auto-selected, so plain Prepare is not held back until the person chooses", async () => {
    api.compatibilityCheck.mockResolvedValue(WITH_FINDINGS);
    api.projectMaterials.mockResolvedValue(analysis({ slots: [slot({ candidates: [candidate()] })] }));
    page();
    const row = await screen.findByRole("button", { name: /^(?!Forget).*Yoopai PLA Matte/ });
    expect(row.getAttribute("aria-pressed")).toBe("false");
    expect(screen.queryByTestId("selected-spool")).toBeNull();
    expect(plainPrepare()?.disabled).toBe(false);
    expect(api.convert).not.toHaveBeenCalled();
    fireEvent.click(row);                                               // a chosen spool does hold the plain button back
    await waitFor(() => expect(plainPrepare()?.disabled).toBe(true));
    expect(screen.getByText(/Use “Review & prepare” there/)).toBeTruthy();
  });

  it("a read failure from the materials engine does not stop the rest of the page", async () => {
    api.compatibilityCheck.mockResolvedValue(WITH_FINDINGS);
    api.projectMaterials.mockRejectedValue(new Error("engine said no"));
    page();
    await screen.findByText(/engine said no/);
    expect(plainPrepare()?.disabled).toBe(false);
  });
});


describe("one-click Prepare in the other mode never drops the person's choices", () => {
  it("is not offered while Project Materials holds choices", async () => {
    api.compatibilityCheck.mockResolvedValue(WITH_FINDINGS);
    api.projectMaterials.mockResolvedValue(analysis({ slots: [slot({ candidates: [candidate()] })] }));
    api.convert.mockResolvedValue({ output_path: "C:/p/out.3mf", output_name: "out.3mf", prepare_mode: "preserve", validated_ok: true, errors: [],
      settings_summary: { source_has_creator_settings: true, kept_count: 0, compat_changed: [], mapped_to_u1: [], could_not_carry: [], warnings: [],
        recommendations_available: true,
        recommended_changes: [{ key: "print_sequence", old: "by object", new: "by layer", reason: "available with the recommended U1 profile" }] } });
    page();
    const row = await screen.findByRole("button", { name: /^(?!Forget).*Yoopai PLA Matte/ });
    fireEvent.click(plainPrepare()!);
    await screen.findByText("U1 profile copy created");
    expect(screen.getAllByRole("button", { name: /recommended/i }).length).toBeGreaterThan(0);   // offered with no choices held
    fireEvent.click(row);
    await waitFor(() => expect(screen.queryAllByRole("button", { name: /recommended/i }).length).toBe(0));
  });
});


describe("what Project Materials' Prepare did is always visible", () => {
  const SUMMARY = { source_has_creator_settings: true, kept_count: 0, compat_changed: [], mapped_to_u1: [], could_not_carry: [], warnings: [],
    recommendations_available: false, recommended_changes: [],
    project_materials: { fidelity: { schema: "x", mode: "preserve", lines: ["Slot 1: mapped."], slots: [] } } };
  const REVIEW = { schema_version: "convert/2", prepare_mode: "preserve", output_path: "", output_name: "", validated_ok: true, errors: [], settings_summary: SUMMARY };
  const DONE = { ...REVIEW, output_path: "C:/p/out.3mf", output_name: "out.3mf" };

  /** Review (dry run) always succeeds; `real` decides what the actual Prepare does. */
  async function prepareWith(real: () => Promise<any>) {
    api.projectMaterials.mockResolvedValue(analysis({ slots: [slot({ candidates: [candidate({ mapping: {
      status: "proven", match_source: "saved_spool", preset_name: "P @U1", base_name: "P @U1", reason: "", candidates: [], stale: false } })] })] }));
    api.convert.mockImplementation(async (_p: string, _o: unknown, _m: string, dry: boolean) => (dry ? REVIEW : real()));
    page();
    fireEvent.click(await screen.findByRole("button", { name: /^(?!Forget).*Yoopai PLA Matte/ }));
    fireEvent.click(screen.getByRole("button", { name: /Review & prepare/ }));
    await screen.findByText("Slot 1: mapped.");
    fireEvent.click(screen.getByRole("button", { name: "Prepare with these choices" }));
  }

  it("shows success while the compatibility check is still pending", async () => {
    api.compatibilityCheck.mockReturnValue(new Promise(() => {}));
    await prepareWith(async () => DONE);
    await screen.findByText("U1 profile copy created");
    expect(screen.getByTestId("prepare-outcome")).toBeTruthy();
    expect(screen.queryByText("Printer profile is for another machine")).toBeNull();
  });

  it("shows success when the compatibility check failed", async () => {
    api.compatibilityCheck.mockRejectedValue(new Error("no answer"));
    await prepareWith(async () => DONE);
    await screen.findByText("U1 profile copy created");
    expect(screen.getByText(/Couldn't read that file: no answer/)).toBeTruthy();
  });

  it("shows the error when the compatibility check failed and Prepare then fails", async () => {
    api.compatibilityCheck.mockRejectedValue(new Error("no answer"));
    await prepareWith(async () => { throw new Error("engine said no"); });
    await screen.findByText(/Couldn't prepare a copy: engine said no/);
    expect(screen.queryByText("U1 profile copy created")).toBeNull();
  });

  it("shows a blocked Prepare with no compatibility result", async () => {
    api.compatibilityCheck.mockReturnValue(new Promise(() => {}));
    await prepareWith(async () => ({ ...REVIEW, blocked: true, validated_ok: false, errors: ["Prepare stopped: x."],
      settings_summary: { project_materials: { guard: { applies: true, blocking: true, shared: [], warnings: [], resolution: "Pick other presets.",
        conflicts: [{ key: "filament_vendor", preset: "P @U1", slots: [0, 1], declared_in: [0], values: {} }] } } } }));
    await screen.findByTestId("blocked");
    expect(screen.getByText(/Prepare stopped: x\./)).toBeTruthy();
  });

  it("with findings, success still appears and the findings stay conditional on the check", async () => {
    api.compatibilityCheck.mockResolvedValue(WITH_FINDINGS);
    await prepareWith(async () => DONE);
    await screen.findByText("U1 profile copy created");
    expect(await screen.findByText("Printer profile is for another machine")).toBeTruthy();
  });
});


describe("a Prepare that wrote nothing is not reported as a success", () => {
  it("says so, and offers no file to open", async () => {
    api.compatibilityCheck.mockReturnValue(new Promise(() => {}));
    api.projectMaterials.mockResolvedValue(analysis({ slots: [slot({ candidates: [candidate({ mapping: {
      status: "proven", match_source: "saved_spool", preset_name: "P @U1", base_name: "P @U1", reason: "", candidates: [], stale: false } })] })] }));
    const summary = { source_has_creator_settings: true, kept_count: 0, compat_changed: [], mapped_to_u1: [], could_not_carry: [], warnings: [],
      recommendations_available: false, recommended_changes: [],
      project_materials: { fidelity: { schema: "x", mode: "preserve", lines: ["Slot 1: mapped."], slots: [] } } };
    api.convert.mockImplementation(async (_p: string, _o: unknown, _m: string, dry: boolean) => ({
      schema_version: "convert/2", prepare_mode: "preserve", output_path: "", output_name: "", validated_ok: true, errors: [], settings_summary: summary, dry }));
    page();
    fireEvent.click(await screen.findByRole("button", { name: /^(?!Forget).*Yoopai PLA Matte/ }));
    fireEvent.click(screen.getByRole("button", { name: /Review & prepare/ }));
    await screen.findByText("Slot 1: mapped.");
    fireEvent.click(screen.getByRole("button", { name: "Prepare with these choices" }));
    await screen.findByTestId("prepare-no-file");
    expect(screen.queryByText("U1 profile copy created")).toBeNull();
    expect(screen.queryByRole("button", { name: /Copy path/ })).toBeNull();
  });
});
