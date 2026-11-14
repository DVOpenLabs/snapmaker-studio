import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import CreativeReportView from "./CreativeReportView";
import CreativeView from "./CreativeView";
import CreativeFormatChooser from "./CreativeFormatChooser";
import CreativePreparePanel, { ExportVerification } from "./CreativePreparePanel";
import creativeRoute from "@/routes/ext/creative.route";
import creativeMeta from "@/routes/ext/creative.meta";
import type { CreativeFormatInfo, CreativeInspectResponse, CreativePrepareResponse } from "@/lib/creativeApi";

const HASH = "a".repeat(64);

function report(over: Partial<CreativeInspectResponse> = {}): CreativeInspectResponse {
  return {
    origin: { generator: "fullspectrum", status: "detected", candidates: ["fullspectrum"] },
    understood: ["mixed_filament_definitions"],
    passed_through: [{ name: "layer_height", sha256: HASH }],
    could_not_interpret: ["fos_future_key"],
    missing: ["fos_physical_nozzle_diameter"],
    diagnostics: ["unrecognized_fullspectrum_row_shape"],
    recipes: [{ recipe_id: "fullspectrum:7", generator: { name: "FullSpectrum", version: "0.9.12" }, kind: "fullspectrum",
      components: [{ source: "project:1:1" }, { source: "project:1:2" }], simulated: true, execution_supported: false }],
    physical_slots_needed: 2,
    source: { name: "synthetic.3mf", size_bytes: 1234, sha256_before: HASH, sha256_after: HASH, unchanged: true },
    evidence: "fixture-tested", advisory: "Advisory read of one project file.",
    ...over,
  };
}

describe("creative route wiring", () => {
  it("route default export has the { path, Component } shape and meta agrees", () => {
    expect(Object.keys(creativeRoute).sort()).toEqual(["Component", "path"]);
    expect(typeof creativeRoute.Component).toBe("function");
    expect(creativeRoute.path).toBe("/creative");
    expect(creativeMeta.path).toBe(creativeRoute.path);
    expect(creativeMeta.group).toBe("Studio+");
    expect(creativeMeta.label).toBe("Creative import");
  });
});

describe("creative report view", () => {
  const html = renderToStaticMarkup(<CreativeReportView report={report()} />);

  it("shows understood, untouched and could-not-interpret buckets", () => {
    expect(html).toContain("mixed_filament_definitions");
    expect(html).toContain("layer_height (aaaaaaaa)");
    expect(html).toContain("fos_future_key");
    expect(html).toContain("fos_physical_nozzle_diameter (expected, not found)");
    expect(html).toContain("note: unrecognized_fullspectrum_row_shape");
  });

  it("labels recipes as simulated, not executed, ratios not stated", () => {
    expect(html).toContain("fullspectrum:7");
    expect(html).toContain("ratios not stated");
    expect(html).toContain("Simulated; execution not supported");
    expect(html).toContain("not a statement about your loaded filament");
  });

  it("shows the unchanged-original hash line and the evidence label", () => {
    expect(html).toContain("Original unchanged");
    expect(html).toContain("before aaaaaaaaaaaaaaaa, after aaaaaaaaaaaaaaaa");
    expect(html).toContain("fixture-tested");
  });

  it("reports a changed fingerprint instead of claiming it is unchanged", () => {
    const changed = renderToStaticMarkup(<CreativeReportView report={report({
      source: { name: "x.3mf", size_bytes: 1, sha256_before: HASH, sha256_after: "b".repeat(64), unchanged: false } })} />);
    expect(changed).not.toContain("Original unchanged");
    expect(changed).toContain("differs between the two reads");
  });

  it("unknown origin stays unknown", () => {
    const h = renderToStaticMarkup(<CreativeReportView report={report({ origin: { generator: "unknown", status: "unknown", candidates: [] }, recipes: [], physical_slots_needed: null })} />);
    expect(h).toContain("Origin unknown");
    expect(h).toContain("No recipes in this file.");
  });

  it("has no overclaiming or readiness wording", () => {
    const all = (html + renderToStaticMarkup(<CreativeView />)).toLowerCase();
    for (const banned of ["ready", "coming soon", "guarantee", "100%", "simultaneous", "print success", "printer doctor"]) {
      expect(all).not.toContain(banned);
    }
  });
});

describe("creative view", () => {
  it("renders the path input, format choice and a disabled inspect button", () => {
    const html = renderToStaticMarkup(<CreativeView />);
    expect(html).toContain("Project file path");
    expect(html).toContain("Detect from markers and settings");
    expect(html).toMatch(/<button[^>]*disabled[^>]*>Inspect project/);
  });

  it("offers every supported tool in the format list, including the three new readers", () => {
    const html = renderToStaticMarkup(<CreativeView />);
    for (const label of ["DitherForge", "Kromacut", "SindriCAD", "OrcaSlicer ImageMap", "Lumina Layers"]) expect(html).toContain(label);
  });
});

