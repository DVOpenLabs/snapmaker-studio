import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MonitorSummary, RestorePreview } from "./RecoveryPanel";
import { isValidPort } from "./api";
import type { RestoreResult } from "./api";

const base: RestoreResult = {
  missing_checkpoint: false, revision: 3, checkpointed_at: "2026-01-01T00:00:00Z", workspace: {},
  files: [
    { name: "a.3mf", state: "same", association: "unverified" },
    { name: "b.3mf", state: "changed", association: "unverified" },
    { name: "c.3mf", state: "missing", association: "unverified" },
  ],
  jobs: [{ job_id: "j1", state: "interrupted", replayed: false }],
  observations: [{ historical: true, usable_for_loadout: false }],
  fresh_read_required: true, legacy_job: null,
};

describe("RestorePreview", () => {
  it("shows changed and missing files and the historical notice", () => {
    const html = renderToStaticMarkup(<RestorePreview data={base} />);
    expect(html).toContain("b.3mf: changed since the checkpoint");
    expect(html).toContain("c.3mf: missing from its recorded location");
    expect(html).toContain("2 file(s) changed or missing");
    expect(html).toContain("Historical, re-read needed");
    expect(html).toContain("was interrupted. It was recorded, not resumed.");
  });
  it("shows filename association as unverified and never claims printing", () => {
    const html = renderToStaticMarkup(<RestorePreview data={base} />);
    expect(html).toContain("Matched by filename only (unverified)");
    expect(html.toLowerCase()).not.toContain("printing this file");
    expect(html.toLowerCase()).not.toMatch(/guaranteed|100%|is printing/);
  });
  it("handles loading and missing checkpoint", () => {
    expect(renderToStaticMarkup(<RestorePreview data={null} />)).toContain("Reading the last checkpoint");
    expect(renderToStaticMarkup(<RestorePreview data={{ ...base, missing_checkpoint: true }} />)).toContain("No checkpoint saved yet");
  });
});

describe("MonitorSummary", () => {
  it("keeps unknown unknown", () => {
    const html = renderToStaticMarkup(<MonitorSummary read={{ print_state: "printing", filename: "x.gcode", association: "unverified" }} />);
    expect(html).toContain("Printer state reported: printing");
    expect(html).toContain("match to a local file: unverified");
    expect(html).toContain("Camera: unknown");
    expect(renderToStaticMarkup(<MonitorSummary read={null} />)).toBe("");
  });
});

describe("monitor port validation", () => {
  it("accepts only whole-number ports in the TCP range", () => {
    for (const value of ["1", "7125", "65535"]) expect(isValidPort(value)).toBe(true);
    for (const value of ["", "0", "65536", "7125.5", "1e3", " 7125", "port"]) {
      expect(isValidPort(value)).toBe(false);
    }
  });
});
