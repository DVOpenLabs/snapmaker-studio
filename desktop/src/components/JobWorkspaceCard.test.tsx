// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4312, token: "test" }) }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("@/api", () => ({ jobCheck: vi.fn(), doctor: vi.fn().mockResolvedValue({}), convert: vi.fn(), diff: vi.fn() }));

import * as api from "@/api";
import { JobWorkspaceCard } from "@/components/JobWorkspaceCard";
import { useJob } from "@/store/job";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";
import type { JobRecord } from "@/lib/jobRecord";

const fp = (c: string, n: number) => ({ size_bytes: n, sha256: c.repeat(64) });
const RECORD: JobRecord = {
  schema: "job/1", savedAt: "2026-01-01T00:00:00.000Z",
  original: { path: "C:\\work\\A.3mf", name: "A.3mf", fingerprint: fp("a", 10) },
  prepared: { path: "C:\\work\\A_U1.3mf", name: "A_U1.3mf", fingerprint: fp("b", 20), mode: "preserve" },
  sliced: { path: "C:\\out\\A.gcode", name: "A.gcode", fingerprint: fp("c", 30) },
};

const report = (states: Record<string, string>) => {
  vi.mocked(api.jobCheck).mockResolvedValue({
    schema_version: "job-check/1",
    files: Object.entries(states).map(([role, status]) => ({ role, path: "x", status })) as any,
  });
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.doctor).mockResolvedValue({} as any);
  useJob.setState({ record: RECORD, phase: "idle", check: {}, error: null });
  useSession.setState({ file: null });
  useSliced.setState({ path: null, name: null });
});
afterEach(cleanup);

