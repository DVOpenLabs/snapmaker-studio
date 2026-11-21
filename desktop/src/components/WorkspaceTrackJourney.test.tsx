// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
vi.mock("@/lib/extApi", () => ({ callExt: vi.fn(async (path: string) => {
  if (path === "/assemblies/list") return { assemblies: [] };
  if (path === "/creative/formats") return { formats: [] };
  throw new Error("synthetic action reached engine: " + path);
}) }));
import { callExt } from "@/lib/extApi";
import CreativeView from "@/components/creative/CreativeView";
import AssembliesView from "@/lib/assemblies/AssembliesView";
import variants from "@/routes/ext/variants.route";
import { useJob } from "@/store/job";
import { JOB_SCHEMA, linked, type JobRecord } from "@/lib/jobRecord";
const path = (name: string) => ["C:", "synthetic", name].join("/");
const record = (): JobRecord => ({ schema: JOB_SCHEMA, savedAt: "t", original: linked(path("source.3mf")), prepared: { ...linked(path("copy.3mf")), mode: "preserve" }, sliced: linked(path("slice.gcode")) });
beforeEach(() => { vi.clearAllMocks(); useJob.setState({ record: record(), verified: true }); });
afterEach(cleanup);
it("Creative picks a prepared copy from the job, but does not inspect until asked", async () => {
  render(<MemoryRouter><CreativeView /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Prepared copy: copy.3mf" }));
  expect((screen.getByLabelText("Project file path") as HTMLInputElement).value).toBe(path("copy.3mf"));
  expect(vi.mocked(callExt).mock.calls.some(c => c[0] === "/creative/inspect")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Inspect project" }));
  await screen.findByRole("alert");
  expect(vi.mocked(callExt).mock.calls.find(c => c[0] === "/creative/inspect")?.[1]).toMatchObject({ path: path("copy.3mf") });
});
it("Assemblies selects a linked slice, but imports only on explicit Import", async () => {
  render(<AssembliesView />);
  fireEvent.click(screen.getByRole("button", { name: "Sliced output: slice.gcode" }));
  expect((screen.getByLabelText("Import file path") as HTMLInputElement).value).toBe(path("slice.gcode"));
  expect(vi.mocked(callExt).mock.calls.some(c => c[0] === "/assemblies/import_file")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Import file" })); await screen.findByRole("alert");
  expect(vi.mocked(callExt).mock.calls.find(c => c[0] === "/assemblies/import_file")?.[1]).toEqual({ path: path("slice.gcode") });
});
it("Variants fills either side independently and compares only on request", async () => {
  render(<variants.Component />);
  fireEvent.click(within(screen.getByRole("region", { name: "Use a job file for output 1" })).getByRole("button", { name: "Prepared copy: copy.3mf" }));
  fireEvent.click(within(screen.getByRole("region", { name: "Use a job file for output 2" })).getByRole("button", { name: "Sliced output: slice.gcode" }));
  expect((screen.getByLabelText("Output 1 path") as HTMLInputElement).value).toBe(path("copy.3mf"));
  expect((screen.getByLabelText("Output 2 path") as HTMLInputElement).value).toBe(path("slice.gcode"));
  expect(callExt).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Compare outputs" })); await screen.findByRole("alert");
  expect(vi.mocked(callExt).mock.calls[0][1]).toEqual({ outputs: [{ path: path("copy.3mf") }, { path: path("slice.gcode") }] });
});
