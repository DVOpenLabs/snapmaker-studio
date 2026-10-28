import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import SetupReportView from "./SetupReportView";
import { SAMPLE_REPORT } from "./sampleReport";

const html = (r = SAMPLE_REPORT) => renderToStaticMarkup(<SetupReportView report={r} />);

describe("setup report view", () => {
  it("shows all four states, historical, the legacy notice and the verdict", () => {
    const out = html();
    for (const word of ["Available", "Unknown", "Stale", "Historical"]) expect(out).toContain(word);
    expect(out).toContain("assume four heads");
    expect(out).toContain("not validated for this setup");
    expect(out).toContain("cannot give every requested material a head");
  });

  it("states an unknown head count as not reported and hides the notice when it does not apply", () => {
    const e = { ...SAMPLE_REPORT.entries[0], counts: { ...SAMPLE_REPORT.entries[0].counts!, physical_heads: null } };
    const out = html({ ...SAMPLE_REPORT, entries: [e], legacy_limitation: { applies: false, reasons: [], text: null } });
    expect(out).toContain("not reported");
    expect(out).not.toContain("legacy-notice");
  });

  it("does not show an unread slot count as zero", () => {
    const first = SAMPLE_REPORT.entries[0];
    const caps = first.capabilities.map((c) => (c.key === "logical_slots" ? { ...c, state: "unknown" as const } : c));
    const e = { ...first, counts: { ...first.counts!, logical_slots: 0 }, capabilities: caps };
    const out = html({ ...SAMPLE_REPORT, entries: [e] });
    expect(out).toMatch(/Logical slots:\s*(<!-- -->)?not reported/);
    expect(out).not.toMatch(/Logical slots:\s*(<!-- -->)?0/);
    expect(html()).toMatch(/Logical slots:\s*(<!-- -->)?8/);
  });

  it("avoids banned wording", () => {
    expect(html()).not.toMatch(/simultaneous|guarantee|100\s*%|coming soon|8 nozzles/i);
  });
});
