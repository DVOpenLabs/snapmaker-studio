/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";

// #92: no star rating, number or "will it print" promise may stand in for a readiness score.
const sources = import.meta.glob([
  "../routes/DesignInsights.tsx",
  "../routes/LiveWorkspace.tsx",
  "../routes/Dashboard.tsx",
  "../routes/WhyStudio.tsx",
  "../components/FirstPrintCard.tsx",
  "../components/IntelligenceReport.tsx",
  "../components/PrintRiskSignals.tsx",
], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

const BANNED: [string, RegExp][] = [
  ["star rating", /\bStars?\b|StarHalf|readinessStars|of 5`/],
  ["score field", /<dt>Score<\/dt>|d\.score|scoreCap|studio_score|print_success_score/],
  ["readiness score copy", /print-readiness score|readiness score|Readiness \(est/i],
  ["will-it-print promise", /will it print/i],
];

describe("no numeric readiness or will-it-print copy in the UI", () => {
  for (const [name, re] of BANNED) {
    it(`has no ${name}`, () => {
      const hits = Object.entries(sources).filter(([, text]) => re.test(text)).map(([path]) => path);
      expect(hits).toEqual([]);
    });
  }
});
