import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { ReadyNowProject } from "@/api";

vi.mock("@/api", () => ({}));

const { ReadyNowSections, ReadyNowRow } = await import("./ReadyNowSections");

const noop = () => {};

function row(over: Partial<ReadyNowProject> = {}): ReadyNowProject {
  return {
    path: "C:/m/a.3mf", name: "a.3mf", bucket: "ready_now",
    top_reason: "Every material it asks for is loaded.", top_action: "Prepare it in Snapmaker Orca to slice.",
    confidence: "likely", evidence: [], unknowns: [], colour_notes: [], amount_checked: true,
    slots: [], file_state: "ok", ...over,
  };
}

const html = (rows: ReadyNowProject[]) =>
  renderToStaticMarkup(<ReadyNowSections results={rows} onOpen={noop} onPrepare={noop} />);

describe("ReadyNowSections", () => {
  it("draws only buckets that have projects, in display order", () => {
    const out = html([
      row({ path: "1", name: "attn.3mf", bucket: "needs_attention" }),
      row({ path: "2", name: "ready.3mf" }),
      row({ path: "3", name: "unk.3mf", bucket: "cant_determine" }),
    ]);
    expect(out.indexOf("Ready now (1)")).toBeGreaterThanOrEqual(0);
    expect(out.indexOf("Ready now (1)")).toBeLessThan(out.indexOf("Needs attention (1)"));
    expect(out.indexOf("Needs attention (1)")).toBeLessThan(out.indexOf("Can&#x27;t determine (1)"));
    expect(out).not.toContain("One change away");
  });

  it("gives every section an accessible heading", () => {
    const out = html([row()]);
    expect(out).toContain('aria-labelledby="rn-ready_now"');
    expect(out).toContain('id="rn-ready_now"');
  });

  it("a ready project with an unchecked amount carries a visible chip and caveated status", () => {
    const out = renderToStaticMarkup(
      <ReadyNowRow r={row({ amount_checked: false })} onOpen={noop} onPrepare={noop} />);
    expect(out).toContain("Amount not checked");
    expect(out).toContain("Ready now — amount not checked");
  });

  it("a checked amount shows no caveat chip", () => {
    const out = renderToStaticMarkup(<ReadyNowRow r={row()} onOpen={noop} onPrepare={noop} />);
    expect(out).not.toContain("Amount not checked");
  });

  it("shows the colour note prominently, once, without calling the colour right", () => {
    const out = renderToStaticMarkup(<ReadyNowRow
      r={row({ colour_notes: ["Right material, different colour: wants #FF0000, #0000FF loaded."],
               top_reason: "Prints now, but the loaded colour differs from the project." })}
      onOpen={noop} onPrepare={noop} />);
    expect(out).toContain('role="note"');
    expect(out.split("Prints now, but the loaded colour differs from the project.").length - 1).toBe(1);
    expect(out).toContain("Different colour loaded");
  });

  it("lists what Studio can't tell, and the confidence in words", () => {
    const out = renderToStaticMarkup(<ReadyNowRow
      r={row({ bucket: "cant_determine", confidence: "unknown", unknowns: ["Studio could not reach your printer."] })}
      onOpen={noop} onPrepare={noop} />);
    expect(out).toContain("Studio can&#x27;t tell");
    expect(out).toContain("Studio could not reach your printer.");
    expect(out).toContain("Confidence: Unknown");
  });

  it("offers Prepare a U1 copy only for needs_preparation", () => {
    const prep = renderToStaticMarkup(<ReadyNowRow
      r={row({ bucket: "needs_preparation", top_action: "Prepare a U1 copy first" })} onOpen={noop} onPrepare={noop} />);
    expect(prep).toContain("Open project");
    expect(prep).toContain("Prepare a U1 copy</button>");
    const ready = renderToStaticMarkup(<ReadyNowRow r={row()} onOpen={noop} onPrepare={noop} />);
    expect(ready).not.toContain("Prepare a U1 copy</button>");
  });

  it("a missing file explains itself and offers no actions", () => {
    const out = renderToStaticMarkup(<ReadyNowRow
      r={row({ bucket: "cant_determine", file_state: "missing" })} onOpen={noop} onPrepare={noop} />);
    expect(out).toContain("File not found");
    expect(out).not.toContain("Open project");
  });
});
