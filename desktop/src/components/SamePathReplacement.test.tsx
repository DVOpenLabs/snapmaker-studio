// @vitest-environment jsdom
import React from "react";
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4312, token: "test" }) }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("@/api", () => ({
  watchFolder: vi.fn(), jobCheck: vi.fn(), doctor: vi.fn().mockResolvedValue({}), convert: vi.fn(), diff: vi.fn(),
  postSlice: vi.fn().mockResolvedValue({}), slicedCost: vi.fn().mockResolvedValue({}), sendCheck: vi.fn().mockResolvedValue({}),
  materialPlan: vi.fn().mockResolvedValue({}), printPlan: vi.fn().mockResolvedValue({}),
}));

import * as api from "@/api";
import { OrcaRoundTrip } from "@/components/OrcaRoundTrip";
import { SlicedJobCards } from "@/components/SlicedJobCards";
import { observeSliced, trackJob, useJob } from "@/store/job";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";
import { useWatch } from "@/store/watch";

const A = "C:\\work\\A.3mf";
const P = "C:\\out\\A.gcode";
const hex = (c: string) => c.repeat(64);

// Authored identities. mtime is the exact modification time the engine/watcher reports (text).
const V1 = { size_bytes: 30, sha256: hex("a"), mtime_ns: "1000" };   // the G-code Studio read first
const V2 = { size_bytes: 31, sha256: hex("b"), mtime_ns: "2000" };   // a different completed export, different size
const V3 = { size_bytes: 30, sha256: hex("c"), mtime_ns: "1500" };   // different bytes, SAME size, written moments later

const recorded = (observed: any) => ({ schema_version: "job-check/1", files: [{ role: "sliced", path: P, status: "recorded", observed }] }) as any;
const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
const sighting = (v: { size_bytes: number; mtime_ns: string }, over: Partial<Parameters<typeof observeSliced>[0]> = {}) =>
  ({ path: P, size_bytes: v.size_bytes, modified_ns: v.mtime_ns, complete: true, ...over });
const sliceCalls = () => vi.mocked(api.jobCheck).mock.calls.filter(([files]: any) => files[0]?.role === "sliced").length;

let stop: () => void;
let onDisk: any;
let failNext: boolean;

beforeEach(async () => {
  vi.clearAllMocks();
  localStorage.clear();
  useJob.setState({ record: null, verified: false, phase: "idle", check: {}, error: null });
  useSliced.setState({ path: null, name: null, revision: 0 });
  useSession.setState({ file: null });
  onDisk = V1;
  failNext = false;
  vi.mocked(api.jobCheck).mockImplementation(async (files: any) => {
    if (failNext && files[0].role === "sliced") { failNext = false; throw new Error("engine busy"); }
    return {
      schema_version: "job-check/1",
      files: files.map((f: any) => ({ role: f.role, path: f.path, status: "recorded", observed: f.role === "sliced" ? onDisk : { size_bytes: 10, sha256: hex("o"), mtime_ns: "1" } })),
    };
  });
  stop = trackJob();
  useSession.getState().setFile(A);
  await settle();
  useSliced.getState().setSliced(P);
  await settle();
});
afterEach(() => { stop(); cleanup(); });

