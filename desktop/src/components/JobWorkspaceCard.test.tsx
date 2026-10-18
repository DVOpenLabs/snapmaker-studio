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

  it("forgetting the job removes it", () => {
    render(<JobWorkspaceCard />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Forget this job" })); });
    expect(useJob.getState().record).toBeNull();
  });
});
