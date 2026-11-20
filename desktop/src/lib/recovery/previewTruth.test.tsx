// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("./api", async original => ({ ...await original<typeof import("./api")>(), restoreCheckpoint: vi.fn(), saveCheckpoint: vi.fn() }));
vi.mock("./monitor/MonitoringPanel", () => ({ default: () => null }));
import { restoreCheckpoint, saveCheckpoint, type RestoreResult } from "./api";
import { __resetRecoverySubscriberForTests, refreshPreview } from "./subscriber";
import { RecoveryView } from "./RecoveryView";
import { useJob } from "@/store/job";
import { linked, JOB_SCHEMA, type JobRecord } from "@/lib/jobRecord";
const result = (revision = 1, name = "Saved project A"): RestoreResult => ({ missing_checkpoint: false, revision, workspace: { name }, observations: [], jobs: [], files: [], fresh_read_required: true });
const record = (name: string): JobRecord => ({ schema: JOB_SCHEMA, savedAt: "t", original: linked(name), prepared: null, sliced: null });
beforeEach(() => { vi.clearAllMocks(); __resetRecoverySubscriberForTests(); useJob.setState({ record: record("synthetic-a.3mf"), verified: true }); vi.mocked(restoreCheckpoint).mockResolvedValue(result()); });
afterEach(cleanup);
async function mountReady() { await refreshPreview(); render(<RecoveryView />); }
it("pauses checkpoint saves during refresh, labels the old preview historical and resumes only on success", async () => {
  await mountReady(); let resolve!: (value: RestoreResult) => void;
  vi.mocked(restoreCheckpoint).mockReturnValueOnce(new Promise(r => { resolve = r; }));
  fireEvent.click(screen.getByRole("button", { name: "Refresh restore preview" }));
  expect(screen.getByRole("button", { name: "Checkpoint this workspace" }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: "Save sample checkpoint" }).hasAttribute("disabled")).toBe(true);
  const earlier = screen.getByText("Earlier preview — not current").closest("details")!;
  expect(earlier.open).toBe(false); expect(earlier.textContent).toContain("Saved project A");
  await act(async () => resolve(result(2))); expect(screen.queryByText("Earlier preview — not current")).toBeNull();
  expect(screen.getByRole("button", { name: "Checkpoint this workspace" }).hasAttribute("disabled")).toBe(false);
});
it("a failed refresh cannot leave the old preview usable for saving", async () => {
  await mountReady(); vi.mocked(restoreCheckpoint).mockRejectedValueOnce(new Error("Synthetic read refused"));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Refresh restore preview" })));
  expect(screen.getByText(/The latest checkpoint read failed/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Checkpoint this workspace" }).hasAttribute("disabled")).toBe(true);
  expect(saveCheckpoint).not.toHaveBeenCalled();
});
it("distinguishes a saved checkpoint from an unsuccessful verification refresh", async () => {
  await mountReady(); vi.mocked(saveCheckpoint).mockResolvedValueOnce({ revision: 2, checkpointed_at: "t", file_count: 1 });
  vi.mocked(restoreCheckpoint).mockRejectedValueOnce(new Error("Synthetic refresh failed"));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Checkpoint this workspace" })));
  const notice = await screen.findByTestId("checkpoint-notice");
  expect(notice.textContent).toContain("saved for synthetic-a.3mf"); expect(notice.textContent).toContain("preview was not confirmed");
  expect(notice.textContent).not.toContain("NOT saved");
});
it("a project switch during save cannot mislabel the completed checkpoint as the new job", async () => {
  await mountReady(); let resolve!: (value: { revision: number; checkpointed_at: string; file_count: number }) => void;
  vi.mocked(saveCheckpoint).mockReturnValueOnce(new Promise(r => { resolve = r; }));
  fireEvent.click(screen.getByRole("button", { name: "Checkpoint this workspace" }));
  await act(async () => useJob.setState({ record: record("synthetic-b.3mf"), verified: true }));
  vi.mocked(restoreCheckpoint).mockResolvedValueOnce(result(2, "synthetic-a.3mf"));
  await act(async () => resolve({ revision: 2, checkpointed_at: "t", file_count: 1 }));
  await waitFor(() => expect(screen.getByTestId("checkpoint-notice").textContent).toContain("saved for synthetic-a.3mf"));
  expect(screen.getByText("Checkpoint workspace: synthetic-a.3mf")).toBeTruthy();
});
