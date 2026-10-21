// @vitest-environment jsdom
// Integration: a copy prepared on the Compatibility route reaches This job and the After slicing receipt.
// Real stores, the real trackJob subscription, the real Compatibility and AfterSlicing routes and the real receipt card;
// only the engine (@/api) is faked. Nothing here injects a finished conversion into a store.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { candidate, slot } from "@/lib/projectMaterials.fixtures";
import type { ProjectMaterialsAnalysis } from "@/lib/projectMaterials";
import { useProvider } from "@/store/provider";

const api = vi.hoisted(() => {
  const names = ["doctor", "convert", "diff", "jobCheck", "compatibilityCheck", "projectMaterials", "materialPresets", "confirmMaterialMapping", "settingsReceipt", "open3mfDialog", "fidelityAudit"];
  const fns: Record<string, ReturnType<typeof vi.fn>> = {};
  for (const n of names) fns[n] = vi.fn();
  return { fns, get: (k: string) => fns[k] };
});
vi.mock("@/api", () => api.fns);
vi.mock("@/components/PlacementCard", () => ({ PlacementCard: () => null }));
vi.mock("@/components/PreflightCard", () => ({ PreflightCard: () => null }));
vi.mock("@/components/OrcaHandoff", () => ({ OrcaHandoff: () => null }));
vi.mock("@/components/JobWorkspaceCard", () => ({ JobWorkspaceCard: () => null }));
vi.mock("@/components/OrcaRoundTrip", () => ({ OrcaRoundTrip: () => null }));
vi.mock("@/components/SlicedJobCards", () => ({ SlicedJobCards: () => null }));

import Compatibility from "./Compatibility";
import AfterSlicing from "./AfterSlicing";
import { trackJob, useJob } from "@/store/job";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";

const A = "C:/p/model.3mf";
const B = "C:/p/other.3mf";
const OUT = "C:/p/model_SnapmakerU1.3mf";
const GCODE = "C:/p/model_PLA_1h.gcode";
const f = (k: string) => api.get(k);

const FINDING = { id: "f1", severity: "warning", title: "Printer profile is for another machine", explanation: "x", suggested_action: "y",
  setting_path: "printer_model", evidence: "z" };
const WITH_FINDINGS = { findings: [FINDING], summary: "One thing to fix.", recommendation: "Prepare a U1 copy." };
const SUMMARY = { source_has_creator_settings: true, kept_count: 0, compat_changed: [], mapped_to_u1: [], could_not_carry: [], warnings: [],
  recommendations_available: false, recommended_changes: [] };
const converted = (over: Record<string, unknown> = {}) => ({ schema_version: "convert/2", prepare_mode: "preserve", output_path: OUT, output_name: "model_SnapmakerU1.3mf",
  validated_ok: true, blocked: false, errors: [], settings_summary: SUMMARY, ...over });

function analysis(): ProjectMaterialsAnalysis {
  return { schema: "project-materials/1", supported: true, nozzle: "0.4", catalog: { available: true, source: null, fingerprint: "x" },
    provider: { kind: "spoolman", available: false, error_code: "unreachable" }, slots: [slot({ candidates: [], candidate_count: 0 })] } as ProjectMaterialsAnalysis;
}
const wrap = (ui: React.ReactElement) => <MemoryRouter><QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider></MemoryRouter>;
const plainPrepare = () => screen.getByRole("button", { name: /Prepare U1 copy/ });
let stop: () => void;

beforeEach(() => {
  for (const fn of Object.values(api.fns)) fn.mockReset();
  window.localStorage.clear();
  useProvider.setState({ kind: "spoolman", url: "127.0.0.1:7912", slotMap: {}, slotBase: 1, key: "" });
  useJob.setState({ record: null, verified: false });
  useSliced.setState({ path: null, name: null, revision: 0 } as never);
  useSession.setState({ file: null, convert: { status: "idle", data: null, error: null } as never, doctor: { status: "idle", data: null, error: null } as never });
  f("jobCheck").mockResolvedValue({ files: [] });
  f("doctor").mockResolvedValue({});
  f("compatibilityCheck").mockResolvedValue(WITH_FINDINGS);
  f("projectMaterials").mockResolvedValue(analysis());
  f("materialPresets").mockResolvedValue({ available: true, nozzle: "0.4", presets: [] });
  f("settingsReceipt").mockReturnValue(new Promise(() => {}));
  stop = trackJob();
  act(() => { useSession.getState().setFile(A); });
});
afterEach(() => { cleanup(); stop(); });

/** What a person does next: leave Compatibility for After slicing with the slicer's G-code. */
function goToAfterSlicing() {
  cleanup();
  act(() => { useSliced.setState({ path: GCODE, name: "model_PLA_1h.gcode", revision: 1 } as never); });
  render(wrap(<AfterSlicing />));
}
const receiptCall = () => f("settingsReceipt").mock.calls[f("settingsReceipt").mock.calls.length - 1];

