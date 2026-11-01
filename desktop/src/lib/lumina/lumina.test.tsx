import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import LuminaView, { LuminaFields } from "./LuminaView";
import { LuminaResultCard, LuminaStatusNote } from "./LuminaResultCard";
import { buildGenerateBody, type LuminaForm, type LuminaFormat, type LuminaGenerateResponse } from "./luminaApi";
import luminaRoute from "@/routes/ext/lumina.route";
import luminaMeta from "@/routes/ext/lumina.meta";

const HASH = "b".repeat(64);
const FORMATS: LuminaFormat[] = [
  { kind: "3mf", meaning: "A 3MF model file returned by the service.", evidence: "mock-service-tested" },
  { kind: "png", meaning: "A PNG preview image returned by the service.", evidence: "mock-service-tested" },
  { kind: "glb", meaning: "A binary glTF (GLB) preview model returned by the service.", evidence: "mock-service-tested" },
];
const EMPTY: LuminaForm = { serviceUrl: "", imagePath: "", lutName: "", format: "" };
const noop = () => undefined;

function fields(form: LuminaForm, over: Partial<{ formats: LuminaFormat[]; formatsError: string | null; busy: boolean }> = {}) {
  return renderToStaticMarkup(
    <LuminaFields form={form} formats={over.formats ?? FORMATS} formatsError={over.formatsError ?? null}
      busy={over.busy ?? false} onChange={noop} onCheck={noop} onGenerate={noop} />,
  );
}

const RESULT: LuminaGenerateResponse = {
  generated: true, file_name: "lumina-abc123.png", sha256: HASH, size_bytes: 42, kind: "png",
  generated_by: "a user-configured local Lumina-compatible service (not verified)",
  location_label: "Studio's lumina-output folder",
  advisory: "Studio did not watch this file being made.",
  progress: "unknown", cancel: "unknown", evidence: "mock-service-tested",
};

describe("lumina route wiring", () => {
  it("route default export has the { path, Component } shape and meta agrees", () => {
    expect(Object.keys(luminaRoute).sort()).toEqual(["Component", "path"]);
    expect(typeof luminaRoute.Component).toBe("function");
    expect(luminaRoute.path).toBe("/lumina");
    expect(luminaMeta.path).toBe(luminaRoute.path);
    expect(luminaMeta.group).toBe("Studio+");
  });
});

describe("buildGenerateBody", () => {
  const good: LuminaForm = { serviceUrl: " http://192.168.1.20:8000 ", imagePath: " a.png ", lutName: " Default ", format: "png" };

  it("trims fields and sends the chosen format", () => {
    expect(buildGenerateBody(good, FORMATS)).toEqual({
      service_url: "http://192.168.1.20:8000", image_path: "a.png", lut_name: "Default", format: "png",
    });
  });

  it("includes out_dir only when typed", () => {
    expect(buildGenerateBody({ ...good, outDir: "  " }, FORMATS)).not.toHaveProperty("out_dir");
    expect(buildGenerateBody({ ...good, outDir: " D:/out " }, FORMATS).out_dir).toBe("D:/out");
  });

  it("never infers a format: empty or unlisted is refused and names the list", () => {
    for (const format of ["", "stl", "PNG"]) {
      expect(() => buildGenerateBody({ ...good, format }, FORMATS)).toThrow(/3mf, png, glb/);
    }
  });

  it("refuses missing address, image or LUT", () => {
    expect(() => buildGenerateBody({ ...good, serviceUrl: " " }, FORMATS)).toThrow(/address/);
    expect(() => buildGenerateBody({ ...good, imagePath: "" }, FORMATS)).toThrow(/image/);
    expect(() => buildGenerateBody({ ...good, lutName: "" }, FORMATS)).toThrow(/LUT/);
  });
});

describe("LuminaFields", () => {
  it("starts empty with no preselected format and Generate disabled", () => {
    const html = fields(EMPTY);
    expect(html).toContain("Choose a format");
    expect(html).toContain("Studio does not guess the format");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Generate<\/button>/);
    expect(html).not.toMatch(/<option[^>]*selected[^>]*>(3mf|png|glb)</);
    for (const f of FORMATS) expect(html).toContain(`>${f.kind}</option>`);
  });

  it("explains the chosen format and enables Generate when complete", () => {
    const html = fields({ serviceUrl: "http://127.0.0.1:8000", imagePath: "a.png", lutName: "Default", format: "glb" });
    expect(html).toContain("A binary glTF (GLB) preview model returned by the service.");
    expect(html).toContain("Tested against: mock-service-tested.");
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Generate<\/button>/);
  });

  it("shows a format-list failure plainly and disables the selector", () => {
    const html = fields(EMPTY, { formats: [], formatsError: "Lumina formats failed (500)" });
    expect(html).toContain("Lumina formats failed (500)");
    expect(html).toMatch(/<select[^>]*disabled=""/);
  });
});

describe("LuminaResultCard and LuminaStatusNote", () => {
  it("shows name, hash, size, kind, label and the advisory without any folder path", () => {
    const html = renderToStaticMarkup(<LuminaResultCard result={RESULT} />);
    for (const text of ["lumina-abc123.png", HASH, "42 bytes", "Studio&#x27;s lumina-output folder", "not verified",
      "did not watch", "Your original image was not changed", "does not slice"]) {
      expect(html).toContain(text);
    }
    expect(html).not.toMatch(/[A-Za-z]:[\\/]/);
    expect(html).not.toContain("Users");
  });

  it("reports unknown status as unknown, not as failure of the image", () => {
    const html = renderToStaticMarkup(
      <LuminaStatusNote status={{ status: "unknown", code: "unsupported_version", message: "Not tested.", progress: "unknown", cancel: "unknown", evidence: "mock-service-tested" }} />,
    );
    expect(html).toContain("Unknown: Studio could not confirm this service.");
    expect(html).toContain("Not tested.");
  });

  it("ok status claims only that the identity check was answered", () => {
    const html = renderToStaticMarkup(
      <LuminaStatusNote status={{ status: "ok", api_version: "2.0", can_generate: true, note: "That is not proof of anything else.", progress: "unknown", cancel: "unknown", evidence: "mock-service-tested" }} />,
    );
    expect(html).toContain("answered Studio&#x27;s identity check (API version 2.0)");
    expect(html).toContain("not proof");
  });
});

describe("LuminaView first render", () => {
  it("is honest that only a synthetic stand-in was tested and offers no action beyond a local service", () => {
    const html = renderToStaticMarkup(<LuminaView />);
    expect(html).toContain("synthetic stand-in");
    expect(html).toContain("No real Lumina installation has been exercised");
    expect(html).toContain("Studio does not slice");
    expect(html).not.toMatch(/guaranteed|100%|\bready\b/i);
  });
});
