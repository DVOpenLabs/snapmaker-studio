import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const { AddedFromView } = await import("./AddedFromCard");
const { toAddedItem } = await import("@/lib/modelDownloads");

const item = toAddedItem("C:/dl/Gearbox.3mf", {
  ok: true, project_id: 3, name: "Gearbox.3mf", site_name: "Printables",
  source_family: "bambu", verdict: "REPAIRABLE", filament_count: 2,
});

function render(over = {}) {
  const noop = vi.fn();
  return renderToStaticMarkup(
    <AddedFromView item={{ ...item, ...over }} onCheck={noop} onPrepare={noop} onOpen={noop} onDismiss={noop} />,
  );
}

describe("AddedFromView", () => {
  it("shows the heading, the file, the detected facts and the three actions", () => {
    const html = render();
    expect(html).toContain("Added from Printables");
    expect(html).toContain("Gearbox.3mf");
    expect(html).toContain("Bambu Studio project");
    expect(html).toContain("2 filaments in the project");
    for (const label of ["Check for U1", "Prepare", "Open project"]) expect(html).toContain(label);
    expect(html).toContain('aria-label="Dismiss Gearbox.3mf"');
  });
  it("shows no facts list when nothing was detected", () => {
    expect(render({ facts: [] })).not.toContain("<ul");
  });
  it("never shows the local file path", () => {
    expect(render()).not.toContain("C:/dl");
  });
});

describe("Model Connect source guards", () => {
  // Raw source text via Vite, so the guard needs no Node typings.
  const sources = (import.meta as any).glob(
    [
      "./ModelDownloadListener.tsx",
      "./AddedFromCard.tsx",
      "../lib/modelDownloads.ts",
      "../store/modelDownloads.ts",
    ],
    { query: "?raw", import: "default", eager: true },
  ) as Record<string, string>;

  it("found the files it guards", () => {
    expect(Object.keys(sources)).toHaveLength(4);
  });
  it("the page-side code never touches cookies, tokens or the site's page", () => {
    for (const [file, src] of Object.entries(sources)) {
      expect(src, file).not.toMatch(/document\.cookie|localStorage|sessionStorage|cookies?\(/i);
      expect(src, file).not.toMatch(/fetch\(/);
    }
  });
  it("the listener hands the engine only what the shell reported, nothing from the site", () => {
    const src = Object.entries(sources).find(([k]) => k.endsWith("ModelDownloadListener.tsx"))![1];
    expect(src).toContain("registerDownloadedModel(e.path, e.site, e.page_url)");
  });
});
