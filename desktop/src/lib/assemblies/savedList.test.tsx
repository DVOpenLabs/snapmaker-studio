// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import AssembliesView from "./AssembliesView";
import { useAssemblyDraft } from "./draft";
import { listAssemblies, getAssembly, saveAssembly, evaluateAssembly } from "./api";
vi.mock("./api", async original => ({ ...await original<object>(), listAssemblies: vi.fn(), getAssembly: vi.fn(), saveAssembly: vi.fn(), evaluateAssembly: vi.fn() }));
vi.mock("@/api", () => ({ library: vi.fn(), projectMaterialsInventory: vi.fn() }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
const rows = { assemblies: [{ id: 7, revision: 3, name: "Saved synthetic", tiles: 1, updated_at: "" }] };
beforeEach(() => { vi.resetAllMocks(); useAssemblyDraft.getState().reset(); vi.mocked(listAssemblies).mockResolvedValue(rows); });
afterEach(cleanup);
it("shows initial list failure and retries without losing edits or opening anything", async () => {
  vi.mocked(listAssemblies).mockRejectedValueOnce(new Error("synthetic-unavailable"));
  render(<AssembliesView />); fireEvent.change(screen.getByLabelText("Assembly name"), { target: { value: "Unsaved synthetic edit" } });
  expect(await screen.findByRole("alert")).toHaveProperty("textContent",expect.stringContaining("could not be refreshed"));
  fireEvent.click(screen.getByText("Refresh saved assemblies")); await screen.findByText("Saved synthetic (1 tiles)");
  expect(screen.queryByRole("alert")).toBeNull(); expect((screen.getByLabelText("Assembly name") as HTMLInputElement).value).toBe("Unsaved synthetic edit");
  expect(getAssembly).not.toHaveBeenCalled(); expect(saveAssembly).not.toHaveBeenCalled(); expect(evaluateAssembly).not.toHaveBeenCalled();
});
it("an old mount-time list cannot overwrite the newer post-save list", async () => {
  let resolve!: (value: typeof rows) => void; vi.mocked(listAssemblies).mockReturnValueOnce(new Promise(r=>{resolve=r;}));
  vi.mocked(saveAssembly).mockResolvedValue({ id: 7, revision: 3, assembly: {} });
  render(<AssembliesView />); fireEvent.click(screen.getByText("Load sample assembly")); fireEvent.click(screen.getByText("Save assembly"));
  await screen.findByText("Saved synthetic (1 tiles)");
  await act(async()=>resolve({ assemblies: [{ ...rows.assemblies[0], name: "Old synthetic list" }] }));
  expect(screen.getByText("Saved synthetic (1 tiles)")).toBeTruthy(); expect(screen.queryByText("Old synthetic list (1 tiles)")).toBeNull();
});
it("a successful save is still reported as saved when its subsequent list refresh fails", async () => {
  vi.mocked(listAssemblies).mockResolvedValueOnce(rows).mockRejectedValueOnce(new Error("Synthetic refresh refusal")).mockResolvedValueOnce(rows);
  vi.mocked(saveAssembly).mockResolvedValue({ id: 7, revision: 4, assembly: {} });
  render(<AssembliesView />); await screen.findByText("Saved synthetic (1 tiles)"); fireEvent.click(screen.getByText("Load sample assembly")); fireEvent.click(screen.getByText("Save assembly"));
  await screen.findByText("Saved. Spool observations are not saved with the assembly.");
  expect(await screen.findByRole("alert")).toHaveProperty("textContent",expect.stringContaining("Previously listed names may be out of date"));
  expect(useAssemblyDraft.getState().draft.current).toEqual({id:7,revision:4});
  fireEvent.click(screen.getByText("Refresh saved assemblies")); await waitFor(()=>expect(screen.queryByRole("alert")).toBeNull()); expect(saveAssembly).toHaveBeenCalledTimes(1);
});
it("late list failure after leaving does not replace a successor view's successful list", async () => {
  let reject!: (value: Error)=>void; vi.mocked(listAssemblies).mockReturnValueOnce(new Promise((_,no)=>{reject=no;}));
  const old=render(<AssembliesView />); old.unmount(); render(<AssembliesView />); await screen.findByText("Saved synthetic (1 tiles)");
  await act(async()=>reject(new Error("Synthetic old refusal"))); expect(screen.queryByRole("alert")).toBeNull();
});