describe("Prepare on the Compatibility route is part of the job", () => {
  it("ordinary Prepare: the prepared copy is on the job record and in the receipt after navigating away", async () => {
    f("convert").mockResolvedValue(converted());
    render(wrap(<Compatibility />));
    await screen.findByRole("button", { name: /Prepare U1 copy/ });
    fireEvent.click(plainPrepare());
    await screen.findByText(/model_SnapmakerU1\.3mf/);
    await waitFor(() => expect(useJob.getState().record?.prepared?.path).toBe(OUT));
    goToAfterSlicing();
    await waitFor(() => expect(receiptCall()).toEqual([A, OUT, GCODE]));
  });

  it("Project Materials preparation links the same way", async () => {
    f("convert").mockResolvedValue(converted());
    render(wrap(<Compatibility />));
    await screen.findByTestId("provider-down");
    fireEvent.click(screen.getByRole("button", { name: /Keep project's filament/ }));
    fireEvent.click(plainPrepare());
    await waitFor(() => expect(useJob.getState().record?.prepared?.path).toBe(OUT));
    goToAfterSlicing();
    await waitFor(() => expect(receiptCall()).toEqual([A, OUT, GCODE]));
  });
});

describe("only a validated, unblocked copy of the open project is published", () => {
  async function prepareWith(response: unknown) {
    f("convert").mockResolvedValue(response);
    render(wrap(<Compatibility />));
    await screen.findByRole("button", { name: /Prepare U1 copy/ });
    fireEvent.click(plainPrepare());
    await waitFor(() => expect(f("convert")).toHaveBeenCalled());
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  }
  const notLinked = async () => {
    expect(useJob.getState().record?.prepared ?? null).toBeNull();
    goToAfterSlicing();
    await waitFor(() => expect(f("settingsReceipt")).toHaveBeenCalled());
    expect(receiptCall()).toEqual([A, null, GCODE]);
  };

  it("a blocked result is not linked", async () => { await prepareWith(converted({ blocked: true })); await notLinked(); });
  it("a result that failed validation is not linked", async () => { await prepareWith(converted({ validated_ok: false })); await notLinked(); });
  it("a result that wrote no file is not linked", async () => { await prepareWith(converted({ output_path: "", output_name: "" })); await notLinked(); });
  it("a result whose output is the source itself is not linked", async () => { await prepareWith(converted({ output_path: A })); await notLinked(); });

  it("a response that arrives after the project changed is dropped", async () => {
    let release!: (v: unknown) => void;
    f("convert").mockReturnValue(new Promise((r) => { release = r; }));
    render(wrap(<Compatibility />));
    await screen.findByRole("button", { name: /Prepare U1 copy/ });
    fireEvent.click(plainPrepare());
    await waitFor(() => expect(f("convert")).toHaveBeenCalled());
    act(() => { useSession.getState().setFile(B); });
    await act(async () => { release(converted()); await Promise.resolve(); await Promise.resolve(); });
    expect(useSession.getState().convert.status).not.toBe("done");
    expect(useJob.getState().record?.prepared ?? null).toBeNull();
    expect(useJob.getState().record?.original.path).toBe(B);
  });

  it("a response for an earlier open of the same project (A, then B, then A again) is dropped", async () => {
    let release!: (v: unknown) => void;
    f("convert").mockReturnValue(new Promise((r) => { release = r; }));
    render(wrap(<Compatibility />));
    await screen.findByRole("button", { name: /Prepare U1 copy/ });
    fireEvent.click(plainPrepare());
    await waitFor(() => expect(f("convert")).toHaveBeenCalledTimes(1));
    act(() => { useSession.getState().setFile(B); });
    act(() => { useSession.getState().setFile(A); });
    await act(async () => { release(converted()); await Promise.resolve(); await Promise.resolve(); });
    expect(useSession.getState().convert.status).not.toBe("done");
    expect(useJob.getState().record?.prepared ?? null).toBeNull();
    goToAfterSlicing();
    await waitFor(() => expect(f("settingsReceipt")).toHaveBeenCalled());
    expect(receiptCall()).toEqual([A, null, GCODE]);
  });

  it("an older Prepare that resolves after a newer one for the same project does not replace it", async () => {
    let releaseOld!: (v: unknown) => void;
    f("convert").mockReturnValueOnce(new Promise((r) => { releaseOld = r; }));
    render(wrap(<Compatibility />));
    await screen.findByRole("button", { name: /Prepare U1 copy/ });
    fireEvent.click(plainPrepare());
    await waitFor(() => expect(f("convert")).toHaveBeenCalledTimes(1));
    f("convert").mockResolvedValueOnce(converted({ output_path: "C:/p/newer.3mf", output_name: "newer.3mf" }));
    const rev = useSession.getState().beginPrepare(A);
    expect(rev).not.toBeNull();
    useSession.getState().publishPrepared(rev, A, converted({ output_path: "C:/p/newer.3mf" }));
    await act(async () => { releaseOld(converted({ output_path: "C:/p/older.3mf" })); await Promise.resolve(); await Promise.resolve(); });
    expect(useSession.getState().convert.data?.output_path).toBe("C:/p/newer.3mf");
  });

  it("a dry-run preview never becomes the prepared copy", async () => {
    f("convert").mockResolvedValue(converted({ dry: true }));
    render(wrap(<Compatibility />));
    const review = await screen.findByRole("button", { name: /Review settings/ });
    fireEvent.click(review);
    await waitFor(() => expect(f("convert")).toHaveBeenCalledWith(A, undefined, "preserve", true));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(useSession.getState().convert.status).not.toBe("done");
    expect(useJob.getState().record?.prepared ?? null).toBeNull();
  });

  it("a new Prepare that fails does not leave the earlier copy linked as if it were current", async () => {
    f("convert").mockResolvedValueOnce(converted());
    render(wrap(<Compatibility />));
    await screen.findByRole("button", { name: /Prepare U1 copy/ });
    fireEvent.click(plainPrepare());
    await waitFor(() => expect(useSession.getState().convert.status).toBe("done"));
    f("convert").mockResolvedValueOnce(converted({ validated_ok: false, output_path: "C:/p/second.3mf" }));
    fireEvent.click(await screen.findByRole("button", { name: /Prepare another copy|Prepare U1 copy/ }));
    await waitFor(() => expect(f("convert")).toHaveBeenCalledTimes(2));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(useSession.getState().convert.status).not.toBe("done");
  });
});