const FORMAT: CreativeFormatInfo = {
  key: "imagemap", label: "OrcaSlicer ImageMap", carrier: "3MF (ZIP) with 3D/3dmodel.model", selection: "manual only",
  identified_by: [], reads: ["3MF artifact identity (size, SHA-256, member list)"], kept_untouched: ["every part"],
  not_read: ["the zone shape: not established"], upstream: null,
};

describe("format chooser", () => {
  it("says plainly what is and is not read for a manual-only format", () => {
    const html = renderToStaticMarkup(<CreativeFormatChooser value="imagemap" onChange={() => undefined} formats={[FORMAT]} needsChoice={false} />);
    expect(html).toContain("read only when you choose it");
    expect(html).toContain("Studio reads");
    expect(html).toContain("3MF artifact identity");
    expect(html).toContain("Studio does not read");
    expect(html).toContain("the zone shape: not established");
    expect(html).toContain("cannot confirm the file really came from this tool");
  });

  it("words automatic identification as conditional on markers being present", () => {
    const html = renderToStaticMarkup(<CreativeFormatChooser value="sindricad" onChange={() => undefined} formats={[{ ...FORMAT, key: "sindricad", label: "SindriCAD", selection: "automatic", identified_by: ["model metadata Application `SindriCAD`"] }]} needsChoice={false} />);
    expect(html).toContain("identified automatically only when its markers are present in the file");
    expect(html).not.toContain("detected automatically");
    expect(html).not.toContain("Prepare limits");
  });

  it("states a format's Prepare limits when the engine lists them", () => {
    const html = renderToStaticMarkup(<CreativeFormatChooser value="ditherforge" onChange={() => undefined} formats={[{ ...FORMAT, key: "ditherforge", label: "DitherForge", selection: "automatic", prepare_limits: ["The generic-path export is inspect-only."] }]} needsChoice={false} />);
    expect(html).toContain("Prepare limits");
    expect(html).toContain("The generic-path export is inspect-only.");
  });

  it("asks for a choice when detection could not decide, and not otherwise", () => {
    const ask = renderToStaticMarkup(<CreativeFormatChooser value="auto" onChange={() => undefined} formats={[]} needsChoice />);
    expect(ask).toContain("Studio could not decide the tool");
    const quiet = renderToStaticMarkup(<CreativeFormatChooser value="auto" onChange={() => undefined} formats={[]} needsChoice={false} />);
    expect(quiet).not.toContain("Studio could not decide the tool");
    expect(quiet).toContain("does not guess the tool");
  });
});

describe("inspection of the new tools", () => {
  it("shows facts read from a SindriCAD file and its read and not-read lists", () => {
    const html = renderToStaticMarkup(<CreativeReportView report={report({
      origin: { generator: "sindricad", status: "detected", candidates: ["sindricad"] }, recipes: [], physical_slots_needed: null,
      facts: { sindricad: { application: "SindriCAD", body_count: 2, bodies: [{ name: "Plate", extruder: 1 }, { name: "Lid", extruder: 2 }], painted_triangle_count: 2, paint_extruders_used: [2], filament_colour: ["#FF0000", "#0000FF"] } },
      format_info: [{ ...FORMAT, key: "sindricad", label: "SindriCAD", selection: "automatic", identified_by: ["model metadata Application `SindriCAD`"], not_read: ["mesh geometry beyond counts"] }],
    })} />);
    expect(html).toContain("Looks like SindriCAD");
    expect(html).toContain("Body count: 2");
    expect(html).toContain("Bodies: Plate (extruder 1), Lid (extruder 2)");
    expect(html).toContain("Per-face paint: 2 painted triangle(s)");
    expect(html).toContain("SindriCAD: what is and is not read");
    expect(html).toContain("mesh geometry beyond counts");
  });

  it("explains an undecided origin: what was seen, what is not supported, what to do", () => {
    const html = renderToStaticMarkup(<CreativeReportView report={report({
      origin: { generator: "unknown", status: "unknown", candidates: [] }, recipes: [], physical_slots_needed: null,
      explanation: { kind: "unknown_origin", seen: "This file is a 3MF project with 2 parts.", not_supported: "No supported tool's markers were found.", what_to_do: ["Choose the format you know it came from."] },
    })} />);
    expect(html).toContain("does not recognise this file&#x27;s tool");
    expect(html).toContain("What Studio saw.");
    expect(html).toContain("What is not supported.");
    expect(html).toContain("What to do.");
    expect(html).toContain("Choose the format you know it came from.");
  });
});

const BASE_SOURCE = { name: "x.3mf", size_bytes: 1, sha256_before: HASH, sha256_after: HASH, unchanged: true };

