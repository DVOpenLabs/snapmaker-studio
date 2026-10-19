/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";

// The visible privacy claims must match what the app does: files and checks stay on this computer, a printer is
// contacted only after it is set up, and features the person starts (update check, model browser) use the internet.
// "Nothing leaves your network" and "zero network activity" are not claims Studio can make.
const sources = import.meta.glob("./**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

describe("visible local-first wording", () => {
  it("no screen promises that nothing leaves the network or that there is no network activity", () => {
    const bad = Object.entries(sources)
      .filter(([f]) => !/\.test\.tsx?$/.test(f))
      .flatMap(([f, t]) => [...t.matchAll(/nothing leaves your network|zero network|no network (activity|traffic|requests)/gi)].map((m) => `${f}: ${m[0]}`));
    expect(bad).toEqual([]);
  });

  it("the status bar and Settings say what is true", () => {
    const status = sources["./components/shell/StatusBar.tsx"];
    expect(status).toContain("Local-first · your files stay on this computer");
    const settings = sources["./routes/Settings.tsx"];
    expect(settings).toMatch(/Studio contacts a printer only after you set one up/);
    expect(settings).toMatch(/update check or the model browser, use the internet/);
  });
});

describe("path placeholders", () => {
  it("show one backslash per separator, not the doubled form a string literal would give", () => {
    const bad = Object.entries(sources)
      .filter(([f]) => !/\.test\.tsx?$/.test(f))
      .flatMap(([f, t]) => [...t.matchAll(/placeholder="([^"]*)"/g)].filter((m) => /[A-Za-z]:\\\\/.test(m[1])).map((m) => `${f}: ${m[1]}`));
    expect(bad).toEqual([]);
  });
});

describe("Recent projects card", () => {
  it("keeps the project name wrappable on its own line and the status chip below it, so a long name cannot be overlapped", () => {
    const t = sources["./routes/Dashboard.tsx"];
    const card = t.slice(t.indexOf("recent.length > 0"));
    expect(card).toContain("min-w-0 line-clamp-3 font-medium leading-snug [overflow-wrap:anywhere]");
    expect(card).toContain("flex min-w-0 flex-col gap-2");
    expect(card).not.toContain("truncate font-medium");
    expect(card).toMatch(/sm:grid-cols-2 2xl:grid-cols-3/);
  });
});
