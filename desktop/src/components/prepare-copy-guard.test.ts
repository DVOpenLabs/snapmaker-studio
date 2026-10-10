/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";

const BANNED = ["optimized", "safe settings", "we fixed", "best", "ready", "clean"];
const BANNED_PATTERNS = [/\bsafe\b/i, /print-ready/i, /guaranteed/i];
const sources = import.meta.glob([
  "./PrepareModeChooser.tsx",
  "./PrepareSettingsSummary.tsx",
  "../lib/evidenceKind.ts",
  "./FirstPrintCard.tsx",
  "../routes/Compatibility.tsx",
  "../routes/DesignInsights.tsx",
  "../routes/LiveWorkspace.tsx",
], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

// Pre-existing non-prepare UI state/style snippets. Each is removed once, rather
// than removing its entire line, so other copy on that line remains checked.
const allowlistedRouteSubstrings: Record<string, string[]> = {
  "Compatibility.tsx": ["ready", "ready", "ready", "clean"],
  "DesignInsights.tsx": Array<string>(29).fill("ready"),
  "LiveWorkspace.tsx": Array<string>(12).fill("ready"),
};

// Residual limitation: byte-identical banned text inside an allowed snippet is still permitted.
function sourceWithoutAllowlistedSubstrings(path: string, source: string) {
  const filename = path.split("/").pop() ?? "";
  return (allowlistedRouteSubstrings[filename] ?? []).reduce((text, allowed) => text.replace(allowed, ""), source);
}

function disallowedWording(text: string) {
  return [
    ...BANNED.filter((word) => text.toLowerCase().includes(word)),
    ...BANNED_PATTERNS.filter((pattern) => pattern.test(text)).map(String),
  ];
}

describe("prepare copy", () => {
  it("contains none of the disallowed wording", () => {
    const text = Object.entries(sources).map(([path, source]) => sourceWithoutAllowlistedSubstrings(path, source)).join("\n");
    expect(disallowedWording(text)).toEqual([]);
  });

  it("catches banned copy beside an allowlisted snippet on the same line", () => {
    const text = sourceWithoutAllowlistedSubstrings("../routes/Compatibility.tsx", '<span className="text-ready">safe</span>');
    expect(disallowedWording(text)).toContain("/\\bsafe\\b/i");
  });

  it("would catch banned FirstPrintCard-style copy", () => {
    expect(disallowedWording('label: "Prepare a safe U1 copy"')).toContain("/\\bsafe\\b/i");
  });
});
