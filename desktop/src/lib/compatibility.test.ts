import { describe, it, expect } from "vitest";
import { COMPAT_COPY, sortFindings, severityLabel, countFindings } from "./compatibility";
import type { CompatibilityFinding } from "@/api";

const findings: CompatibilityFinding[] = [
  { id: "extrusion.relative_no_reset", severity: "warning", title: "Relative extrusion without a per-layer reset",
    explanation: "Your profile uses relative extrusion.", setting_path: "Metadata/project_settings.config -> layer_change_gcode",
    suggested_action: "Switch back to the official Snapmaker U1 profile.", evidence: "no G92 E0" },
  { id: "value.wall_filament", severity: "error", title: "Invalid value for wall_filament",
    explanation: "Settings from another printer.", setting_path: "Metadata/project_settings.config -> wall_filament",
    suggested_action: "Import into a clean Snapmaker U1 project.", evidence: "wall_filament = 0 (valid range [1,2147483647])" },
];

describe("8. findings render in plain language (severity labels)", () => {
  it("maps severities to beginner labels", () => {
    expect(severityLabel("error")).toBe("Needs attention");
    expect(severityLabel("warning")).toBe("Heads up");
  });
  it("orders errors before warnings", () => {
    expect(sortFindings(findings).map((f) => f.severity)).toEqual(["error", "warning"]);
  });
  it("counts by severity", () => {
    const c = countFindings(findings);
    expect(c.errors).toBe(1); expect(c.warnings).toBe(1); expect(c.total).toBe(2);
  });
});

describe("9. setting path + action are present on findings", () => {
  it("every finding carries a setting_path and a suggested_action", () => {
    for (const f of findings) {
      expect(f.setting_path.length).toBeGreaterThan(0);
      expect(f.suggested_action.length).toBeGreaterThan(0);
    }
  });
});

describe("10. no auto-fix claim in copy", () => {
  it("copy says read-only / does not fix automatically", () => {
    const all = Object.values(COMPAT_COPY).join(" ").toLowerCase();
    expect(all).not.toMatch(/auto-?fix|fixes it automatically|automatically fix/);
    expect(COMPAT_COPY.readOnlyNote.toLowerCase()).toContain("read-only");
  });
});

describe("11. no paid/commercial model names in copy", () => {
  it("copy contains no known commercial fixture names", () => {
    const all = Object.values(COMPAT_COPY).join(" ").toLowerCase();
    for (const name of ["freedom torch", "fox sake", "jesus", "shadow_ams"]) {
      expect(all).not.toContain(name);
    }
  });
});

import { prepareGate } from "./compatibility";
describe("prepareGate", () => {
  const f = (id: string): CompatibilityFinding => ({ id, severity: "warning", title: "", explanation: "", suggested_action: "", setting_path: "", evidence: "" });
  it("is open without either finding", () => { expect(prepareGate([f("x")])).toBe("open"); expect(prepareGate(null)).toBe("open"); });
  it("is blocked for prepare.blocked", () => expect(prepareGate([f("prepare.blocked")])).toBe("blocked"));
  it("is unreadable for project.unreadable, which wins", () =>
    expect(prepareGate([f("prepare.blocked"), f("project.unreadable")])).toBe("unreadable"));
});
