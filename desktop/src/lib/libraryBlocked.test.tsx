// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import record from "@/test-fixtures/library-blocked.json";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4312, token: "t" }) }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

import { StatusBadge, type Verdict } from "@/components/ui/badge";
import { FILTERS } from "@/routes/Projects";
import type { LibraryProject } from "@/api";

// `record` is the library row the engine really emitted for a readable project Prepare would refuse
// (backend test_the_committed_desktop_fixture_is_what_the_producer_really_emits keeps it honest).
const row = record as unknown as LibraryProject;

describe("a stored library record that Prepare would refuse", () => {
  it("is not shown as Fixable / Needs prep once the Model Connect card is gone", () => {
    const html = renderToStaticMarkup(
      <StatusBadge verdict={row.verdict as Verdict} prepareBlocked={row.prepare_blocked} />);
    expect(html).toContain("Review in Orca first");
    expect(html).not.toContain("Fixable");
  });
  it("is filtered under Review in Orca, not Needs prep or Profile compatible", () => {
    const by = Object.fromEntries(FILTERS.map((f) => [f.label, f.match(row)]));
    expect(by["Review in Orca"]).toBe(true);
    expect(by["Needs prep"]).toBe(false);
    expect(by["Profile compatible"]).toBe(false);
    expect(by["All"]).toBe(true);
  });
  it("an ordinary record keeps its own badge and filter", () => {
    const plain = { ...row, prepare_blocked: false, prepare_summary: null };
    expect(renderToStaticMarkup(<StatusBadge verdict="REPAIRABLE" prepareBlocked={plain.prepare_blocked} />)).toContain("Fixable");
    expect(FILTERS.find((f) => f.label === "Needs prep")!.match(plain)).toBe(true);
  });
});

describe("library header counts", () => {
  it("need-prep, review and ready counts agree with the filters", async () => {
    const { libraryCounts } = await import("@/routes/Projects");
    const rows = [
      row,                                                              // blocked
      { ...row, prepare_blocked: false, verdict: "REPAIRABLE" },        // needs prep
      { ...row, prepare_blocked: false, verdict: "READY" },             // compatible
    ];
    expect(libraryCounts(rows)).toEqual({ total: 3, ready: 1, needPrep: 1, review: 1 });
  });
});
