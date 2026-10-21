import { describe, expect, it } from "vitest";
import {
  leftOut, leftOutReason, outcomesFor, pruneOutcomes, restoredNote, type JobCheck, type JobRecord, type RestoreOutcome,
} from "@/lib/jobRecord";

const fp = (c: string) => ({ size_bytes: 1, sha256: c.repeat(64) });
const REC: JobRecord = {
  schema: "job/1", savedAt: "t",
  original: { path: "o", name: "o.3mf", fingerprint: fp("a") },
  prepared: { path: "p", name: "p.3mf", fingerprint: fp("b"), mode: "preserve" },
  sliced: { path: "s", name: "s.gcode", fingerprint: fp("c") },
};

describe("restore outcomes", () => {
  it("record one outcome per checked file, with whether Reopen brought it back", () => {
    const check: JobCheck = { original: "same", prepared: "same", sliced: "changed" };
    const out = outcomesFor(REC, check, ["original"], new Set());
    expect(out.original).toMatchObject({ reopened: true, state: "same", sha: "a".repeat(64) });
    expect(out.prepared).toMatchObject({ reopened: false, state: "same" });
    expect(out.sliced).toMatchObject({ reopened: false, state: "changed" });
  });

  it("stop applying when the linked file is replaced or re-hashed, but survive the adopted file's new hash", () => {
    const out = outcomesFor(REC, { original: "same", prepared: "same", sliced: "changed" }, ["original", "sliced"], new Set(["sliced"]));
    const rehashed: JobRecord = { ...REC, prepared: { ...REC.prepared!, fingerprint: fp("z") }, sliced: { ...REC.sliced!, fingerprint: fp("y") } };
    const kept = pruneOutcomes(out, rehashed);
    expect(kept.original).toBeDefined();
    expect(kept.prepared).toBeUndefined();   // a different copy now
    expect(kept.sliced).toBeDefined();        // adopted: it follows the file on disk
    expect(pruneOutcomes(out, { ...REC, sliced: null }).sliced).toBeUndefined();
    expect(pruneOutcomes(out, null)).toEqual({});
  });

  it("word each case so a historical hash is never read as a current result", () => {
    const o = (over: Partial<RestoreOutcome>): RestoreOutcome => ({ path: "x", sha: null, state: "same", reopened: false, adopted: false, ...over });
    expect(restoredNote("original", o({ reopened: true }))).toMatchObject({ historical: false, tone: "ready" });
    expect(restoredNote("sliced", o({ reopened: true, adopted: true, state: "changed" })).text).toMatch(/follows the file as it is on disk/);
    for (const state of ["changed", "missing", "unreadable", "unverified"] as const) {
      const n = restoredNote("sliced", o({ state }));
      expect(n.historical).toBe(true);
      expect(n.text).toMatch(/^Not reopened — /);
      expect(n.text).toContain("The hash shown is the earlier record, not this file.");
    }
    expect(restoredNote("prepared", o({ state: "same" })).text).toMatch(/never reopens a prepared copy/);
  });

  it("list what is left out with its reason", () => {
    const check: JobCheck = { original: "same", prepared: "missing", sliced: "unreadable" };
    expect(leftOut(REC, check, ["original"])).toEqual([
      { role: "prepared", name: "p.3mf", why: leftOutReason("prepared", "missing") },
      { role: "sliced", name: "s.gcode", why: "could not be read" },
    ]);
    expect(leftOut(REC, { original: "same" }, ["original"])).toEqual([]);
  });
});
