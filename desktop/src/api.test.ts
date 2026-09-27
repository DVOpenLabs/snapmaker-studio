import { describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4312, token: "test" }) }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

import { A4_3_MESSAGES, errorCodeMessage, nozzleStatus } from "./api";

// R2-D3: "a test that each A4.3 error code maps to its shown message" — the
// literal texts here are the frozen error map from the v1.2 plan (A4.3); a
// mismatch here means the desktop's fallback copy has drifted from what the
// backend actually promises to send.
describe("A4_3_MESSAGES / errorCodeMessage (R2-D3)", () => {
  const expected: Record<string, string> = {
    invalid_host: "That printer address isn't valid.",
    invalid_slot: "That slot number isn't valid.",
    invalid_color: "Colour must be a hex value like #1A2B3C, or empty.",
    invalid_weight: "Weight must be between 0 and 10000 grams.",
    invalid_diameters: "Nozzle sizes must be between 0 and 2 mm, one per toolhead, up to 8.",
    invalid_request: "That request isn't valid.",
    no_spool_note: "There is no note with a remaining weight for that slot.",
    no_such_note: "That note no longer exists.",
    stale: "Nozzle notes changed elsewhere. Reload and try again.",
    duplicate_notes: "Two notes exist for this slot. Remove one first.",
    storage_unavailable: "Studio couldn't read or save its local data.",
  };

  for (const [code, message] of Object.entries(expected)) {
    it(`maps "${code}" to its exact A4.3 text`, () => {
      expect(errorCodeMessage(code)).toBe(message);
      expect(A4_3_MESSAGES[code]).toBe(message);
    });
  }

  it("returns undefined for an unrecognised code rather than inventing text", () => {
    expect(errorCodeMessage("something_new")).toBeUndefined();
  });
});

describe("nozzleStatus probe parameter (R2-D5)", () => {
  it("omits (or falses) probe by default so a plain status call stays a plain call", async () => {
    vi.stubGlobal("location", { search: "" });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ toolheads: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await nozzleStatus("u1.local", 7125);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.probe).toBeFalsy();
  });

  it("sends probe: true for the second-phase live check", async () => {
    vi.stubGlobal("location", { search: "" });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ toolheads: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await nozzleStatus("u1.local", 7125, true);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.probe).toBe(true);
  });
});
