import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import PassportReport from "./PassportReport";
import { SAMPLE_PASSPORT, invalidatedVerification, sampleVerification } from "./sample";

const html = (v = sampleVerification()) => renderToStaticMarkup(<PassportReport passport={SAMPLE_PASSPORT} verification={v} />);

describe("passport report", () => {
  it("shows the chain, the declared links and what was kept or left out", () => {
    const out = html();
    for (const word of ["Original", "Prepared copy", "Sliced output", "Matches the passport", "declared by user"]) expect(out).toContain(word);
    expect(out).toContain("Kept: 1 recipe(s), 1 material mapping(s).");
    expect(out).toContain("not known to this build");
    expect(out).toContain("Every file matches the bytes the passport recorded.");
  });

  it("shows invalidation and a differing declared parent", () => {
    const out = html(invalidatedVerification());
    expect(out).toContain("Invalidated");
    expect(out).toContain("Bytes changed");
    expect(out).toContain("which has changed");
    expect(out).toContain("Declared parent differs");
    expect(out).not.toContain("Every file matches");
  });

  it("says nothing was left out only when nothing was", () => {
    expect(html(sampleVerification({ losses: [] }))).toContain("Nothing was left out.");
  });

  it("avoids banned wording", () => {
    const visible = html(invalidatedVerification()).replace(/ class="[^"]*"/g, "");   // class names such as bg-ready are not copy
    expect(visible).not.toMatch(/simultaneous|guarantee|100\s*%|coming soon|\bready\b/i);
  });
});
