import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { PrintFindings } from "@/api";

const { PrintRiskSignals } = await import("./PrintRiskSignals");

const limitations = [
  "Studio checks the things listed above. It cannot know your slicer settings.",
  "Verify in Snapmaker Orca before you print.",
];
const flagged: PrintFindings = {
  available: true,
  summary: "Studio found 2 things worth settling before you slice.",
  signals: [
    { id: "toolhead-fit", kind: "engine", level: "risk", title: "More colors than toolheads", meaning: "The design uses more colors than the U1 can load at once.", action: "Remap to fewer colors in Snapmaker Orca." },
    { id: "design-validation", kind: "engine", level: "warn", title: "Design validation flagged 1 issue", meaning: "Something may cause trouble when slicing.", action: "Read the issues in Design Health.", details: ["Mesh has a hole"] },
  ],
  checked: ["design validation", "colors against toolheads"],
  not_checked: ["printer health", "object spacing"],
  limitations,
};
const render = (f: PrintFindings) => renderToStaticMarkup(<PrintRiskSignals findings={f} />);

describe("PrintRiskSignals", () => {
  it("lists each signal with its meaning, action, evidence label and details", () => {
    const html = render(flagged);
    expect(html).toContain("Print risk signals");
    expect(html).toContain("Risk: More colors than toolheads");
    expect(html).toContain("Heads up: Design validation flagged 1 issue");
    expect(html).toContain("Studio&#x27;s check");
    expect(html).toContain("What to do:");
    expect(html).toContain("Mesh has a hole");
    expect(html).toContain("Studio checked:");
    expect(html).toContain("Studio did not check:");
    expect(html).toContain("object spacing");
    expect(html).toContain("Verify in Snapmaker Orca");
  });

  it("shows no percentage, band or success verdict, with or without signals", () => {
    const clean: PrintFindings = { ...flagged, signals: [], summary: "Studio's checks did not flag anything in what they covered: design validation. That is not a sign the print will succeed." };
    for (const f of [flagged, clean]) {
      const html = render(f);
      expect(html).not.toMatch(/\d\s*%/);
      expect(html).not.toMatch(/Likely to print|Risky|Few risks|readiness|guarantee/i);
    }
    expect(render(clean)).toContain("not a sign the print will succeed");
  });

  it("explains an empty result instead of saying nothing", () => {
    const html = render({ available: false, reason: "no design or printer information was available to check", limitations });
    expect(html).toContain("Studio has nothing to check yet");
    expect(html).toContain("Verify in Snapmaker Orca");
  });
});
