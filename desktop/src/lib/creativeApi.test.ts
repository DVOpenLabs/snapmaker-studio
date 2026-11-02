import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildInspectBody, buildPrepareBody, comparisonBuckets, factLines, fetchCreativeFormats, inspectCreative,
  originSentence, prepareCreative, settingsTotals,
} from "./creativeApi";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4321, token: "test-token" }) }));
const originalFetch = globalThis.fetch;
Object.defineProperty(globalThis, "location", { configurable: true, value: { search: "" } });
afterEach(() => { globalThis.fetch = originalFetch; vi.restoreAllMocks(); });

describe("creative API client", () => {
  it("trims the path and strips pasted quotes; omits the format when it is auto", () => {
    expect(buildInspectBody('  "C:\\x\\a.3mf" ')).toEqual({ path: "C:\\x\\a.3mf" });
    expect(buildInspectBody("a.3mf", "lixnix")).toEqual({ path: "a.3mf", format: "lixnix" });
  });

  it("says a blank path in words", () => {
    expect(() => buildInspectBody("   ")).toThrow("Enter the path of a .3mf project file.");
  });

  it("posts to /creative/inspect through the authenticated helper", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ origin: { generator: "unknown" } }), {
      status: 200, headers: { "Content-Type": "application/json" },
    }));
    globalThis.fetch = fetchMock;
    await inspectCreative("a.3mf");
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:4321/creative/inspect", expect.objectContaining({
      method: "POST", body: JSON.stringify({ path: "a.3mf" }),
    }));
  });

  it("maps a backend refusal to its message", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ error: "invalid", message: "That path is not a file Studio can read." }), { status: 400 }));
    await expect(inspectCreative("nope.3mf")).rejects.toMatchObject({ message: "That path is not a file Studio can read." });
  });

  it("keeps an unknown origin unknown and an ambiguous one undecided", () => {
    expect(originSentence({ generator: "unknown", status: "unknown", candidates: [] })).toContain("Origin unknown");
    expect(originSentence({ generator: "unknown", status: "ambiguous", candidates: ["forcaslicer", "lixnix"] }))
      .toBe("Origin not decided: the file's markers or settings match FOrcaSlicer and LixNix Full Multi-Nozzle.");
    expect(originSentence({ generator: "fullspectrum", status: "detected", candidates: ["fullspectrum"] })).toContain("Looks like FullSpectrum");
    expect(originSentence({ generator: "sindricad", status: "detected", candidates: ["sindricad"] })).toContain("Looks like SindriCAD");
  });

  it("builds the prepare body with an output folder only when one was typed", () => {
    expect(buildPrepareBody("a.3mf")).toEqual({ path: "a.3mf" });
    expect(buildPrepareBody(" a.3mf ", "sindricad", '  "D:\\out"  ')).toEqual({ path: "a.3mf", format: "sindricad", out_dir: "D:\\out" });
    expect(() => buildPrepareBody("", "auto", "x")).toThrow("Enter the path");
  });

  it("posts to /creative/prepare and /creative/formats", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ prepared: false, formats: [] }), {
      status: 200, headers: { "Content-Type": "application/json" } })));
    globalThis.fetch = fetchMock;
    await prepareCreative("a.3mf", "kromacut");
    await fetchCreativeFormats();
    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://127.0.0.1:4321/creative/prepare", expect.objectContaining({
      method: "POST", body: JSON.stringify({ path: "a.3mf", format: "kromacut" }) }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:4321/creative/formats", expect.objectContaining({ method: "POST", body: "{}" }));
  });

  it("turns reader facts into plain lines and skips facts that are absent", () => {
    const lines = factLines({ application: "SindriCAD", body_count: 2, painted_triangle_count: 0,
      bodies: [{ name: "Plate", extruder: 1 }], filament_colour: ["#FF0000", "#0000FF"], paint_extruders_used: [] });
    expect(lines).toContain("Written by (Application tag): SindriCAD");
    expect(lines).toContain("Body count: 2");
    expect(lines).toContain("Per-face paint: none found");
    expect(lines).toContain("Bodies: Plate (extruder 1)");
    expect(lines).toContain("Filament colours: #FF0000, #0000FF");
    expect(lines.some((l) => l.startsWith("Extruders used by paint"))).toBe(false);
    expect(factLines(undefined)).toEqual([]);
  });

  it("orders the comparison buckets kept, changed, dropped, added", () => {
    const buckets = comparisonBuckets({ opens_as_zip: true, comparison: { preserved: ["a"], modified: ["b"], dropped: ["c"], added: ["d"] } });
    expect(buckets.map((b) => `${b.key}:${b.items.join("")}`)).toEqual(["preserved:a", "modified:b", "dropped:c", "added:d"]);
    expect(buckets.every((b) => b.total === 1 && !b.truncated)).toBe(true);
  });

  it("uses the engine totals for the bucket headings and flags a capped list", () => {
    const buckets = comparisonBuckets({ opens_as_zip: true, comparison: { preserved: ["a", "b"], modified: [], dropped: [], added: [] },
      counts: { preserved: 250, modified: 0, dropped: 0, added: 0 } });
    expect(buckets[0]).toMatchObject({ total: 250, truncated: true });
    expect(buckets[1]).toMatchObject({ total: 0, truncated: false });
  });

  it("settings totals come from the counts, not from the bounded key lists", () => {
    expect(settingsTotals({ removed_keys: ["a"], removed_count: 9, changed_keys: [], changed_count: 4, added_key_count: 2 })).toEqual({ removed: 9, changed: 4, added: 2 });
    expect(settingsTotals({ removed_keys: ["a"], changed_keys: ["b", "c"], added_key_count: 0 })).toEqual({ removed: 1, changed: 2, added: 0 });
  });
});