describe("a new export written over the open G-code's path", () => {
  it("opening the G-code reads it once and records that identity", () => {
    expect(sliceCalls()).toBe(1);
    expect(useJob.getState().record?.sliced?.fingerprint).toMatchObject({ size_bytes: 30, sha256: hex("a") });
  });

  it("replaces the saved identity and makes everything read from the old bytes read again", async () => {
    onDisk = V2;
    observeSliced(sighting(V2));
    await settle();
    expect(useJob.getState().record?.sliced?.fingerprint).toMatchObject({ size_bytes: 31, sha256: hex("b") });
    expect(useSliced.getState().revision).toBe(1);
    expect(useSliced.getState().path).toBe(P);
  });

  it("S1: a different export of the SAME size written moments after the first is still noticed", async () => {
    onDisk = V3;
    observeSliced(sighting(V3));
    await settle();
    expect(useJob.getState().record?.sliced?.fingerprint).toMatchObject({ sha256: hex("c") });
    expect(useSliced.getState().revision).toBe(1);
  });

  it("an untouched file is never read again, however often it is sighted", async () => {
    for (let i = 0; i < 6; i++) { observeSliced(sighting(V1)); await settle(); }
    expect(sliceCalls()).toBe(1);
    expect(useSliced.getState().revision).toBe(0);
  });

  it("a rewrite with identical bytes is read once, changes nothing, and is then remembered", async () => {
    const same = { ...V1, mtime_ns: "5000" };
    onDisk = same;
    observeSliced(sighting(same));
    await settle();
    expect(useSliced.getState().revision).toBe(0);
    observeSliced(sighting(same));
    await settle();
    expect(sliceCalls()).toBe(2);
  });

  it("an incomplete file at that path is never read as the replacement", async () => {
    onDisk = V2;
    observeSliced(sighting(V2, { complete: false }));
    await settle();
    expect(sliceCalls()).toBe(1);
    expect(useSliced.getState().revision).toBe(0);
  });

  it("S3: a failed read is retried on the next completed sighting, even for an equal-size rewrite", async () => {
    onDisk = V3;
    failNext = true;
    observeSliced(sighting(V3));
    await settle();
    expect(useSliced.getState().revision).toBe(0);
    observeSliced(sighting(V3));
    await settle();
    expect(useJob.getState().record?.sliced?.fingerprint).toMatchObject({ sha256: hex("c") });
    expect(useSliced.getState().revision).toBe(1);
  });

  it("S4: if the first read never established an identity, the next completed sighting reads and refreshes", async () => {
    useSliced.getState().clear();                 // unlinks the first read while tracking
    await settle();
    stop();
    failNext = true;
    stop = trackJob();
    useSliced.getState().setSliced(P);            // initial read throws
    await settle();
    expect(useJob.getState().record?.sliced?.fingerprint ?? null).toBeNull();
    observeSliced(sighting(V1));
    await settle();
    expect(useJob.getState().record?.sliced?.fingerprint).toMatchObject({ sha256: hex("a") });
    expect(useSliced.getState().revision).toBe(1);
  });

  it("S2: a read still in flight when a replacement is sighted cannot be overwritten by, or overwrite, it", async () => {
    stop();
    useSliced.getState().clear();
    const releases: Array<(v: any) => void> = [];
    vi.mocked(api.jobCheck).mockImplementation(() => new Promise((resolve) => { releases.push(resolve); }));
    stop = trackJob();
    useSliced.getState().setSliced(P);            // initial read #1 pending with the OLD bytes
    await settle();
    observeSliced(sighting(V2));                  // sighted meanwhile: no second read is stacked
    await settle();
    expect(releases.length).toBe(1);
    releases[0](recorded(V1));                    // old bytes land
    await settle();
    expect(useJob.getState().record?.sliced?.fingerprint).toMatchObject({ sha256: hex("a") });
    onDisk = V2;
    vi.mocked(api.jobCheck).mockImplementation(async () => recorded(V2));
    observeSliced(sighting(V2));                  // the replacement is now read, and wins
    await settle();
    expect(useJob.getState().record?.sliced?.fingerprint).toMatchObject({ sha256: hex("b") });
  });

  it("a read for a path that is no longer open is discarded", async () => {
    stop();
    useSliced.getState().clear();
    const releases: Array<(v: any) => void> = [];
    vi.mocked(api.jobCheck).mockImplementation(() => new Promise((resolve) => { releases.push(resolve); }));
    stop = trackJob();
    useSliced.getState().setSliced(P);
    await settle();
    useSliced.getState().clear();
    releases[0](recorded(V2));
    await settle();
    expect(useJob.getState().record?.sliced ?? null).toBeNull();
    expect(useSliced.getState().revision).toBe(0);
  });

  it("S2b: a replacement read still in flight when the G-code is closed refreshes nothing", async () => {
    const releases: Array<(v: any) => void> = [];
    vi.mocked(api.jobCheck).mockImplementation(() => new Promise((resolve) => { releases.push(resolve); }));
    observeSliced(sighting(V2));                  // replacement read pending
    await settle();
    expect(releases.length).toBe(1);
    useSliced.getState().clear();                 // the person closes the G-code
    releases[0](recorded(V2));
    await settle();
    expect(useSliced.getState().revision).toBe(0);
  });

  it("a replacement that is another project's slice is not kept as this job's result, but is no longer shown as the old one", async () => {
    onDisk = V2;
    observeSliced(sighting(V2, { verdict: "no_match" }));
    await settle();
    expect(useJob.getState().record?.sliced).toBeNull();
    expect(useSliced.getState().revision).toBe(1);
  });

  it("N6: a size-only identity (no hash) is never treated as the same bytes", async () => {
    stop();
    useSliced.getState().clear();
    onDisk = { size_bytes: 30, sha256: null, mtime_ns: "1000" };
    stop = trackJob();
    useSliced.getState().setSliced(P);
    await settle();
    onDisk = { size_bytes: 30, sha256: null, mtime_ns: "9000" };
    observeSliced(sighting({ size_bytes: 30, mtime_ns: "9000" }));
    await settle();
    expect(useSliced.getState().revision).toBe(1);
  });

  it("a sighting of some other path is ignored", async () => {
    observeSliced(sighting(V2, { path: "C:\\out\\other.gcode" }));
    await settle();
    expect(sliceCalls()).toBe(1);
  });
});

