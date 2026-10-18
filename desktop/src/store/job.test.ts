// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4312, token: "test" }) }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("@/api", () => ({ jobCheck: vi.fn(), doctor: vi.fn(), convert: vi.fn(), diff: vi.fn() }));

import * as api from "@/api";

const A = "C:\\work\\A.3mf";
const P = "C:\\work\\A_U1.3mf";
const G = "C:\\out\\A.gcode";
const hex = (c: string) => c.repeat(64);

/** A pretend engine: fingerprints by path, and answers checks from a table the test edits. */
function engine(disk: Record<string, { size_bytes: number; sha256: string | null } | undefined>) {
  vi.mocked(api.jobCheck).mockImplementation(async (files) => ({
    schema_version: "job-check/1",
    files: files.map((f) => {
      const seen = disk[f.path];
      if (!seen) return { role: f.role, path: f.path, status: "missing" as const };
      if (!f.expected) return { role: f.role, path: f.path, status: "recorded" as const, observed: seen };
      const same = seen.size_bytes === f.expected.size_bytes && seen.sha256 === f.expected.sha256;
      return { role: f.role, path: f.path, status: same ? "same" as const : "changed" as const, observed: seen };
    }),
  }));
}

async function fresh() {
  vi.resetModules();
  const job = await import("./job");
  const session = await import("./session");
  const sliced = await import("./sliced");
  return { ...job, useSession: session.useSession, useSliced: sliced.useSliced };
}

const settle = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.mocked(api.doctor).mockResolvedValue({} as any);
});
afterEach(() => vi.restoreAllMocks());

async function linkedJob(disk: Parameters<typeof engine>[0]) {
  engine(disk);
  const m = await fresh();
  const stop = m.trackJob();
  m.useSession.getState().setFile(A);
  await settle();
  m.useSession.setState({ convert: { status: "done", error: null, data: { output_path: P, output_name: "A_U1.3mf", validated_ok: true, prepare_mode: "preserve", settings_summary: {} } as any } });
  await settle();
  m.useSliced.getState().setSliced(G);
  await settle();
  return { ...m, stop };
}

const DISK = () => ({ [A]: { size_bytes: 10, sha256: hex("a") }, [P]: { size_bytes: 20, sha256: hex("b") }, [G]: { size_bytes: 30, sha256: hex("c") } });

describe("linking as the person works", () => {
  it("ties original, prepared copy and sliced job together with their fingerprints", async () => {
    const m = await linkedJob(DISK());
    const r = m.useJob.getState().record!;
    expect([r.original.path, r.prepared?.path, r.sliced?.path]).toEqual([A, P, G]);
    expect(r.original.fingerprint).toEqual({ size_bytes: 10, sha256: hex("a") });
    expect(r.prepared?.fingerprint?.size_bytes).toBe(20);
    expect(r.sliced?.fingerprint?.size_bytes).toBe(30);
  });

  it("a blocked or unvalidated preparation is not linked as a prepared copy", async () => {
    engine(DISK());
    const m = await fresh();
    m.trackJob();
    m.useSession.getState().setFile(A);
    await settle();
    m.useSession.setState({ convert: { status: "done", error: null, data: { output_path: P, validated_ok: false, prepare_mode: "preserve" } as any } });
    m.useSession.setState({ convert: { status: "done", error: null, data: { output_path: P, validated_ok: true, blocked: true, prepare_mode: "preserve" } as any } });
    await settle();
    expect(m.useJob.getState().record?.prepared).toBeNull();
  });

  it("opening another project starts a new job and drops the old links", async () => {
    const m = await linkedJob(DISK());
    m.useSession.getState().setFile("C:\\work\\B.3mf");
    await settle();
    const r = m.useJob.getState().record!;
    expect(r.original.path).toBe("C:\\work\\B.3mf");
    expect(r.prepared).toBeNull();
    expect(r.sliced).toBeNull();
  });

  it("choosing another G-code clears the sliced link", async () => {
    const m = await linkedJob(DISK());
    m.useSliced.getState().clear();
    expect(m.useJob.getState().record?.sliced).toBeNull();
  });
});

