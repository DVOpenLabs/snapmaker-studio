import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import type { IntelligenceReport as Report } from "@/api";

const { IntelligenceReport } = await import("./IntelligenceReport");

const base: Report = {
  available: true,
  risks_found: 1,
  risks: [{ doctor: "Project Doctor", level: "warn", text: "Design validation flagged 6 issues" }],
  biggest_risk: { doctor: "Project Doctor", level: "warn", text: "Design validation flagged 6 issues" },
  next_action: "Read the issues in Design Health.",
  verdict: "1 risk found; top risk: Design validation flagged 6 issues.",
  printer_compatibility: "Unknown",
  cost: 0.21,
  currency: "$",
};
const render = (r: Report) => renderToStaticMarkup(
  <QueryClientProvider client={new QueryClient()}><IntelligenceReport data={r} /></QueryClientProvider>,
);

describe("IntelligenceReport", () => {
  it("shows a count of risks found and no score hero, percentage or readiness rating", () => {
    const html = render(base);
    expect(html).toContain("Risks found");
    expect(html).toContain("Design validation flagged 6 issues");
    expect(html).not.toMatch(/\/ 100|\/100|Readiness|readiness|Studio score|expected print success/i);
    expect(html).not.toMatch(/>\s*\d+\s*%</);
  });

  it("never shows a green or numeric score for a flawed file, even if an old reply carries studio_score", () => {
    const html = render({ ...base, studio_score: 100, print_success_score: 100 } as Report);
    expect(html).not.toContain("100");
    expect(html).not.toMatch(/stage-validate/);
  });

  it("says the count is advisory and points to Snapmaker Orca", () => {
    const html = render(base);
    expect(html).toContain("not a measure of how likely the print is to succeed");
    expect(html).toContain("Verify in Snapmaker Orca");
  });
});
