// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CreativeView from "./CreativeView";
import { useCreativeDraft } from "./draft";
import { inspectCreative, prepareCreative, fetchCreativeFormats } from "@/lib/creativeApi";
vi.mock("@/lib/creativeApi", async original => ({ ...await original<object>(), inspectCreative: vi.fn(), prepareCreative: vi.fn(), fetchCreativeFormats: vi.fn() }));
vi.mock("./CreativeReportView", () => ({ default: () => <p>Synthetic inspection</p> }));
vi.mock("./CreativePreparePanel", () => ({ default: () => null }));
vi.mock("@/components/ProjectMaterialsCard", () => ({ ProjectMaterialsCard: () => <p>Review materials explicitly</p> }));
vi.mock("@/components/PrepareSetupSelector", () => ({ ConnectedPrepareSetupSelector: () => null }));
const report = { origin: { status: "detected" } };
beforeEach(() => { vi.clearAllMocks(); useCreativeDraft.getState().reset(); vi.mocked(fetchCreativeFormats).mockResolvedValue({ formats: [], manual_only: [], note: "" }); vi.mocked(inspectCreative).mockResolvedValue(report as never); });
afterEach(cleanup);
it("restores source, format and output folder but requires a fresh explicit inspection", async () => {
  const storage=vi.spyOn(Storage.prototype,"setItem"); const view=render(<CreativeView />);
  fireEvent.change(screen.getByLabelText("Project file path"), { target: { value: "synthetic.3mf" } }); fireEvent.change(screen.getByLabelText("Project format"), { target: { value: "kromacut" } });
  fireEvent.click(screen.getByText("Inspect project")); await screen.findByText("Synthetic inspection");
  fireEvent.change(screen.getByLabelText("Output folder (optional)"), { target: { value: "synthetic-output" } }); view.unmount(); render(<CreativeView />);
  expect((screen.getByLabelText("Project file path") as HTMLInputElement).value).toBe("synthetic.3mf"); expect((screen.getByLabelText("Project format") as HTMLSelectElement).value).toBe("kromacut");
  expect(screen.queryByText("Synthetic inspection")).toBeNull(); expect(prepareCreative).not.toHaveBeenCalled(); expect(inspectCreative).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByText("Inspect project")); await screen.findByText("Synthetic inspection");
  expect((screen.getByLabelText("Output folder (optional)") as HTMLInputElement).value).toBe("synthetic-output"); expect(inspectCreative).toHaveBeenLastCalledWith("synthetic.3mf","kromacut");
  expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
});
it("clear explicitly forgets draft and late inspection does not revive it", async () => {
  let resolve!: (value: never) => void; vi.mocked(inspectCreative).mockReturnValueOnce(new Promise(r=>{resolve=r;}));
  render(<CreativeView />); fireEvent.change(screen.getByLabelText("Project file path"), { target: { value: "synthetic.3mf" } }); fireEvent.click(screen.getByText("Inspect project")); fireEvent.click(screen.getByText("Clear creative inputs"));
  await act(async()=>resolve(report as never)); expect(screen.queryByText("Synthetic inspection")).toBeNull(); expect(useCreativeDraft.getState().inputs).toEqual({ path:"",format:"auto",outDir:"" }); expect(prepareCreative).not.toHaveBeenCalled();
});
it("late completion after leaving cannot replace a newer source or auto-prepare", async () => {
  let resolve!: (value: never) => void; vi.mocked(inspectCreative).mockReturnValueOnce(new Promise(r=>{resolve=r;}));
  const view=render(<CreativeView />); fireEvent.change(screen.getByLabelText("Project file path"), { target: { value: "old-synthetic.3mf" } }); fireEvent.click(screen.getByText("Inspect project")); view.unmount();
  render(<CreativeView />); fireEvent.change(screen.getByLabelText("Project file path"), { target: { value: "new-synthetic.3mf" } }); await act(async()=>resolve(report as never));
  expect((screen.getByLabelText("Project file path") as HTMLInputElement).value).toBe("new-synthetic.3mf"); expect(screen.queryByText("Synthetic inspection")).toBeNull(); expect(prepareCreative).not.toHaveBeenCalled();
});
