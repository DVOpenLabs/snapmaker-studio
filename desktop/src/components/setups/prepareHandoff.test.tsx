// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mock = vi.hoisted(() => ({ evaluate: vi.fn() }));
vi.mock("@/lib/setupsApi", async original => ({ ...await original<typeof import("@/lib/setupsApi")>(), evaluateSetup: mock.evaluate }));
vi.mock("@/api", async original => ({ ...await original<typeof import("@/api")>(), doctor: vi.fn(async () => ({})) }));
import SetupsView from "./SetupsView";
import { SAMPLE_REPORT } from "./sampleReport";
import { ConnectedPrepareSetupSelector } from "@/components/PrepareSetupSelector";
import { useSession } from "@/store/session";
import { useJob } from "@/store/job";
import { linked, JOB_SCHEMA } from "@/lib/jobRecord";
import { readSetupDraft, forgetSetupDraft } from "@/lib/setupDraft";
const project = "synthetic-project.3mf";
const topology = { schema_version: "topology/1", complete: true, heads: [{ id: "h0", index: 0 }], slots: [{ id: "s0", index: 0 }], units: [], bindings: [{ slot_id: "s0", target: "h0" }], evidence: [] };
const answer = { topology, read: { status: "ok" }, report: { ...SAMPLE_REPORT, entries: [], legacy_limitation: { applies: false, reasons: [], text: null } } };
beforeEach(() => { vi.clearAllMocks(); forgetSetupDraft(project); useSession.getState().reset(); useJob.setState({ verified: true, record: { schema: JOB_SCHEMA, savedAt: "t", original: linked(project), prepared: null, sliced: null } }); mock.evaluate.mockResolvedValue(answer); });
afterEach(cleanup);
async function mount() {
  render(<MemoryRouter initialEntries={["/setups"]}><Routes><Route path="/setups" element={<SetupsView />} /><Route path="/this-print" element={<ConnectedPrepareSetupSelector projectPath={project} />} /></Routes></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("Host address"), { target: { value: "synthetic.local" } });
  fireEvent.change(screen.getByLabelText("Port"), { target: { value: "9411" } });
  fireEvent.change(screen.getByLabelText("OctoPrint API key"), { target: { value: "synthetic-key-never-transferred" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Read setup" })));
}
it("transfers draft inputs only, pauses Prepare and requires a fresh read without the old key", async () => {
  await mount(); expect(mock.evaluate).toHaveBeenCalledTimes(1);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Continue in Prepare" })));
  expect((screen.getByLabelText("Setup host address") as HTMLInputElement).value).toBe("synthetic.local");
  expect((screen.getByLabelText("Setup port") as HTMLInputElement).value).toBe("9411");
  expect((screen.getByLabelText("Setup OctoPrint API key") as HTMLInputElement).value).toBe("");
  expect(useSession.getState().prepareSetup.status).toBe("unknown"); expect(mock.evaluate).toHaveBeenCalledTimes(1);
  await act(async () => fireEvent.click(screen.getByTestId("setup-read")));
  expect(mock.evaluate).toHaveBeenCalledTimes(2); expect(mock.evaluate.mock.calls[1][0]).not.toHaveProperty("api_key");
  expect(useSession.getState().prepareSetup.status).toBe("ready");
});
it("does not offer an unchecked saved job", async () => {
  await mount(); await act(async () => useJob.setState({ verified: false }));
  expect(screen.getByRole("button", { name: "Continue in Prepare" }).hasAttribute("disabled")).toBe(true);
  expect(readSetupDraft(project)).toBeUndefined();
});
it("carries accessory configuration but never promotes its old report into a selection", async () => {
  await mount();
  fireEvent.change(screen.getByLabelText("Accessory adapter"), { target: { value: "bmcu" } });
  fireEvent.change(screen.getByLabelText("Accessory snapshot"), { target: { value: "BMCU_PRINT_BEGIN SCHEMA=1" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Read setup" })));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Continue in Prepare" })));
  expect((screen.getByLabelText("Accessory adapter") as HTMLSelectElement).value).toBe("bmcu");
  expect(useSession.getState().prepareSetup.status).toBe("unknown");
  expect(readSetupDraft(project)?.accessory.snapshot).toBe("BMCU_PRINT_BEGIN SCHEMA=1");
});

it("a fresh-read failure keeps the transferred setup paused rather than falling back to stock", async () => {
  await mount(); await act(async () => fireEvent.click(screen.getByRole("button", { name: "Continue in Prepare" })));
  mock.evaluate.mockRejectedValueOnce(new Error("Synthetic fresh read refused"));
  await act(async () => fireEvent.click(screen.getByTestId("setup-read")));
  expect(useSession.getState().prepareSetup.status).toBe("failed");
  expect(screen.getByTestId("setup-paused")).toBeTruthy();
  expect(useSession.getState().convert.status).toBe("idle");
});
