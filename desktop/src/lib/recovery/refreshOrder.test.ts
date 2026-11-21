import { beforeEach, expect, it, vi } from "vitest";
vi.mock("./api", () => ({ restoreCheckpoint: vi.fn() }));
import { restoreCheckpoint, type RestoreResult } from "./api";
import { __resetRecoverySubscriberForTests, getPreview, refreshPreview } from "./subscriber";
const deferred = () => {
  let resolve!: (value: RestoreResult) => void; let reject!: (error: Error) => void;
  const promise = new Promise<RestoreResult>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const result = (revision: number): RestoreResult => ({ missing_checkpoint: false, revision, checkpointed_at: "t", workspace: {}, observations: [], files: [], jobs: [], fresh_read_required: true });
beforeEach(() => { vi.resetAllMocks(); __resetRecoverySubscriberForTests(); });
it("an old success cannot replace the newer restore preview", async () => {
  const old = deferred(), fresh = deferred(); vi.mocked(restoreCheckpoint).mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
  const first = refreshPreview(), second = refreshPreview();
  fresh.resolve(result(2)); await second; old.resolve(result(1)); await first;
  expect(getPreview().data?.revision).toBe(2); expect(getPreview().status).toBe("ready");
});
it("an old failure cannot hide a newer success", async () => {
  const old = deferred(), fresh = deferred(); vi.mocked(restoreCheckpoint).mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
  const first = refreshPreview(), second = refreshPreview(); fresh.resolve(result(3)); await second;
  old.reject(new Error("old refusal")); await first; expect(getPreview().error).toBe(""); expect(getPreview().status).toBe("ready");
});
it("an old success cannot erase a newer refusal", async () => {
  const old = deferred(), fresh = deferred(); vi.mocked(restoreCheckpoint).mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
  const first = refreshPreview(), second = refreshPreview(); fresh.reject(new Error("new refusal")); await second;
  old.resolve(result(1)); await first; expect(getPreview().status).toBe("failed"); expect(getPreview().error).toBe("new refusal");
});
it("reset prevents an outstanding request from repopulating another test/session", async () => {
  const old = deferred(); vi.mocked(restoreCheckpoint).mockReturnValueOnce(old.promise);
  const first = refreshPreview(); __resetRecoverySubscriberForTests(); old.resolve(result(1)); await first;
  expect(getPreview()).toEqual({ status: "idle", data: null, error: "" });
});
