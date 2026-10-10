/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";

// Studio is local-first: nothing may pull a font from a remote host (#94). This guard covers named font hosts
// (Google Fonts, Bunny, Typekit, ...) and any remote @import in CSS/HTML/TS/TSX; it does not detect other remote URLs.
const sources = {
  ...import.meta.glob("./**/*.{css,html,ts,tsx}", { query: "?raw", import: "default", eager: true }),
  ...import.meta.glob("../index.html", { query: "?raw", import: "default", eager: true }),
} as Record<string, string>;

const REMOTE_FONT =
  /fonts\.googleapis\.com|fonts\.gstatic\.com|use\.typekit\.net|fonts\.bunny\.net|cdnfonts\.com|fontawesome\.com|@import\s+(url\(\s*)?["']?\s*(https?:)?\/\//i;

/** Lines of `text` that reference a remote font host or a remote @import. */
function remoteFontHits(text: string): string[] {
  return text.split(/\r?\n/).filter((l) => REMOTE_FONT.test(l));
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
      .flatMap(([f, text]) => remoteFontHits(text).map((l) => `${f}: ${l.trim()}`));
    expect(bad).toEqual([]);
  });

  it("the matcher catches the original offending import and common variants", () => {
    expect(remoteFontHits('@import url("https://fonts.googleapis.com/css2?family=Inter");')).toHaveLength(1);
    expect(remoteFontHits("@import 'http://example.com/a.css';")).toHaveLength(1);
    expect(remoteFontHits("@import url(//cdn.example.com/a.css);")).toHaveLength(1);
    expect(remoteFontHits('<link href="https://fonts.gstatic.com/s/x.woff2">')).toHaveLength(1);
    expect(remoteFontHits('@import "./local.css";')).toHaveLength(0);
    expect(remoteFontHits("font-family: ui-sans-serif, system-ui;")).toHaveLength(0);
  });
});
