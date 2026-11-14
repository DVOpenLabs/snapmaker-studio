/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";

// #92 (every non-test file under desktop/src): no star rating, number or "will it print" promise may stand in for a readiness score.
const sources = import.meta.glob(["../**/*.{ts,tsx}", "!../**/*.test.{ts,tsx}", "!../**/*.d.ts"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

const BANNED: [string, RegExp][] = [
  ["star rating", /\bStars?\b|StarHalf|readinessStars|of 5`/],
  ["score field", /<dt>Score<\/dt>|d\.score|scoreCap|studio_score|print_success_score/],
  ["readiness score copy", /print-readiness score|readiness score|Readiness \(est/i],
  ["will-it-print promise", /will it print|will actually print|will stick|will print|will it fit and print|will the first layer|will your colou?rs print/i],
  ["certainty paraphrase", /always know|ready to print|print-ready|what's ready|what.s ready/i],
  ["0-100 health score", /0\s*[–-]\s*100/],
];

describe("no numeric readiness or will-it-print copy in the UI", () => {
  it("scans the whole UI source tree (a rename cannot silently shrink it)", () => {
    const names = Object.keys(sources);
    expect(names.length).toBeGreaterThan(80);
    for (const must of ["DesignInsights.tsx", "LiveWorkspace.tsx", "IntelligenceReport.tsx", "PrintRiskSignals.tsx", "Printers.tsx", "WhyStudio.tsx"]) {
      expect(names.some((n) => n.endsWith("/" + must)), must).toBe(true);
    }
  });

  for (const [name, re] of BANNED) {
    it(`has no ${name}`, () => {
      const hits = Object.entries(sources).filter(([, text]) => re.test(text)).map(([path]) => path);
      expect(hits).toEqual([]);
    });
  }
});
