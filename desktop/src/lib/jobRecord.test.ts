import { describe, expect, it } from "vitest";
import {
  classify, clearSliced, linkPrepared, linkSliced, openProject, parseRecord, restorable, withFingerprint,
  type JobRecord, type JobRole,
} from "./jobRecord";

const NOW = "2026-01-01T00:00:00.000Z";
const fp = (n: number) => ({ size_bytes: n, sha256: "a".repeat(63) + String(n % 10) });
const A = "C:\\work\\A.3mf";
const B = "C:\\work\\B.3mf";

function fullJob(): JobRecord {
  let r: JobRecord | null = openProject(null, A, NOW);
  r = withFingerprint(r, "original", A, fp(1));
  r = linkPrepared(r, A, "C:\\work\\A_U1.3mf", "preserve", NOW);
  r = withFingerprint(r, "prepared", "C:\\work\\A_U1.3mf", fp(2));
  r = linkSliced(r, A, "C:\\out\\A.gcode", NOW);
  r = withFingerprint(r, "sliced", "C:\\out\\A.gcode", fp(3));
  return r!;
}

describe("linking the three identities", () => {
  it("re-opening the same project keeps its prepared copy and sliced job", () => {
    const r = fullJob();
    expect(openProject(r, A, NOW)).toBe(r);
  });

  it("opening a different project starts a new job with nothing carried over", () => {
    const r = openProject(fullJob(), B, NOW);
    expect(r.original.path).toBe(B);
    expect(r.prepared).toBeNull();
    expect(r.sliced).toBeNull();
  });

  it("a prepared copy is not linked to a project that is not the job's original", () => {
    const r = openProject(null, A, NOW);
    expect(linkPrepared(r, B, "C:\\work\\B_U1.3mf", "preserve", NOW)).toBe(r);
  });

  it("a new prepared copy invalidates the earlier sliced job", () => {
    const r = linkPrepared(fullJob(), A, "C:\\work\\A_U1_2.3mf", "recommended", NOW)!;
    expect(r.prepared?.mode).toBe("recommended");
    expect(r.sliced).toBeNull();
  });

  it("G-code opened with no project, or beside another project, is not tied to this job", () => {
    const r = openProject(null, A, NOW);
    expect(linkSliced(r, null, "C:\\out\\x.gcode", NOW)).toBe(r);
    expect(linkSliced(r, B, "C:\\out\\x.gcode", NOW)).toBe(r);
    expect(linkSliced(r, A, "C:\\out\\x.gcode", NOW)?.sliced?.name).toBe("x.gcode");
  });

  it("a late fingerprint for a replaced file is dropped", () => {
    const r = fullJob();
    const after = withFingerprint(linkSliced(r, A, "C:\\out\\new.gcode", NOW), "sliced", "C:\\out\\A.gcode", fp(9))!;
    expect(after.sliced?.path).toBe("C:\\out\\new.gcode");
    expect(after.sliced?.fingerprint).toBeNull();
  });

  it("clearing the sliced job leaves the original and prepared copy", () => {
    const r = clearSliced(fullJob())!;
    expect(r.sliced).toBeNull();
    expect(r.prepared).not.toBeNull();
  });
});

