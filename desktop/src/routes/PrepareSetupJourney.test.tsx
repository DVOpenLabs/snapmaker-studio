// @vitest-environment jsdom
// Route-level journey for "Prepare with a printer setup": real DOM events on the real Cockpit and selector, the real
// session store and usePrepare. Mocked: the local service (convert, doctor ...), the setups read, and heavy panels.
// Fixture/mock-service level only: it proves the UI's behaviour, not what the engine writes (see docs/internal/screens/prepare-setup).
import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 1, token: "t" }) }));
vi.mock("@/api", async (orig) => ({
  ...(await orig<typeof import("@/api")>()),
  doctor: vi.fn(), convert: vi.fn(), diff: vi.fn(), detectOrca: vi.fn(), openInOrca: vi.fn(), openModelDialog: vi.fn(), compatibilityCheck: vi.fn(), paintedPreview: vi.fn(),
}));
vi.mock("@/lib/setupsApi", async (orig) => ({ ...(await orig<typeof import("@/lib/setupsApi")>()), evaluateSetup: vi.fn() }));
vi.mock("@/components/PlacementCard", () => ({
  usePlacement: () => ({ check: null, failed: false, fix: null, fixing: false, runFix: vi.fn() }),
  PlacementView: () => <div data-testid="placement-view" />,
}));
vi.mock("@/components/PreflightCard", () => ({ PreflightCard: () => <div /> }));
vi.mock("@/components/ColorPlanCard", () => ({ ColorPlanCard: () => <div /> }));
vi.mock("@/components/FidelityCard", () => ({ FidelityCard: () => null }));
vi.mock("@/components/FixLedgerCard", () => ({ FixLedgerCard: () => null }));
vi.mock("@/components/JobWorkspaceCard", () => ({ JobWorkspaceCard: () => <div /> }));
vi.mock("@/components/job/ModelPane", () => ({ ModelPane: () => <div /> }));
vi.mock("@/components/job/SliceCompare", () => ({ SliceCompare: () => <div /> }));
vi.mock("@/components/ProjectMaterialsCard", async (orig) => ({
  ...(await orig<typeof import("@/components/ProjectMaterialsCard")>()),
  ProjectMaterialsCard: () => <div data-testid="materials" />,
}));

import * as api from "@/api";
import * as setups from "@/lib/setupsApi";
import Cockpit from "@/routes/Cockpit";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";

const A = { path: "C:\\work\\a.3mf", name: "a.3mf", ext: "3mf" };
const B = { path: "C:\\work\\b.3mf", name: "b.3mf", ext: "3mf" };
const convert = vi.mocked(api.convert);
const evaluate = vi.mocked(setups.evaluateSetup);

const deferred = <T,>() => {
  let resolve!: (v: T) => void; let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};
/** A synthetic topology with `heads` physical heads and `slots` logical slots (one lane per slot, all bound). */
const topo = (heads: number, slots: number) => ({
  schema_version: "topology/1", snapshot_id: "snap-synthetic", received_at: "2026-01-01T12:00:00Z", observed_at: null, mapping_revision: null,
  complete: true, evidence: [], diagnostics: [],
  heads: Array.from({ length: heads }, (_, i) => ({ id: `head:${i}`, index: i, nozzle_mm: 0.4, evidence: [] })),
  slots: Array.from({ length: slots }, (_, i) => ({ id: `slot:${i}`, index: i, binding: null, nozzle_mm: null })),
  units: [{ id: "unit:0", kind: "feeder", lanes: Array.from({ length: slots }, (_, i) => ({ id: `lane:${i}`, reachable_heads: [`head:${i % heads}`] })) }],
  bindings: Array.from({ length: slots }, (_, i) => ({ slot_id: `slot:${i}`, target: `lane:${i}` })),
});
const evalOk = (heads: number, slots: number) => ({ report: {}, read: {}, topology: topo(heads, slots) }) as any;
const copyOf = (p: { path: string }, setup?: object, over: object = {}) => {
  const out = p.path.replace(".3mf", "_U1.3mf");
  return { blocked: false, validated_ok: true, output_path: out, output_name: out.split("\\").pop(), prepare_mode: "preserve",
    settings_summary: { warnings: [], ...(setup ? { setup } : {}) }, ...over } as any;
};
const REFUSED = {
  blocked: true, validated_ok: false, output_path: "", output_name: "", prepare_mode: "preserve",
  errors: ["The printer setup cannot be used: the printer setup does not list every physical head. Nothing was prepared."],
  settings_summary: { warnings: [], setup: { state: "invalid", reasons: ["the printer setup does not list every physical head"], stock_alternative: "Prepare without a printer setup." } },
} as any;

const settle = () => act(async () => { for (let i = 0; i < 4; i++) await Promise.resolve(); });
const open = (file: typeof A) => act(() => { useSession.getState().setFile(file.path); });
const tab = (name: string) => fireEvent.click(screen.getByRole("tab", { name }));
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: string | RegExp) => fireEvent.click(screen.getByRole("button", { name }));
const status = () => screen.getByTestId("setup-status");
const lastCall = () => convert.mock.calls[convert.mock.calls.length - 1];
const sentTopology = () => lastCall()?.[5];

