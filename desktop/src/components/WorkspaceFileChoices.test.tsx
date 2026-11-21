// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import WorkspaceFileChoices from "./WorkspaceFileChoices";
import { useJob } from "@/store/job";
import { JOB_SCHEMA, linked, type JobRecord } from "@/lib/jobRecord";

// All names/paths below are synthetic, assembled at runtime.
const path = (name: string) => ["C:", "synthetic", name].join("/");
const record = (): JobRecord => ({ schema: JOB_SCHEMA, savedAt: "t", original: linked(path("source.3mf")), prepared: { ...linked(path("copy.3mf")), mode: "preserve" }, sliced: linked(path("slice.gcode")) });
beforeEach(() => useJob.setState({ record: null, verified: false }));
afterEach(cleanup);
it("offers no paths from an unchecked saved job", () => {
  useJob.setState({ record: record(), verified: false });
  render(<WorkspaceFileChoices extensions={["3mf"]} onChoose={vi.fn()} />);
  expect(screen.queryAllByRole("button")).toHaveLength(0);
  expect(screen.getByRole("status").textContent).toContain("not been reopened or checked");
});
it("requires an explicit click and filters compatible roles", () => {
  useJob.setState({ record: record(), verified: true }); const choose = vi.fn();
  render(<WorkspaceFileChoices extensions={["gcode"]} onChoose={choose} />);
  expect(choose).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "Project: source.3mf" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Sliced output: slice.gcode" }));
  expect(choose).toHaveBeenCalledWith(path("slice.gcode"));
});
it("updates offered files on project switch and forget", () => {
  useJob.setState({ record: record(), verified: true });
  const view = render(<WorkspaceFileChoices extensions={["3mf"]} onChoose={vi.fn()} />);
  useJob.setState({ record: { ...record(), original: linked(path("other.3mf")), prepared: null, sliced: null } });
  view.rerender(<WorkspaceFileChoices extensions={["3mf"]} onChoose={vi.fn()} />);
  expect(screen.queryByRole("button", { name: "Prepared copy: copy.3mf" })).toBeNull();
  expect(screen.getByRole("button", { name: "Project: other.3mf" })).toBeTruthy();
  useJob.setState({ record: null }); view.rerender(<WorkspaceFileChoices extensions={["3mf"]} onChoose={vi.fn()} />);
  expect(screen.queryAllByRole("button")).toHaveLength(0);
});
it("does not use incompatible artifacts or permit a disabled handoff", () => {
  useJob.setState({ record: record(), verified: true }); const choose = vi.fn();
  render(<WorkspaceFileChoices extensions={["3MF"]} disabled onChoose={choose} />);
  fireEvent.click(screen.getByRole("button", { name: "Project: source.3mf" })); expect(choose).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "Sliced output: slice.gcode" })).toBeNull();
});