describe("every page that shows the G-code checks re-reads them on a replacement", () => {
  it("the shared cards read again when the revision changes, and not otherwise", async () => {
    render(<SlicedJobCards path={P} projectPath={A} />);
    await act(async () => { await settle(); });
    const first = vi.mocked(api.postSlice).mock.calls.length;
    expect(first).toBe(1);
    await act(async () => { useSliced.getState().refresh(); await settle(); });
    expect(vi.mocked(api.postSlice).mock.calls.length).toBe(2);
    await act(async () => { await settle(); });
    expect(vi.mocked(api.postSlice).mock.calls.length).toBe(2);
  });

  it("both pages use the shared cards instead of mounting the four cards themselves", () => {
    const pages = import.meta.glob("../routes/{AfterSlicing,Cockpit}.tsx", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    expect(Object.keys(pages).length).toBe(2);
    for (const [page, text] of Object.entries(pages)) {
      expect(text, page).toContain("<SlicedJobCards");
      for (const card of ["<PostSliceCard", "<SendReadyCard", "<MaterialPlanCard", "<PrintPlanCard"]) {
        expect(text.includes(card), `${page} mounts ${card} directly`).toBe(false);
      }
    }
  });
});

describe("through the folder watcher", () => {
  const candidate = (v: { size_bytes: number; mtime_ns: string }, over: any = {}) =>
    ({ path: P, name: "A.gcode", size_bytes: v.size_bytes, modified_ns: v.mtime_ns, age_seconds: 1, complete: true, state: "complete", ...over });
  const reply = (candidates: any[], best: string | null = null) =>
    ({ schema_version: "watch/1", available: true, folder: "C:\\out", best, candidates, summary: "" }) as any;

  it("a completed export of the open path refreshes it; ambiguity elsewhere still opens nothing", async () => {
    useWatch.setState({ folder: "C:\\out", autoOpen: true });
    onDisk = V3;
    vi.mocked(api.watchFolder).mockResolvedValue(reply([candidate(V3), candidate(V2, { path: "C:\\out\\x.gcode", name: "x.gcode" })], null));
    render(<OrcaRoundTrip />);
    await act(async () => { await settle(); });
    expect(useSliced.getState().revision).toBe(1);
    expect(useSliced.getState().path).toBe(P);
  });

  it("an export still being written leaves the open job untouched", async () => {
    useWatch.setState({ folder: "C:\\out", autoOpen: true });
    onDisk = V2;
    vi.mocked(api.watchFolder).mockResolvedValue(reply([candidate(V2, { complete: false, state: "still being written" })]));
    render(<OrcaRoundTrip />);
    await act(async () => { await settle(); });
    expect(useSliced.getState().revision).toBe(0);
    expect(useJob.getState().record?.sliced?.fingerprint).toMatchObject({ sha256: hex("a") });
  });
});
