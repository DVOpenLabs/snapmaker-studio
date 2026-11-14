import { describe, expect, it } from "vitest";
import { buildRequest } from "./api";
import { invalidatedVerification, sampleVerification } from "./sample";
import { chainSummary, derivationText, lossText, reasonText } from "./view";

describe("passport request", () => {
  it("orders entries original, prepared, sliced and skips blanks", () => {
    const body = buildRequest({ sliced: " c.gcode ", original: "a.3mf", prepared: "" });
    expect(body.entries).toEqual([{ path: "a.3mf", role: "original" }, { path: "c.gcode", role: "sliced" }]);
    expect(body.recipes).toBeUndefined();
  });

  it("refuses an empty form and bad JSON before any request", () => {
    expect(() => buildRequest({})).toThrow(/at least one file/);
    expect(() => buildRequest({ original: "a" }, "{")).toThrow(/Recipes must be valid JSON/);
    expect(() => buildRequest({ original: "a" }, "", "{}")).toThrow(/Material mappings must be a JSON list/);
    expect(buildRequest({ original: "a" }, "[]", "[{\"slot_ref\":\"slot:0\"}]").material_mappings).toHaveLength(1);
  });
});

describe("passport wording", () => {
  it("says every file matches only when every file matched", () => {
    expect(chainSummary(sampleVerification().artifacts)).toBe("Every file matches the bytes the passport recorded.");
    const unknown = sampleVerification().artifacts.map((a, i) => (i === 2 ? { ...a, chain: "unverified" as const } : a));
    expect(chainSummary(unknown)).toBe("1 of 3 files could not be checked.");
    expect(chainSummary(invalidatedVerification().artifacts)).toContain("no longer match");
    expect(chainSummary([])).toBe("No files in the passport.");
  });

  it("explains reasons, losses and declared links in plain words", () => {
    expect(reasonText({ code: "ancestor_changed", artifact: "a.3mf" })).toContain("which has changed");
    expect(reasonText({ code: "bytes_missing", artifact: "a.3mf" })).toContain("not found");
    expect(lossText({ kind: "recipe", id: "r", reason: "unknown_schema_version" })).toContain("not known to this build");
    expect(lossText({ kind: "material_mapping", id: "slot:0", reason: "field_not_retained:note" })).toContain('"note" is not kept');
    const d = invalidatedVerification().derivations[0];
    expect(derivationText(d)).toContain("declared by user");
    expect(derivationText(d)).toContain("different bytes than declared");
    expect(derivationText({ ...d, witness: "local", declared_by: null, declared_mismatch: false })).toContain("seen by Studio");
  });
});