describe("prepare panel", () => {
  const done: CreativePrepareResponse = {
    prepared: true, origin: { generator: "sindricad", status: "detected", candidates: ["sindricad"] },
    output: { name: "x_SnapmakerU1.3mf", local_path: "synthetic/prepared-copy.3mf", location: "studio_default", location_label: "Studio's creative-prepared folder", in_source_folder: false },
    prepare: { mode: "preserve", validated_ok: true, errors: [], compat_changed: [], mapped_to_u1: [], could_not_carry: [], warnings: [] },
    verification: { opens_as_zip: true, members: [{ name: "a", sha256: HASH }, { name: "b", sha256: HASH }],
      comparison: { preserved: ["3D/3dmodel.model"], modified: ["Metadata/project_settings.config"], dropped: ["Metadata/gone.bin"], added: ["Metadata/new.bin"] },
      settings: { removed_keys: [], changed_keys: ["layer_height"], added_key_count: 64 },
      per_face_paint: { original_triangles: 2, exported_triangles: 2, kept: true } },
    loss_notes: ["1 part(s) of the original are not in the copy: Metadata/gone.bin."],
    original: { name: "x.3mf", sha256_before: HASH, sha256_after: HASH, original_unchanged: true },
    source: BASE_SOURCE, advisory: "Advisory comparison by part name and content hash.",
  };

  it("shows the four export buckets, paint count, loss notes and the unchanged original", () => {
    const html = renderToStaticMarkup(<CreativePreparePanel result={done} />);
    expect(html).toContain("Kept identical (1)");
    expect(html).toContain("Changed (1)");
    expect(html).toContain("Dropped (1)");
    expect(html).toContain("Added (1)");
    expect(html).toContain("Metadata/gone.bin");
    expect(html).toContain("2 painted triangle(s) in the original, 2 in the copy");
    expect(html).toContain("Project settings: 0 removed, 1 changed, 64 added");
    expect(html).toContain("It is not next to the original.");
    expect(html).toContain("Original unchanged");
    expect(html).toContain("Review it in Snapmaker Orca before slicing");
  });

  it("headings use the engine totals and say 'showing N of M' when a name list is capped", () => {
    const names = Array.from({ length: 200 }, (_, i) => `Metadata/p${i}.bin`);
    const html = renderToStaticMarkup(<CreativePreparePanel result={{
      ...done,
      verification: { ...done.verification, comparison: { preserved: names, modified: [], dropped: [], added: [] },
        counts: { preserved: 250, modified: 0, dropped: 0, added: 0 },
        settings: { removed_keys: ["a"], removed_count: 300, changed_keys: [], changed_count: 0, added_key_count: 2 } },
    }} />);
    expect(html).toContain("Kept identical (250)");
    expect(html).toContain("showing 200 of 250");
    expect(html).not.toContain("showing 0 of");
    expect(html).toContain("Project settings: 300 removed, 0 changed, 2 added");
  });

  it("names the saved location with a label only, never a folder path", () => {
    const html = renderToStaticMarkup(<CreativePreparePanel result={{ ...done, output: { ...done.output, location: "chosen", location_label: "the folder you chose" } }} />);
    expect(html).toContain("Saved in: the folder you chose.");
    expect(html).not.toMatch(/[A-Za-z]:\\|\/Users\/|\/home\//);
  });

  it("does not claim the original is unchanged when its fingerprint moved", () => {
    const html = renderToStaticMarkup(<CreativePreparePanel result={{ ...done, original: { ...done.original, sha256_after: "b".repeat(64), original_unchanged: false } }} />);
    expect(html).not.toContain("Original unchanged");
    expect(html).toContain("differs between the two reads");
  });

  it("says when the exported file could not be re-read", () => {
    const html = renderToStaticMarkup(<ExportVerification verification={{ opens_as_zip: false, problem: "That file is not a readable 3MF archive." }} lossNotes={[]} />);
    expect(html).toContain("could not be re-read");
    expect(html).toContain("not a readable 3MF archive");
  });

  it("explains a refusal and says nothing was written", () => {
    const html = renderToStaticMarkup(<CreativePreparePanel result={{
      prepared: false, origin: { generator: "kromacut", status: "detected", candidates: ["kromacut"] }, source: BASE_SOURCE, advisory: "Advisory.",
      refusal: { kind: "prepare_refused", seen: "This file was read as Kromacut.", not_supported: "Studio's Prepare could not produce a copy it can vouch for.",
        what_to_do: ["Open the original in Snapmaker Orca to check it."], problems: ["component(s) ['2'] reference an object that no file defines"] },
    }} />);
    expect(html).toContain("No copy was written");
    expect(html).toContain("This file was read as Kromacut.");
    expect(html).toContain("can vouch for");
    expect(html).toContain("What the check found");
    expect(html).toContain("reference an object that no file defines");
  });

  it("uses no readiness or guarantee wording in prepare copy", () => {
    const all = (renderToStaticMarkup(<CreativePreparePanel result={done} />) + renderToStaticMarkup(<CreativeView />)
      + renderToStaticMarkup(<CreativeFormatChooser value="auto" onChange={() => undefined} formats={[]} needsChoice />)).toLowerCase();
    for (const banned of ["ready", "coming soon", "guarantee", "100%", "print success", "printer doctor"]) expect(all).not.toContain(banned);
  });
});
