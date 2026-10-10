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
  printer_status: "Not checked",
  cost: 0.21,
  currency: "$",
};
const render = (r: Report, defaultOpen = false) => renderToStaticMarkup(
  <QueryClientProvider client={new QueryClient()}><IntelligenceReport data={r} defaultOpen={defaultOpen} /></QueryClientProvider>,
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

  it("with the evidence expanded and a reachable (fake) printer, shows no health number, grade, 'good to print' or 'Compatible'", () => {
    const html = render({
      ...base,
      printer_status: "Answered, 1 concern",
      supporting: [
        { doctor: "Printer", status: "Answered, 1 concern", detail: "What the printer reported about its own firmware and print history." },
        { doctor: "First Layer Doctor", status: "OK", detail: "" },
      ],
    }, true);
    expect(html).toContain("Supporting Doctors");
    expect(html).toContain("Printer");
    expect(html).toContain("Answered, 1 concern");
    expect(html).not.toMatch(/\d+\s*\/\s*100|score|good to print|Healthy \(|Compatible/i);
  });

  it("uses one count for 'Risks found' and the comparison, and says only what was checked when nothing is found", () => {
    const html = render({
      ...base,
      comparison: { issues_found: 1, fixes_offered: 0, prices_the_print: false,
        orca_line: "Orca would slice this as-is, with no warning about the 1 risk Studio found.",
        studio_line: "Studio found 1 risk and offered 0 fixes before you slice." },
    });
    expect(html).toContain("Studio found 1 risk");
    expect(html).not.toMatch(/2 issues|no major blockers|it&#x27;d be fine/);
  });

  it("shows 'Not verified: object spacing' instead of 'Risks found 0' or a found-nothing claim", () => {
    const html = render({
      ...base, risks: [], biggest_risk: null, risks_found: 0, not_verified: ["object spacing"],
      verdict: "Studio's other checks found no risks, but object spacing was not verified. That is not a sign the print will succeed.",
      next_action: "Check spacing between objects in Snapmaker Orca, then prepare a U1 profile copy and review it before slicing.",
      comparison: { issues_found: 0, fixes_offered: 0, prices_the_print: false,
        orca_line: "Only Snapmaker Orca's preview can show spacing between objects.",
        studio_line: "Studio's other checks found nothing in this file, but object spacing was not verified." },
    });
    expect(html).toContain("Not verified");
    expect(html).toContain("Object spacing");
    expect(html).not.toMatch(/Risks found/i);
    expect(html).not.toContain("Orca slices the file as you give it");
    expect(html).not.toContain("Biggest risk");
  });
});
