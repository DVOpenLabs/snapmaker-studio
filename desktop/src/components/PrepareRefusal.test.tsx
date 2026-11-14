import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4312, token: "test" }) }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

import { PrepareRefusal } from "./PrepareRefusal";
import { PrepareRefusalError, convert } from "@/api";

const PLAIN = "Studio only keeps per-object settings it has verified Snapmaker Orca reads. 1 setting(s) are not verified, on object 4: ironing_type. Open the original in Snapmaker Orca to review those settings. No prepared copy was saved, and your original file was not changed.";
const RAW = "Studio built a prepared copy it cannot vouch for and did not save it: object 4: ironing_type is not a setting Studio has proved";

describe("PrepareRefusal", () => {
  it("leads with the plain sentence and keeps the raw wording in a collapsed details element", () => {
    const html = renderToStaticMarkup(<PrepareRefusal error={new PrepareRefusalError(PLAIN, RAW)} />);
    const [main, secondary] = html.split("<details");
    expect(main).toContain("Couldn&#x27;t prepare a copy: ");
    expect(main).toContain("Open the original in Snapmaker Orca");
    expect(main).not.toContain("cannot vouch for");
    expect(main).not.toContain("UnsoundOutput");
    expect(secondary).toContain("Technical details");
    expect(secondary).toContain("cannot vouch for");
    expect(html).not.toContain("<details open");
  });

  it("shows no details area for an ordinary error", () => {
    const html = renderToStaticMarkup(<PrepareRefusal error={new Error("engine said no")} />);
    expect(html).toContain("engine said no");
    expect(html).not.toContain("<details");
  });
});

describe("convert() on a 422 refusal", () => {
  it("throws the plain message with the technical details attached, not merged", async () => {
    vi.stubGlobal("location", { search: "" });
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false, status: 422,
      json: async () => ({ error: PLAIN, refusal: "UnsoundOutput", details: RAW }),
    })));
    let caught: unknown;
    try { await convert("x.3mf"); } catch (e) { caught = e; }
    vi.unstubAllGlobals();
    expect(caught).toBeInstanceOf(PrepareRefusalError);
    expect((caught as Error).message).toBe(PLAIN);
    expect((caught as { details?: string }).details).toBe(RAW);
  });

  it("a plain failure without details stays an ordinary Error", async () => {
    vi.stubGlobal("location", { search: "" });
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 500, json: async () => ({ error: "internal error", kind: "KeyError" }) })));
    let caught: unknown;
    try { await convert("x.3mf"); } catch (e) { caught = e; }
    vi.unstubAllGlobals();
    expect(caught).not.toBeInstanceOf(PrepareRefusalError);
    expect((caught as Error).message).toBe("internal error (KeyError)");
  });
});
