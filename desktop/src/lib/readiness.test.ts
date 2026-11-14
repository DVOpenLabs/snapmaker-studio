import { describe, it, expect } from "vitest";
import { readinessView, PROFILE_COPY_SAVED } from "./readiness";
import type { ReadinessReport } from "@/api";

const base: ReadinessReport = {
  schema_version: "report/1", name: "x.3mf", verdict: "READY", readiness_score: 100,
  ready: true, checks: [], preserved: [], changes: [], at_risk: [], warnings: [],
};

describe("readinessView — single source of truth", () => {
  it("ready only when report.ready is true", () => {
    const v = readinessView({ ...base, ready: true });
    expect(v.ready).toBe(true);
    expect(v.tone).toBe("ready");
    expect(v.headline).toMatch(/Ready for Orca/i);
  });

  it("a profile-compatible-but-risky file is NOT ready, never says U1-ready", () => {
    const v = readinessView({
      ...base, ready: false, readiness_score: 100,
      at_risk: ["13 colours but the U1 has 4 toolheads — plan colour swaps"],
    });
    expect(v.ready).toBe(false);
    expect(v.tone).toBe("risk");
    expect(v.headline).not.toMatch(/u1-ready|ready to slice/i);
    expect(v.nextActions.join(" ")).toMatch(/colour|remap/i);
  });

  it("no report yet -> Checking, never ready", () => {
    const v = readinessView(null);
    expect(v.ready).toBe(false);
    expect(v.tone).toBe("checking");
  });

  it("profile-copy wording is profile-only, not ready/clean/safe", () => {
    expect(PROFILE_COPY_SAVED).toMatch(/profile copy/i);
    expect(PROFILE_COPY_SAVED).not.toMatch(/u1-ready|clean|safe|ready to slice/i);
  });
});
