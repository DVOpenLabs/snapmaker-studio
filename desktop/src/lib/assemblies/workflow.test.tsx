// @vitest-environment jsdom
import { useAssemblyDraft } from "./draft";
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { projectMaterialsInventory } from "@/api";
import AssembliesView from "./AssembliesView";
import { evaluateAssembly, getAssembly, importAssemblyFile, listAssemblies, saveAssembly } from "./api";
vi.mock("./api", async original => ({ ...await original<object>(), evaluateAssembly: vi.fn(), getAssembly: vi.fn(), importAssemblyFile: vi.fn(), listAssemblies: vi.fn(), saveAssembly: vi.fn() }));
vi.mock("@/api", () => ({ library: vi.fn(), projectMaterialsInventory: vi.fn() }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("./AssemblyReportView", () => ({ default: ({ report }: { report: { name: string } }) => <div data-testid="report">{report.name}</div> }));
const real = { name: "Real saved assembly", bindings: { road: { provider_instance_id: "sample", provider_spool_id: "road-1" } }, tiles: [{ tile_id: "one", name: "One", roles: { road: "slot:0" }, usage: { "slot:0": 3 } }] };
beforeEach(() => { useAssemblyDraft.getState().reset(); vi.clearAllMocks(); vi.mocked(listAssemblies).mockResolvedValue({ assemblies: [{ id: 1, name: "Saved real", tiles: 1, revision: 1, updated_at: "" }] }); });
afterEach(cleanup);
it("does not publish an old evaluation after editing the document", async () => {
  let finish!: (value: never) => void;
  vi.mocked(evaluateAssembly).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  render(<AssembliesView />);
  fireEvent.click(screen.getByText("Load sample assembly"));
  fireEvent.click(screen.getByText("Check spools"));
  fireEvent.change(screen.getByLabelText("Assembly name"), { target: { value: "Changed" } });
  await act(async () => finish({ report: { name: "Old evaluation" } } as never));
  expect(screen.queryByTestId("report")).toBeNull();
});
it("does not show a stale error or apply an old open result after edits", async () => {
  let finish!: (value: never) => void;
  vi.mocked(getAssembly).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  render(<AssembliesView />);
  await screen.findByText("Saved real (1 tiles)");
  fireEvent.change(screen.getByLabelText("Saved assemblies"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Assembly name"), { target: { value: "Current edit" } });
  await act(async () => finish({ id: 1, revision: 1, assembly: real } as never));
  expect((screen.getByLabelText("Assembly name") as HTMLInputElement).value).toBe("Current edit");
});
it("clears sample observations when opening a saved assembly", async () => {
  vi.mocked(getAssembly).mockResolvedValue({ id: 1, revision: 1, assembly: real });
  render(<AssembliesView />);
  fireEvent.click(screen.getByText("Load sample assembly"));
  await screen.findByText("Saved real (1 tiles)");
  fireEvent.change(screen.getByLabelText("Saved assemblies"), { target: { value: "1" } });
  await waitFor(() => expect((screen.getByLabelText("Assembly name") as HTMLInputElement).value).toBe("Real saved assembly"));
  expect((screen.getByLabelText("road remaining grams") as HTMLInputElement).value).toBe("");
});
it("does not mix real imports with invented sample tiles", async () => {
  render(<AssembliesView />);
  fireEvent.click(screen.getByText("Load sample assembly"));
  // The path field and import/inventory buttons are disabled in sample mode, so no real file can be mixed in.
  expect((screen.getByLabelText("Import file path") as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByText("Import file") as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByText("Read inventory") as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByText("Import file"));
  expect(importAssemblyFile).not.toHaveBeenCalled();
});
it("imports a file, saves and reopens the actual imported document", async () => {
  vi.mocked(importAssemblyFile).mockResolvedValue({ assembly: real, file_name: "synthetic.3mf", sha256: "a".repeat(64), notes: [] });
  vi.mocked(saveAssembly).mockResolvedValue({ id: 2, revision: 1, assembly: real });
  render(<AssembliesView />);
  fireEvent.change(screen.getByLabelText("Import file path"), { target: { value: "synthetic.3mf" } });
  fireEvent.click(screen.getByText("Import file"));
  await screen.findByLabelText("Tile 1 name");
  vi.mocked(listAssemblies).mockResolvedValue({ assemblies: [{id:2,name:"Saved import",tiles:1,revision:1,updated_at:""}] });
  vi.mocked(getAssembly).mockResolvedValue({id:2,revision:1,assembly:real});
  fireEvent.click(screen.getByText("Save assembly"));
  await waitFor(() => expect(saveAssembly).toHaveBeenCalledWith(expect.objectContaining({ tiles: expect.arrayContaining([expect.objectContaining({ tile_id: "one", usage: { "slot:0": 3 } })]) }), undefined, undefined));
  await screen.findByText("Saved import (1 tiles)");
  fireEvent.click(screen.getByText("New assembly"));
  expect(screen.queryByLabelText("Tile 1 name")).toBeNull();
  fireEvent.change(screen.getByLabelText("Saved assemblies"),{target:{value:"2"}});
  await waitFor(()=>expect((screen.getByLabelText("Tile 1 name") as HTMLInputElement).value).toBe("One"));
  expect((screen.getByLabelText("road remaining grams") as HTMLInputElement).value).toBe("");
});


async function imported(){
  vi.mocked(importAssemblyFile).mockResolvedValue({assembly:real,file_name:"synthetic.stl",sha256:"a".repeat(64),notes:[]});
  render(<AssembliesView/>);fireEvent.change(screen.getByLabelText("Import file path"),{target:{value:"synthetic.stl"}});fireEvent.click(screen.getByText("Import file"));await screen.findByLabelText("Tile 1 name");
  fireEvent.change(screen.getByLabelText("Provider address"),{target:{value:"http://127.0.0.1:8123"}});fireEvent.change(screen.getByLabelText("Provider instance ID"),{target:{value:"synthetic"}});
}
it("keeps the editor intact for an unsupported inventory response without entries",async()=>{
  vi.mocked(projectMaterialsInventory).mockResolvedValue({supported:false,reason:"This file has no project settings"} as never);
  await imported();fireEvent.click(screen.getByText("Read inventory"));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent",expect.stringContaining("no project settings"));
  expect((screen.getByLabelText("Tile 1 name") as HTMLInputElement).value).toBe("One");
});
it("reports provider unavailability without calling it a successful inventory read",async()=>{
  vi.mocked(projectMaterialsInventory).mockResolvedValue({supported:true,entries:[],provider:{available:false,error_code:"unreachable"}} as never);
  await imported();fireEvent.click(screen.getByText("Read inventory"));expect(await screen.findByRole("alert")).toHaveProperty("textContent",expect.stringContaining("provider is unavailable"));
});
it("requires typing a current measurement before historical inventory can be dated",async()=>{
  vi.mocked(projectMaterialsInventory).mockResolvedValue({supported:true,entries:[{spool_id:1,label:"Synthetic",remaining_g:25}],provider:{available:true}} as never);
  await imported();fireEvent.click(screen.getByText("Read inventory"));
  fireEvent.change(await screen.findByLabelText("road inventory spool"),{target:{value:"0"}});
  const record=screen.getByText("Record my current measurement (5 min)");expect(record.hasAttribute("disabled")).toBe(true);
  fireEvent.change(screen.getByLabelText("road remaining grams"),{target:{value:"24"}});expect(record.hasAttribute("disabled")).toBe(false);
  fireEvent.click(record);expect(record.hasAttribute("disabled")).toBe(true);
});
it("scale edits clear both usage and all dated spool readings",async()=>{
  await imported();fireEvent.change(screen.getByLabelText("road remaining grams"),{target:{value:"25"}});fireEvent.click(screen.getByText("Record my current measurement (5 min)"));
  fireEvent.change(screen.getByLabelText("Tile 1 scale"),{target:{value:"120"}});
  expect((screen.getByLabelText("road remaining grams") as HTMLInputElement).value).toBe("");
  expect((screen.getByLabelText("Tile 1 slot:0 grams") as HTMLInputElement).value).toBe("");
});


it("refuses a non-array inventory reply without replacing the assembly",async()=>{
  vi.mocked(projectMaterialsInventory).mockResolvedValue({supported:true,entries:{},provider:{available:true}} as never);
  await imported();fireEvent.click(screen.getByText("Read inventory"));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent",expect.stringContaining("readable spool list"));
  expect((screen.getByLabelText("Tile 1 name") as HTMLInputElement).value).toBe("One");
});
