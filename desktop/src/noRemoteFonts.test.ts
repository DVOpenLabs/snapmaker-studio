/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";

// Studio is local-first: nothing may pull a font from a remote host (#94). This guard covers named font hosts
// (Google Fonts, Bunny, Typekit, ...) and any remote @import in CSS/HTML/TS/TSX; it does not detect other remote URLs.
const sources = {
  ...import.meta.glob("./**/*.{css,html,ts,tsx}", { query: "?raw", import: "default", eager: true }),
  ...import.meta.glob("../index.html", { query: "?raw", import: "default", eager: true }),
} as Record<string, string>;

// Whitespace, newlines and CSS comments may sit between the parts of an @import.
const GAP = String.raw`(?:\s|/\*[\s\S]*?\*/)`;
const REMOTE_FONT = new RegExp(
  [
    String.raw`fonts\.googleapis\.com|fonts\.gstatic\.com|use\.typekit\.net|fonts\.bunny\.net|cdnfonts\.com|fontawesome\.com`,
    String.raw`@import${GAP}+(?:url\(${GAP}*)?["']?${GAP}*(?:https?:)?//`,
  ].join("|"),
  "gi",
);

/** Every remote font host or remote @import in `text`, matched across line breaks and comments. */
function remoteFontHits(text: string): string[] {
  return [...text.matchAll(REMOTE_FONT)].map((m) => m[0].replace(/\s+/g, " "));
}

describe("no remote font requests (#94)", () => {
  it("finds the sources to scan", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50);
    expect(Object.keys(sources)).toContain("./index.css");
    expect(Object.keys(sources)).toContain("../index.html");
    // Vacuity guard: if raw CSS is stubbed to empty (vitest.config.ts css.include), the scan below would pass on nothing.
    expect(sources["./index.css"]).toContain("@tailwind");
  });

  it("no CSS, HTML or TSX under desktop/src or index.html references an external font host", () => {
    const bad = Object.entries(sources)
      .filter(([f]) => !f.endsWith("noRemoteFonts.test.ts"))
      .flatMap(([f, text]) => remoteFontHits(text).map((h) => `${f}: ${h}`));
    expect(bad).toEqual([]);
  });

  it("the matcher catches the original offending import and common variants", () => {
    const hits = (t: string) => (remoteFontHits(t).length > 0 ? 1 : 0);
    expect(hits('@import url("https://fonts.googleapis.com/css2?family=Inter");')).toBe(1);
    expect(hits("@import 'http://example.com/a.css';")).toBe(1);
    expect(hits("@import url(//cdn.example.com/a.css);")).toBe(1);
    expect(hits('<link href="https://fonts.gstatic.com/s/x.woff2">')).toBe(1);
    expect(hits('@import "https://example.com/fonts.css";')).toBe(1);
  });

  it("catches an @import split across lines or interrupted by comments", () => {
    const hits = (t: string) => (remoteFontHits(t).length > 0 ? 1 : 0);
    expect(hits('@import\n  url(\n"https://example.com/fonts.css"\n);')).toBe(1);
    expect(hits('@import /* why */\n  url(/* x */ "https://example.com/f.css");')).toBe(1);
    expect(hits('@import /* why */ "//example.com/f.css";')).toBe(1);
    expect(hits("a {}\n\n  https://fonts.bunny.net/css?family=x\n")).toBe(1);
  });

  it("lets local imports and local or data: fonts through", () => {
    const hits = (t: string) => (remoteFontHits(t).length > 0 ? 1 : 0);
    expect(hits('@import "./local.css";')).toBe(0);
    expect(hits('@import\n url("./local.css");')).toBe(0);
    expect(hits('@font-face { src: url("./fonts/a.woff2"), url(data:font/woff2;base64,AAAA); }')).toBe(0);
    expect(hits("font-family: ui-sans-serif, system-ui;")).toBe(0);
  });
});
