// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import AssembliesView from "./AssembliesView";
import { useAssemblyDraft } from "./draft";
import { useJob } from "@/store/job";
import { evaluateAssembly, importAssemblyFile, listAssemblies, saveAssembly, getAssembly } from "./api";
vi.mock("./api", async original => ({ ...await original<object>(), evaluateAssembly: vi.fn(), importAssemblyFile: vi.fn(), listAssemblies: vi.fn(), saveAssembly: vi.fn(), getAssembly: vi.fn() }));
vi.mock("@/api", () => ({ library: vi.fn(), projectMaterialsInventory: vi.fn() }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("./AssemblyReportView", () => ({ default: () => <p>Synthetic report</p> }));
const document = { name: "Synthetic assembly", bindings: { base: { provider_instance_id: "synthetic", provider_spool_id: "one" } }, tiles: [{ tile_id: "one", name: "Synthetic tile", roles: { base: "slot:0" }, usage: { "slot:0": 3 } }] };
beforeEach(() => { vi.clearAllMocks(); useAssemblyDraft.getState().reset(); vi.mocked(listAssemblies).mockResolvedValue({ assemblies: [] }); vi.mocked(importAssemblyFile).mockResolvedValue({ assembly: document, file_name: "synthetic.3mf", sha256: "a".repeat(64), notes: [] }); });
afterEach(cleanup);
async function imported() { const view = render(<AssembliesView />); fireEvent.change(screen.getByLabelText("Import file path"), { target: { value: "synthetic.3mf" } }); fireEvent.click(screen.getByText("Import file")); await screen.findByLabelText("Tile 1 name"); return view; }
it("retains edited tiles and dated readings across navigation without renewing or auto-evaluating", async () => {
  const storage = vi.spyOn(Storage.prototype, "setItem");
  const view = await imported();
  fireEvent.change(screen.getByLabelText("Tile 1 name"), { target: { value: "Edited synthetic tile" } });
  fireEvent.change(screen.getByLabelText("base provider instance"), { target: { value: "synthetic" } });
  fireEvent.change(screen.getByLabelText("base spool ID"), { target: { value: "one" } });
  fireEvent.change(screen.getByLabelText("base remaining grams"), { target: { value: "24" } });
  fireEvent.click(screen.getByText("Record my current measurement (5 min)"));
  const reading = structuredClone(useAssemblyDraft.getState().draft.supply[0]);
  fireEvent.change(screen.getByLabelText("Provider key"), { target: { value: "synthetic-not-a-secret" } });
  view.unmount(); render(<AssembliesView />);
  expect((screen.getByLabelText("Tile 1 name") as HTMLInputElement).value).toBe("Edited synthetic tile");
  expect((screen.getByLabelText("base remaining grams") as HTMLInputElement).value).toBe("24");
  expect((screen.getByLabelText("Provider key") as HTMLInputElement).value).toBe("");
  expect(useAssemblyDraft.getState().draft.supply[0]).toEqual(reading);
  expect(evaluateAssembly).not.toHaveBeenCalled(); expect(saveAssembly).not.toHaveBeenCalled(); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  vi.mocked(evaluateAssembly).mockResolvedValue({ report: { name: "Synthetic" } } as never);
  fireEvent.click(screen.getByText("Check spools"));
  await waitFor(() => expect(evaluateAssembly).toHaveBeenCalledWith(expect.objectContaining({ tiles: [expect.objectContaining({ name: "Edited synthetic tile" })] }), [reading]));
  cleanup(); render(<AssembliesView />); expect(screen.queryByText("Synthetic report")).toBeNull();
});
it("retains the sample boundary and New assembly explicitly clears the draft", async () => {
  const view = render(<AssembliesView />); fireEvent.click(screen.getByText("Load sample assembly")); view.unmount(); render(<AssembliesView />);
  expect(screen.getByTestId("assembly-sample-disclosure").textContent).toContain("all figures are invented");
  // Sample mode clears any earlier real path and blocks file import and inventory reads until New assembly.
  expect((screen.getByLabelText("Import file path") as HTMLInputElement).disabled).toBe(true); expect((screen.getByLabelText("Import file path") as HTMLInputElement).value).toBe("");
  expect((screen.getByText("Import file") as HTMLButtonElement).disabled).toBe(true); expect((screen.getByText("Read inventory") as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByText("Import file")); expect(importAssemblyFile).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("New assembly")); expect(useAssemblyDraft.getState().draft).toMatchObject({ sampleMode: false, supply: [], current: null, filePath: "", document: { tiles: [], bindings: {} } });
});
it("sample mode: a verified job file offered by the picker cannot be adopted or imported", async () => {
  useJob.setState({ record: { original: { path: "C:\work\synthetic.3mf", name: "synthetic.3mf", fingerprint: null }, prepared: null, sliced: null } as never, verified: true } as never);
  render(<AssembliesView />);
  const choice = screen.getByText(/Project: synthetic\.3mf/) as HTMLButtonElement; expect(choice.disabled).toBe(false);
  fireEvent.click(screen.getByText("Load sample assembly"));
  expect((screen.getByText(/Project: synthetic\.3mf/) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByText(/Project: synthetic\.3mf/));
  expect((screen.getByLabelText("Import file path") as HTMLInputElement).value).toBe("");
  expect((screen.getByText("Import file") as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByText("Import file")); expect(importAssemblyFile).not.toHaveBeenCalled();
  useJob.setState({ record: null, verified: false } as never);
});
it("late import completion after navigation cannot overwrite the newer draft", async () => {
  let resolve!: (value: never) => void; vi.mocked(importAssemblyFile).mockReturnValueOnce(new Promise(r => { resolve=r; }));
  const view=render(<AssembliesView />); fireEvent.change(screen.getByLabelText("Import file path"), { target: { value: "old-synthetic.3mf" } }); fireEvent.click(screen.getByText("Import file")); view.unmount();
  render(<AssembliesView />); fireEvent.change(screen.getByLabelText("Assembly name"), { target: { value: "Newer edit" } });
  await act(async () => resolve({ assembly: document, notes: [] } as never));
  expect((screen.getByLabelText("Assembly name") as HTMLInputElement).value).toBe("Newer edit"); expect(screen.queryByLabelText("Tile 1 name")).toBeNull();
});
it("restores saved identity for revision-checked saves and opening clears old observations", async () => {
  vi.mocked(listAssemblies).mockResolvedValue({ assemblies: [{ id: 7, revision: 3, name: "Saved synthetic", tiles: 1, updated_at: "" }] });
  vi.mocked(getAssembly).mockResolvedValue({ id: 7, revision: 3, assembly: document });
  const view=await imported(); fireEvent.change(screen.getByLabelText("base remaining grams"), { target: { value: "22" } }); view.unmount(); render(<AssembliesView />);
  await screen.findByText("Saved synthetic (1 tiles)"); fireEvent.change(screen.getByLabelText("Saved assemblies"), { target: { value: "7" } });
  await waitFor(() => expect(useAssemblyDraft.getState().draft.current).toEqual({ id: 7, revision: 3 }));
  expect(useAssemblyDraft.getState().draft.supply).toEqual([]); cleanup(); render(<AssembliesView />);
  vi.mocked(saveAssembly).mockResolvedValue({ id: 7, revision: 4, assembly: document }); fireEvent.click(screen.getByText("Save assembly"));
  await waitFor(() => expect(saveAssembly).toHaveBeenCalledWith(expect.anything(), 7, 3));
});