describe("after a restart", () => {
  it("the job survives module reinitialisation, and is only offered, not reopened", async () => {
    const first = await linkedJob(DISK());
    first.stop();
    const m = await fresh();
    expect(m.useJob.getState().record?.original.path).toBe(A);
    expect(m.useSession.getState().file).toBeNull();
    expect(m.useSliced.getState().path).toBeNull();
    expect(api.convert).not.toHaveBeenCalled();
  });

  it("unchanged files restore the project and G-code, and nothing is prepared or re-sliced", async () => {
    const first = await linkedJob(DISK());
    first.stop();
    engine(DISK());
    const m = await fresh();
    await m.useJob.getState().runCheck();
    expect(m.useJob.getState().check).toEqual({ original: "same", prepared: "same", sliced: "same" });
    m.useJob.getState().restore(new Set());
    expect(m.useSession.getState().file?.path).toBe(A);
    expect(m.useSliced.getState().path).toBe(G);
    expect(api.convert).not.toHaveBeenCalled();
  });

  it("a changed G-code is not reopened unless the person names it", async () => {
    const first = await linkedJob(DISK());
    first.stop();
    engine({ ...DISK(), [G]: { size_bytes: 31, sha256: hex("d") } });
    const m = await fresh();
    await m.useJob.getState().runCheck();
    expect(m.useJob.getState().check.sliced).toBe("changed");
    m.useJob.getState().restore(new Set());
    expect(m.useSliced.getState().path).toBeNull();
    expect(m.useSession.getState().file?.path).toBe(A);
  });

  it("naming a changed G-code reopens it and adopts what is on disk as its identity", async () => {
    const first = await linkedJob(DISK());
    first.stop();
    const moved = { size_bytes: 31, sha256: hex("d") };
    engine({ ...DISK(), [G]: moved });
    const m = await fresh();
    await m.useJob.getState().runCheck();
    m.useJob.getState().restore(new Set(["sliced"]));
    await settle();
    expect(m.useSliced.getState().path).toBe(G);
    expect(m.useJob.getState().record?.sliced?.fingerprint).toEqual(moved);
  });

  it("a missing G-code is never reopened, even if named", async () => {
    const first = await linkedJob(DISK());
    first.stop();
    const disk = DISK(); delete (disk as any)[G];
    engine(disk);
    const m = await fresh();
    await m.useJob.getState().runCheck();
    expect(m.useJob.getState().check.sliced).toBe("missing");
    m.useJob.getState().restore(new Set(["sliced"]));
    expect(m.useSliced.getState().path).toBeNull();
  });

  it("a changed original reopens only when named, and its old prepared copy and G-code are no longer presented as its results", async () => {
    const first = await linkedJob(DISK());
    first.stop();
    engine({ ...DISK(), [A]: { size_bytes: 11, sha256: hex("e") } });
    const m = await fresh();
    await m.useJob.getState().runCheck();
    m.useJob.getState().restore(new Set());
    expect(m.useSession.getState().file).toBeNull();
    await m.useJob.getState().runCheck();
    m.useJob.getState().restore(new Set(["original", "sliced"]));
    await settle();
    expect(m.useSession.getState().file?.path).toBe(A);
    expect(m.useSliced.getState().path).toBeNull();
    const r = m.useJob.getState().record!;
    expect(r.prepared).toBeNull();
    expect(r.sliced).toBeNull();
  });

  it("a file with no recorded fingerprint is unverified and not reopened unnamed", async () => {
    vi.mocked(api.jobCheck).mockRejectedValue(new Error("engine down"));
    const first = await fresh();
    first.trackJob();
    first.useSession.getState().setFile(A);
    await settle();
    expect(first.useJob.getState().record?.original.fingerprint).toBeNull();
    engine(DISK());
    const m = await fresh();
    await m.useJob.getState().runCheck();
    expect(m.useJob.getState().check.original).toBe("unverified");
    m.useJob.getState().restore(new Set());
    expect(m.useSession.getState().file).toBeNull();
  });

  it("a check that comes back after the job was forgotten is dropped", async () => {
    const first = await linkedJob(DISK());
    first.stop();
    let release!: (v: any) => void;
    vi.mocked(api.jobCheck).mockImplementation(() => new Promise((resolve) => { release = resolve; }));
    const m = await fresh();
    const pending = m.useJob.getState().runCheck();
    m.useJob.getState().forget();
    release({ schema_version: "job-check/1", files: [{ role: "original", path: A, status: "same" }] });
    await pending;
    expect(m.useJob.getState().record).toBeNull();
    expect(m.useJob.getState().phase).toBe("idle");
    expect(localStorage.getItem("snapstudio.job.v1")).toBeNull();
  });

  it("restore does nothing until a check has been run", async () => {
    const first = await linkedJob(DISK());
    first.stop();
    const m = await fresh();
    m.useJob.getState().restore(new Set(["original", "sliced", "prepared"]));
    expect(m.useSession.getState().file).toBeNull();
    expect(m.useSliced.getState().path).toBeNull();
  });
});
