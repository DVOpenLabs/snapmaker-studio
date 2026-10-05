import { describe, it, expect } from "vitest";
import { MODEL_BROWSER_COPY, closedPanel, panelLabel, showPanel } from "./modelBrowser";

describe("Model Browser control panel", () => {
  it("hides the panel until a site is opened in-app", () => {
    expect(showPanel(closedPanel)).toBe(false);
    expect(panelLabel(closedPanel)).toMatch(/closed/i);
  });
  it("shows the open site once browsing in-app", () => {
    const s = { open: true, site: "Printables" };
    expect(showPanel(s)).toBe(true);
    expect(panelLabel(s)).toBe("Model Browser is open — browsing Printables");
  });
  it("flow copy uses the Studio Model Browser (no Chrome/Edge, no API keys, no auto-import)", () => {
    const all = (MODEL_BROWSER_COPY.flow + " " + MODEL_BROWSER_COPY.trust).toLowerCase();
    expect(all).toContain("studio model browser");
    expect(all).toContain("project doctor");
    expect(all).not.toMatch(/api key.*required|import to studio|downloads? for you|auto-?import|chrome|edge/);
  });
  it("describes Model Connect accurately: the browser downloads, Studio adds it to the library", () => {
    const flow = MODEL_BROWSER_COPY.flow.toLowerCase();
    const trust = MODEL_BROWSER_COPY.trust.toLowerCase();
    expect(flow).toContain("adds it to your library");
    expect(trust).toContain("never sees your password or cookies");
    expect(trust).toContain("never fetches files itself");
    expect(trust).toContain("no api keys are needed");
  });
});
