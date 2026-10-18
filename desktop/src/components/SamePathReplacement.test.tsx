// @vitest-environment jsdom
import React from "react";
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4312, token: "test" }) }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("@/api", () => ({ watchFolder: vi.fn(), jobCheck: vi.fn(), doctor: vi.fn().mockResolvedValue({}), convert: vi.fn(), diff: vi.fn() }));

import * as api from "@/api";
import { OrcaRoundTrip } from "@/components/OrcaRoundTrip";
import { observeSliced, trackJob, useJob } from "@/store/job";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";
import { useWatch } from "@/store/watch";

const A = "C:\\work\\A.3mf";
const P = "C:\\out\\A.gcode";
const hex = (c: string) => c.repeat(64);
const FP_A = { size_bytes: 30, sha256: hex("a") };   // the G-code Studio read first
const FP_B = { size_bytes: 31, sha256: hex("b") };   // a different, completed export at the same path

const recorded = (observed: any) => ({ schema_version: "job-check/1", files: [{ role: "sliced", path: P, status: "recorded", observed }] }) as any;
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const sighting = (over: Partial<Parameters<typeof observeSliced>[0]> = {}) =>
  ({ path: P, size_bytes: 31, age_seconds: 1, complete: true, ...over });

let stop: () => void;
let onDisk: any;

beforeEach(async () => {
  vi.clearAllMocks();
  localStorage.clear();
  useJob.setState({ record: null, verified: false, phase: "idle", check: {}, error: null });
  useSliced.setState({ path: null, name: null, revision: 0 });
  useSession.setState({ file: null });
  onDisk = FP_A;
  vi.mocked(api.jobCheck).mockImplementation(async (files: any) => recorded(onDisk) && ({
    schema_version: "job-check/1",
    files: files.map((f: any) => ({ role: f.role, path: f.path, status: "recorded", observed: f.role === "sliced" ? onDisk : { size_bytes: 10, sha256: hex("o") } })),
  }));
  stop = trackJob();
  useSession.getState().setFile(A);
  await settle();
  useSliced.getState().setSliced(P);
  await settle();
});
afterEach(() => { stop(); cleanup(); });

describe("a new export written over the open G-code's path", () => {
  it("replaces the saved identity and makes everything read from the old bytes read again", async () => {
    expect(useJob.getState().record?.sliced?.fingerprint).toEqual(FP_A);
    const before = useSliced.getState().revision;
    onDisk = FP_B;
    await observeSliced(sighting());
    expect(useJob.getState().record?.sliced?.fingerprint).toEqual(FP_B);
    expect(useSliced.getState().revision).toBe(before + 1);
    expect(useSliced.getState().path).toBe(P);
  });

  it("a rewrite with identical bytes is re-read once and changes nothing", async () => {
    const before = useSliced.getState().revision;
    await observeSliced(sighting({ size_bytes: 30, age_seconds: 0 }));
    expect(useSliced.getState().revision).toBe(before);
    expect(useJob.getState().record?.sliced?.fingerprint).toEqual(FP_A);
  });

  it("an incomplete file at that path is never read as the replacement", async () => {
    onDisk = FP_B;
    vi.mocked(api.jobCheck).mockClear();
    await observeSliced(sighting({ complete: false }));
    expect(api.jobCheck).not.toHaveBeenCalled();
    expect(useJob.getState().record?.sliced?.fingerprint).toEqual(FP_A);
    expect(useSliced.getState().revision).toBe(0);
  });

  it("a routine poll that sees the same untouched file hashes nothing", async () => {
    vi.mocked(api.jobCheck).mockClear();
    for (let i = 0; i < 5; i++) await observeSliced(sighting({ size_bytes: 30, age_seconds: 600 }));
    expect(api.jobCheck).not.toHaveBeenCalled();
  });

  it("a late observation cannot overwrite the replacement that was read after it", async () => {
    const releases: Array<(v: any) => void> = [];
    vi.mocked(api.jobCheck).mockImplementation(() => new Promise((resolve) => { releases.push(resolve); }));
    const first = observeSliced(sighting({ size_bytes: 31 }));
    const second = observeSliced(sighting({ size_bytes: 32 }));
    const FP_C = { size_bytes: 32, sha256: hex("c") };
    releases[1](recorded(FP_C));
    await second;
    releases[0](recorded(FP_B));
    await first;
    expect(useJob.getState().record?.sliced?.fingerprint).toEqual(FP_C);
  });

  it("a replacement that is another project's slice is not kept as this job's result, but is no longer shown as the old one", async () => {
    onDisk = FP_B;
    await observeSliced(sighting({ verdict: "no_match" }));
    expect(useJob.getState().record?.sliced).toBeNull();
    expect(useSliced.getState().revision).toBe(1);
  });

  it("a sighting of some other path is ignored", async () => {
    vi.mocked(api.jobCheck).mockClear();
    await observeSliced(sighting({ path: "C:\\out\\other.gcode" }));
    expect(api.jobCheck).not.toHaveBeenCalled();
  });
});

describe("through the folder watcher", () => {
  const candidate = (over: any = {}) => ({ path: P, name: "A.gcode", size_bytes: 31, age_seconds: 1, complete: true, state: "complete", ...over });
  const reply = (candidates: any[], best: string | null = null) =>
    ({ schema_version: "watch/1", available: true, folder: "C:\\out", best, candidates, summary: "" }) as any;

  it("a completed export of the open path refreshes it; ambiguity elsewhere still opens nothing", async () => {
    useSliced.getState().clear();
    useSliced.getState().setSliced(P);
    await settle();
    useWatch.setState({ folder: "C:\\out", autoOpen: true });
    onDisk = FP_B;
    vi.mocked(api.watchFolder).mockResolvedValue(reply([candidate(), candidate({ path: "C:\\out\\x.gcode", name: "x.gcode" })], null));
    render(<OrcaRoundTrip />);
    await act(async () => { await settle(); });
    expect(useSliced.getState().revision).toBe(1);
    expect(useSliced.getState().path).toBe(P);
  });

  it("an export still being written leaves the open job untouched", async () => {
    useWatch.setState({ folder: "C:\\out", autoOpen: true });
    onDisk = FP_B;
    vi.mocked(api.watchFolder).mockResolvedValue(reply([candidate({ complete: false, state: "still being written" })]));
    render(<OrcaRoundTrip />);
    await act(async () => { await settle(); });
    expect(useSliced.getState().revision).toBe(0);
    expect(useJob.getState().record?.sliced?.fingerprint).toEqual(FP_A);
  });
});