describe("what a check lets Studio restore", () => {
  const report = (...pairs: Array<[JobRole, string]>) => pairs.map(([role, status]) => ({ role, status }));

  it("unchanged files restore without being asked twice", () => {
    const check = classify(fullJob(), report(["original", "same"], ["prepared", "same"], ["sliced", "same"]));
    expect(restorable(check, new Set())).toEqual(["original", "prepared", "sliced"]);
  });

  it("a changed file restores only when the person names it", () => {
    const check = classify(fullJob(), report(["original", "same"], ["prepared", "same"], ["sliced", "changed"]));
    expect(restorable(check, new Set())).toEqual(["original", "prepared"]);
    expect(restorable(check, new Set<JobRole>(["sliced"]))).toEqual(["original", "prepared", "sliced"]);
  });

  it("a missing or unreadable file never restores, even if named", () => {
    const check = classify(fullJob(), report(["original", "missing"], ["prepared", "unreadable"], ["sliced", "same"]));
    expect(check).toMatchObject({ original: "missing", prepared: "unreadable", sliced: "same" });
    expect(restorable(check, new Set<JobRole>(["original", "prepared"]))).toEqual([]);
    expect(restorable(check, new Set<JobRole>(["sliced"]))).toEqual(["sliced"]);
  });

  it("what was made from a project that is no longer provably the same is not offered back unasked", () => {
    const check = classify(fullJob(), report(["original", "changed"], ["prepared", "same"], ["sliced", "same"]));
    expect(restorable(check, new Set())).toEqual([]);
  });

  it("a file with no recorded fingerprint is unverified, never same", () => {
    const r = openProject(null, A, NOW);
    expect(classify(r, report(["original", "same"]))).toEqual({ original: "unverified" });
    expect(restorable({ original: "unverified" }, new Set())).toEqual([]);
  });

  it("a size-only comparison is unverified, never same", () => {
    expect(classify(fullJob(), report(["original", "unverified"])).original).toBe("unverified");
  });

  it("a file the engine did not report on is unreadable, not assumed fine", () => {
    expect(classify(fullJob(), report(["original", "same"])).sliced).toBe("unreadable");
  });
});

describe("reading a saved record back", () => {
  it("round-trips", () => {
    const r = fullJob();
    expect(parseRecord(JSON.stringify(r))).toEqual(r);
  });

  it.each([null, "", "not json", "{}", '{"schema":"job/2"}', '{"schema":"job/1","savedAt":"x"}',
    '{"schema":"job/1","savedAt":"x","original":{"path":""}}'])("treats %j as no saved job", (raw) => {
    expect(parseRecord(raw as string | null)).toBeNull();
  });

  it("drops a malformed fingerprint rather than trusting it", () => {
    const raw = JSON.stringify({ ...fullJob(), original: { path: A, name: "x", fingerprint: { size_bytes: "big", sha256: 5 } } });
    expect(parseRecord(raw)?.original.fingerprint).toBeNull();
  });
});

describe("re-linking the same file", () => {
  it("keeps the recorded fingerprint instead of forgetting it", () => {
    const r = fullJob();
    expect(linkSliced(r, A, "C:\\out\\A.gcode", NOW)).toBe(r);
    expect(linkPrepared(r, A, "C:\\work\\A_U1.3mf", "preserve", NOW)).toBe(r);
  });
});

describe("review repair round (lib)", () => {
  const report = (...pairs: Array<[JobRole, string]>) => pairs.map(([role, status]) => ({ role, status }));
  it("missing and unreadable survive a missing fingerprint", () => {
    const r = openProject(null, A, NOW);
    expect(classify(r, report(["original", "unreadable"])).original).toBe("unreadable");
    expect(classify(r, report(["original", "missing"])).original).toBe("missing");
    expect(classify(r, []).original).toBe("unreadable");
  });
  it("naming a changed original plans only the original", async () => {
    const { planFor } = await import("./jobRecord");
    const check = classify(fullJob(), report(["original", "changed"], ["prepared", "same"], ["sliced", "changed"]));
    expect(planFor(check, new Set<JobRole>(["original", "sliced"]))).toEqual(["original"]);
  });
  it("a non-integer recorded size is dropped, not trusted", () => {
    const raw = JSON.stringify({ ...fullJob(), original: { path: A, name: "x", fingerprint: { size_bytes: 1.5, sha256: null } } });
    expect(parseRecord(raw)?.original.fingerprint).toBeNull();
  });
});

describe("re-reading the same bytes", () => {
  it("does not make a new record", () => {
    const r = fullJob();
    expect(withFingerprint(r, "original", A, { ...fp(1), mtime_ns: "9" })).toBe(r);
  });
  it("different bytes do", () => {
    const r = fullJob();
    expect(withFingerprint(r, "original", A, fp(7))).not.toBe(r);
  });
});
