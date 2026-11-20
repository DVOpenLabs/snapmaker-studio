// @vitest-environment jsdom
import { useCreativeDraft } from "./draft";
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CreativeView from "./CreativeView";
import { inspectCreative, prepareCreative, fetchCreativeFormats } from "@/lib/creativeApi";
import { useSession } from "@/store/session";
import { NO_SETUP } from "@/lib/prepareSetup";
vi.mock("@/lib/creativeApi", async original => ({ ...await original<object>(), inspectCreative: vi.fn(), prepareCreative: vi.fn(), fetchCreativeFormats: vi.fn() }));
vi.mock("./CreativeReportView", () => ({ default: ({ report }: { report: { evidence: string } }) => <p>{report.evidence}</p> }));
vi.mock("./CreativePreparePanel", () => ({ default: () => <p>Prepared response</p> }));
vi.mock("@/components/ProjectMaterialsCard", () => ({ ProjectMaterialsCard: ({ onSelectionsChange, onPrepare, busy }: { onSelectionsChange: (v: unknown[]) => void; onPrepare: (v: unknown[]) => void; busy: boolean }) => <button disabled={busy} onClick={() => { const values = [{ slot: 0, colour: "#123456" }]; onSelectionsChange(values); onPrepare(values); }}>Prepare selected materials</button> }));
vi.mock("@/components/PrepareSetupSelector", () => ({ ConnectedPrepareSetupSelector: ({ onPrepareWithoutSetup }: { onPrepareWithoutSetup?: () => void }) => <button onClick={onPrepareWithoutSetup}>Prepare without setup</button> }));
const report = { origin: { status: "detected" }, evidence: "Synthetic inspection" };
beforeEach(() => { useCreativeDraft.getState().reset(); vi.clearAllMocks(); useSession.setState({ prepareSetup: NO_SETUP(100) }); vi.mocked(fetchCreativeFormats).mockResolvedValue({ formats: [], manual_only: [], note: "" }); vi.mocked(inspectCreative).mockResolvedValue(report as never); vi.mocked(prepareCreative).mockResolvedValue({ prepared: false, refusal: { kind: "synthetic" } } as never); });
afterEach(cleanup);
async function inspect() {
  render(<CreativeView />);
  fireEvent.change(screen.getByLabelText("Project file path"), { target: { value: "synthetic.3mf" } });
  fireEvent.click(screen.getByText("Inspect project"));
  await screen.findByText("Synthetic inspection");
}
it("forwards explicit material selections to Creative Prepare", async () => {
  await inspect(); fireEvent.click(screen.getByText("Prepare selected materials"));
  await waitFor(() => expect(prepareCreative).toHaveBeenCalledWith("synthetic.3mf", "auto", "", { materials: [{ slot: 0, colour: "#123456" }], topology: undefined }));
});
it("blocks a failed setup until the separate no-setup action", async () => {
  await inspect();
  act(() => useSession.setState({ prepareSetup: { status: "failed", token: 101, projectPath: "synthetic.3mf", label: "Synthetic host", reason: "unavailable" } }));
  expect(screen.getByText("Prepare a U1 copy", { selector: "button" }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByText("Prepare without setup"));
  await waitFor(() => expect(prepareCreative).toHaveBeenCalledTimes(1));
  expect(vi.mocked(prepareCreative).mock.calls[0][3]?.topology).toBeUndefined();
});
it("discards an inspection after the path changes", async () => {
  let finish!: (value: never) => void;
  vi.mocked(inspectCreative).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  render(<CreativeView />);
  fireEvent.change(screen.getByLabelText("Project file path"), { target: { value: "old.3mf" } });
  fireEvent.click(screen.getByText("Inspect project"));
  fireEvent.change(screen.getByLabelText("Project file path"), { target: { value: "new.3mf" } });
  await act(async () => finish(report as never));
  expect(screen.queryByText("Synthetic inspection")).toBeNull();
});
it("does not display a prepared response after material or path changes", async () => {
  let finish!: (value: never) => void;
  vi.mocked(prepareCreative).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  await inspect(); fireEvent.click(screen.getByText("Prepare a U1 copy", { selector: "button" }));
  fireEvent.change(screen.getByLabelText("Project file path"), { target: { value: "other.3mf" } });
  await act(async () => finish({ prepared: false } as never));
  expect(screen.queryByText("Prepared response")).toBeNull();
});