describe("the job card", () => {
  it("shows nothing when there is no saved job", () => {
    useJob.setState({ record: null });
    const { container } = render(<JobWorkspaceCard />);
    expect(container.innerHTML).toBe("");
  });

  it("offers a check, not a restore, before anything has been verified", () => {
    render(<JobWorkspaceCard />);
    expect(screen.getByText("Pick up your last job")).toBeTruthy();
    expect(screen.getByText("A.3mf")).toBeTruthy();
    expect(screen.getByText("A_U1.3mf")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Check these files" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Reopen|Nothing to reopen/ })).toBeNull();
    expect(useSession.getState().file).toBeNull();
  });

  it("checks, then reopens unchanged files without preparing or slicing anything", async () => {
    report({ original: "same", prepared: "same", sliced: "same" });
    render(<JobWorkspaceCard />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Check these files" })); });
    expect(screen.getAllByText("Unchanged since it was recorded")).toHaveLength(3);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Reopen project and sliced g-code" })); });
    expect(useSession.getState().file?.path).toBe("C:\\work\\A.3mf");
    expect(useSliced.getState().path).toBe("C:\\out\\A.gcode");
    expect(api.convert).not.toHaveBeenCalled();
  });

  it("a changed G-code is flagged and reopened only after it is named", async () => {
    report({ original: "same", prepared: "same", sliced: "changed" });
    render(<JobWorkspaceCard />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Check these files" })); });
    expect(screen.getByText("Changed since it was recorded")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reopen project" })).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("button", { name: "Reopen project and sliced g-code" })).toBeTruthy();
  });

  it("a missing file is explained and cannot be named", async () => {
    report({ original: "same", prepared: "missing", sliced: "missing" });
    render(<JobWorkspaceCard />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Check these files" })); });
    expect(screen.getAllByText("Not found where it was")).toHaveLength(2);
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("nothing to reopen is said plainly and the button is disabled", async () => {
    report({ original: "missing", prepared: "missing", sliced: "missing" });
    render(<JobWorkspaceCard />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Check these files" })); });
    expect((screen.getByRole("button", { name: "Nothing to reopen" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("with the job's own project open it shows the linked files and offers no restore", () => {
    useSession.setState({ file: { path: "C:\\work\\A.3mf", name: "A.3mf", ext: "3mf" } });
    render(<JobWorkspaceCard />);
    expect(screen.getByText("This job")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Check these files" })).toBeNull();
  });

  it("with a different project open it stays out of the way", () => {
    useSession.setState({ file: { path: "C:\\work\\B.3mf", name: "B.3mf", ext: "3mf" } });
    const { container } = render(<JobWorkspaceCard />);
    expect(container.innerHTML).toBe("");
  });

  it("says which files will reopen, by name, and that nothing is prepared, sliced or sent", async () => {
    report({ original: "same", prepared: "same", sliced: "same" });
    render(<JobWorkspaceCard />);
    expect(screen.getByText(/Check first: Studio then lists exactly which files it will reopen/)).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Check these files" })); });
    const note = screen.getByText(/Will reopen:/);
    expect(note.textContent).toContain("A.3mf, A.gcode");
    expect(note.textContent?.split("Left out:")[0]).not.toContain("A_U1.3mf");
    expect(note.textContent).toMatch(/does not prepare, slice or send anything/);
  });

  it("explains why the prepared copy is listed but never reopened", () => {
    render(<JobWorkspaceCard />);
    expect(screen.getByText("Why isn’t the prepared copy reopened?")).toBeTruthy();
    expect(screen.getByText("preserve mode")).toBeTruthy();
  });

  it("keeps a long file name whole and readable, with its full path on hover", () => {
    const long = "a-very-long-project-name-with-many-parts-and-a-version-number-v12-final-final.3mf";
    useJob.setState({ record: { ...RECORD, original: { ...RECORD.original, name: long, path: `C:\\work\\${long}` } } });
    render(<JobWorkspaceCard />);
    const name = screen.getByText(long);
    expect(name.className).toContain("break-all");
    expect(name.getAttribute("title")).toBe(`C:\\work\\${long}`);
  });

  it("forgetting the job removes it", () => {
    render(<JobWorkspaceCard />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Forget this job" })); });
    expect(useJob.getState().record).toBeNull();
  });
});

describe("recorded, checked, reopened and left out", () => {
  const check = async (states: Record<string, string>) => {
    report(states);
    render(<JobWorkspaceCard />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Check these files" })); });
  };
  const reopen = async (name: RegExp) => {
    await act(async () => { fireEvent.click(screen.getByRole("button", { name })); });
  };

  it("before any check every hash is labelled as a recorded one and the file as not checked yet", () => {
    render(<JobWorkspaceCard />);
    expect(screen.getAllByText(/recorded/).length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText("Recorded earlier — not checked yet")).toHaveLength(3);
  });

  it("the check names what will be left out and why, before anything is reopened", async () => {
    await check({ original: "same", prepared: "same", sliced: "changed" });
    const note = screen.getByText(/Will reopen:/);
    expect(note.textContent).toContain("Left out:");
    expect(note.textContent).toContain("A.gcode (changed since it was recorded)");
    expect(note.textContent).toContain("A_U1.3mf (a saved job never reopens a prepared copy)");
  });

  it("after a default Reopen a changed G-code is shown as left out, its hash as the earlier record", async () => {
    await check({ original: "same", prepared: "same", sliced: "changed" });
    await reopen(/^Reopen project$/);
    expect(useSession.getState().file?.path).toBe("C:\\work\\A.3mf");
    expect(useSliced.getState().path).toBeNull();
    expect(screen.getByText("Reopened — unchanged since it was recorded")).toBeTruthy();
    const sliced = screen.getByText(/^Not reopened — changed since it was recorded\./);
    expect(sliced.textContent).toContain("The hash shown is the earlier record, not this file.");
    // The record is preserved as history: still the recorded identity, not rewritten to anything current.
    expect(useJob.getState().record?.sliced?.fingerprint?.sha256).toBe("c".repeat(64));
  });

  it("the prepared copy is never presented as reopened, whether or not it is intact", async () => {
    await check({ original: "same", prepared: "same", sliced: "same" });
    await reopen(/^Reopen project and sliced g-code$/);
    expect(screen.getByText(/^Not reopened — a saved job never reopens a prepared copy\./)).toBeTruthy();
    expect(screen.getAllByText("Reopened — unchanged since it was recorded")).toHaveLength(2);
  });

  it("a missing prepared copy is labelled as not found and its hash as a record only", async () => {
    await check({ original: "same", prepared: "missing", sliced: "same" });
    await reopen(/^Reopen project$/);   // the G-code came from the missing copy, so it is not offered unnamed
    expect(screen.getByText(/^Not reopened — not found where it was\. The hash shown is the earlier record/)).toBeTruthy();
  });

  it("a G-code that could not be read is labelled as such and was not reopened", async () => {
    await check({ original: "same", prepared: "same", sliced: "unreadable" });
    await reopen(/^Reopen project$/);
    expect(useSliced.getState().path).toBeNull();
    expect(screen.getByText(/^Not reopened — could not be read\./)).toBeTruthy();
  });

  it("naming a changed G-code reopens it and says its record now follows the file on disk", async () => {
    report({ original: "same", prepared: "same", sliced: "changed" });
    render(<JobWorkspaceCard />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Check these files" })); });
    fireEvent.click(screen.getByRole("checkbox"));
    await reopen(/^Reopen project and sliced g-code$/);
    expect(useSliced.getState().path).toBe("C:\\out\\A.gcode");
    expect(screen.getByText(/^Reopened — it had changed since it was recorded/)).toBeTruthy();
  });

  it("reopening a changed project anyway unlinks the earlier files and says so, with no stale hashes beside them", async () => {
    report({ original: "changed", prepared: "same", sliced: "same" });
    render(<JobWorkspaceCard />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Check these files" })); });
    fireEvent.click(screen.getByRole("checkbox"));
    await reopen(/^Reopen project$/);
    expect(useJob.getState().record?.prepared).toBeNull();
    expect(useJob.getState().record?.sliced).toBeNull();
    expect(screen.getByText(/Not linked to this project: A_U1\.3mf, A\.gcode\./)).toBeTruthy();
    expect(screen.queryByText("A.gcode", { selector: "span" })).toBeNull();
  });

  it("a note stops applying once the file it described is replaced", async () => {
    await check({ original: "same", prepared: "same", sliced: "changed" });
    await reopen(/^Reopen project$/);
    expect(screen.getByText(/^Not reopened — changed since it was recorded\./)).toBeTruthy();
    // A new G-code is linked: the old "left out" note must not describe it.
    act(() => { useJob.setState({ record: { ...RECORD, sliced: { path: "C:\\out\\B.gcode", name: "B.gcode", fingerprint: null } } }); });
    act(() => { useSliced.setState({ path: "C:\\out\\B.gcode", name: "B.gcode" }); });
    expect(screen.queryByText(/^Not reopened — changed since it was recorded\./)).toBeNull();
  });

  it("forgetting the job clears what the last restore said", async () => {
    await check({ original: "same", prepared: "same", sliced: "same" });
    await reopen(/^Reopen project and sliced g-code$/);
    expect(Object.keys(useJob.getState().outcome).length).toBeGreaterThan(0);
    act(() => { useJob.getState().forget(); });
    expect(useJob.getState().outcome).toEqual({});
  });
});