function readHost(host: string, port = "7125") {
  type("Setup host address", host); type("Setup port", port);
  click("Read setup");
}
async function openSettings(file = A) {
  render(<MemoryRouter><Cockpit /></MemoryRouter>);
  await open(file); await settle();
  tab("Copy settings");
}

beforeEach(() => {
  vi.clearAllMocks();
  convert.mockReset(); evaluate.mockReset();
  vi.mocked(api.doctor).mockResolvedValue({ verdict: "READY", prepare_blocked: false } as any);
  vi.mocked(api.diff).mockResolvedValue({} as any);
  vi.mocked(api.compatibilityCheck).mockResolvedValue({ findings: [] } as any);
  vi.mocked(api.detectOrca).mockResolvedValue("C:\\Orca\\orca.exe");
  useSession.getState().reset();
  useSliced.setState({ path: null, name: null });
});
afterEach(cleanup);

describe("Prepare with a printer setup: the journey", () => {
  it("type host, read, review, create: the topology shown is the topology sent, and the engine's own report decides the outcome", async () => {
    const d = deferred<any>();
    evaluate.mockReturnValue(d.promise);
    await openSettings();
    expect(status().getAttribute("data-state")).toBe("none");
    expect((screen.getByRole("button", { name: "Read setup" }) as HTMLButtonElement).disabled).toBe(true);   // no host typed yet
    readHost("u1-demo.local");
    expect(status().getAttribute("data-state")).toBe("reading");
    await act(async () => { d.resolve(evalOk(4, 8)); await Promise.resolve(); }); await settle();
    expect(status().getAttribute("data-state")).toBe("ready");
    expect(status().textContent).toContain("4 toolheads, 8 logical slots");
    expect(evaluate).toHaveBeenCalledWith({ host: "u1-demo.local", port: 7125 });

    convert.mockResolvedValue(copyOf(A, { state: "valid", heads: 4, slots: 8, unbound: [] }));
    click("Review settings"); await settle();
    expect(convert).toHaveBeenLastCalledWith(A.path, undefined, "preserve", true, undefined, expect.objectContaining({ schema_version: "topology/1" }));
    expect(sentTopology()!.slots).toHaveLength(8);
    expect(screen.getByTestId("setup-outcome").getAttribute("data-state")).toBe("used");
    expect(screen.getByTestId("setup-outcome").textContent).toContain("4 toolheads, 8 logical slots");

    click("Create U1 copy"); await settle();
    expect(convert).toHaveBeenLastCalledWith(A.path, undefined, expect.any(String), false, undefined, expect.objectContaining({ schema_version: "topology/1" }));
    expect(screen.getByTestId("copy-name").textContent).toBe("a_U1.3mf");
  });

  it("a chosen setup is not proof of use: no engine report reads as unknown, never as success", async () => {
    evaluate.mockResolvedValue(evalOk(4, 4));
    await openSettings();
    readHost("u1-demo.local"); await settle();
    convert.mockResolvedValue(copyOf(A));                                     // the engine said nothing about the setup
    click("Review settings"); await settle();
    const outcome = screen.getByTestId("setup-outcome");
    expect(outcome.getAttribute("data-state")).toBe("unknown");
    expect(outcome.textContent).toContain("cannot confirm");
    expect(outcome.textContent).not.toMatch(/engine reports it used/);
  });

  it("a valid setup the engine did not apply (no per-head settings) is said plainly, not shown as used", async () => {
    evaluate.mockResolvedValue(evalOk(4, 8));
    await openSettings();
    readHost("u1-demo.local"); await settle();
    convert.mockResolvedValue(copyOf(A, { state: "valid", applied: false, heads: 4, slots: 8, unbound: [] }));
    click("Review settings"); await settle();
    expect(screen.getByTestId("setup-outcome").getAttribute("data-state")).toBe("unused");
    expect(screen.getByTestId("setup-outcome").textContent).toContain("did not apply it");
  });

  it("an engine report for a different shape than the one sent is not taken as confirmation", async () => {
    evaluate.mockResolvedValue(evalOk(4, 8));
    await openSettings();
    readHost("u1-demo.local"); await settle();
    convert.mockResolvedValue(copyOf(A, { state: "valid", heads: 4, slots: 4, unbound: [] }));
    click("Review settings"); await settle();
    expect(screen.getByTestId("setup-outcome").getAttribute("data-state")).toBe("unknown");
  });

  it("a setup the engine refuses never looks successful: the copy view shows the refusal, its reasons and the stock alternative", async () => {
    evaluate.mockResolvedValue(evalOk(4, 8));
    await openSettings();
    readHost("u1-demo.local"); await settle();
    convert.mockResolvedValue(REFUSED);
    click("Create U1 copy"); await settle();
    expect(screen.queryByTestId("copy-result")).toBeNull();
    expect(screen.queryByText("U1 copy created")).toBeNull();
    expect(screen.getByTestId("blocked").textContent).toContain("does not list every physical head");
    expect(screen.getByTestId("blocked-setup").textContent).toContain("Prepare without a printer setup.");
    tab("Copy settings");
    expect(screen.getByTestId("setup-outcome").getAttribute("data-state")).toBe("blocked");
  });

  it("a failed read is a problem, pauses Prepare, sends nothing, and names the way out", async () => {
    evaluate.mockRejectedValue(new Error("Setup check failed: the host did not answer"));
    await openSettings();
    readHost("u1-demo.local"); await settle();
    expect(status().getAttribute("data-state")).toBe("failed");
    expect(screen.getByTestId("setup-paused")).toBeTruthy();
    click("Create U1 copy"); await settle();
    expect(convert).not.toHaveBeenCalled();
    expect(screen.getAllByText(/can't be used/).length).toBeGreaterThan(0);
  });

  it("an incomplete setup from the host is shown as unknown and nothing is sent", async () => {
    evaluate.mockResolvedValue({ report: {}, read: {}, topology: { ...topo(4, 4), complete: false } } as any);
    await openSettings();
    readHost("u1-demo.local"); await settle();
    expect(status().getAttribute("data-state")).toBe("unknown");
    click("Review settings"); await settle();
    expect(convert).not.toHaveBeenCalled();
  });

  it("clear, then Prepare: no setup is sent and a late answer from before the clear is not shown", async () => {
    evaluate.mockResolvedValue(evalOk(4, 8));
    await openSettings();
    readHost("u1-demo.local"); await settle();
    const late = deferred<any>();
    convert.mockReturnValueOnce(late.promise);
    click("Review settings"); await settle();
    click("Clear setup");
    expect(status().getAttribute("data-state")).toBe("none");
    await act(async () => { late.resolve(copyOf(A, { state: "valid", heads: 4, slots: 8, unbound: [] })); await Promise.resolve(); }); await settle();
    expect(screen.queryByTestId("setup-outcome")).toBeNull();
    convert.mockResolvedValue(copyOf(A));
    click("Create U1 copy"); await settle();
    expect(sentTopology()).toBeUndefined();
    expect(lastCall()).toHaveLength(5);                          // exactly the stock request: no topology argument at all
  });

  it("Prepare without a setup: drops the setup first and sends the stock request", async () => {
    evaluate.mockResolvedValue(evalOk(4, 8));
    await openSettings();
    readHost("u1-demo.local"); await settle();
    convert.mockResolvedValue(copyOf(A));
    click("Prepare without a setup"); await settle();
    expect(convert).toHaveBeenCalledTimes(1);
    expect(convert.mock.calls[0]).toHaveLength(5);
    expect(useSession.getState().prepareSetup.status).toBe("none");
  });

  it("out-of-order reads: the older answer arriving last does not replace the newer one", async () => {
    const first = deferred<any>(), second = deferred<any>();
    evaluate.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    await openSettings();
    readHost("old-host.local");
    await act(async () => { await Promise.resolve(); });
    // The controls lock while reading, so the newer read is started through the store, as a second request would be.
    await act(async () => { void useSession.getState().readPrepareSetup({ host: "new-host.local", port: "7125" }); await Promise.resolve(); });
    await act(async () => { second.resolve(evalOk(4, 8)); await Promise.resolve(); }); await settle();
    await act(async () => { first.resolve(evalOk(4, 4)); await Promise.resolve(); }); await settle();
    expect(status().getAttribute("data-state")).toBe("ready");
    expect(status().textContent).toContain("new-host.local");
    expect(status().textContent).toContain("8 logical slots");
    expect(status().textContent).not.toContain("old-host.local");
  });

  it("switching project while a read is in flight: the late answer belongs to nothing and B is prepared with no setup", async () => {
    const d = deferred<any>();
    evaluate.mockReturnValue(d.promise);
    await openSettings();
    readHost("u1-demo.local");
    await open(B); await settle();
    await act(async () => { d.resolve(evalOk(4, 8)); await Promise.resolve(); }); await settle();
    expect(useSession.getState().prepareSetup.status).toBe("none");
    tab("Copy settings");
    expect(status().getAttribute("data-state")).toBe("none");
    convert.mockResolvedValue(copyOf(B));
    click("Create U1 copy"); await settle();
    expect(lastCall()?.[0]).toBe(B.path);
    expect(sentTopology()).toBeUndefined();
  });

  it("the API key is not kept: the field is empty after the read and it is not in the stored selection", async () => {
    evaluate.mockResolvedValue(evalOk(4, 4));
    await openSettings();
    type("Setup OctoPrint API key", "synthetic-key-123");
    readHost("u1-demo.local"); await settle();
    expect((screen.getByLabelText("Setup OctoPrint API key") as HTMLInputElement).value).toBe("");
    expect(evaluate).toHaveBeenCalledWith(expect.objectContaining({ api_key: "synthetic-key-123" }));
    expect(JSON.stringify(useSession.getState().prepareSetup)).not.toContain("synthetic-key-123");
  });
});
