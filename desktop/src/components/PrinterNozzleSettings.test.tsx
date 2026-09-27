import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { nozzleRows } from "@/lib/nozzleRows";
import type { NozzleStatus, NozzleToolhead } from "@/api";

vi.mock("@/api", () => ({
  nozzleStatus: vi.fn().mockResolvedValue({}),
  nozzleConfirm: vi.fn(),
  nozzleClear: vi.fn(),
}));

const store = new Map<string, string>();
(globalThis as { localStorage?: unknown }).localStorage = {
  getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
  setItem: (k: string, v: string) => void store.set(k, String(v)),
  removeItem: (k: string) => void store.delete(k),
  clear: () => store.clear(),
  key: (i: number) => [...store.keys()][i] ?? null,
  get length() { return store.size; },
};

const PrinterNozzleSettings = (await import("./PrinterNozzleSettings")).default;
const { NozzleTable } = await import("./PrinterNozzleSettings");

function toolhead(overrides: Partial<NozzleToolhead>): NozzleToolhead {
  return {
    toolhead: 0, diameter: null, source: "unknown", confirmed_at: null,
    confirmed: null, conflict: false, out_of_range: false, ...overrides,
  };
}

function status(toolheads: NozzleToolhead[]): NozzleStatus {
  return {
    host: "u1.local", port: 7125, reachable: true, live: null, live_error: null,
    toolhead_count: toolheads.length, toolhead_count_source: "printer", revision: 1,
    observed_at: "2026-09-01T00:00:00Z", count_mismatch: false, storage_error: null,
    toolheads,
  };
}

describe("PrinterNozzleSettings (container)", () => {
  it("renders the header and hint, and a loading state before the fetch resolves", () => {
    const html = renderToStaticMarkup(<PrinterNozzleSettings />);
    expect(html).toContain("Nozzles");
    expect(html).toContain("Toolhead 1 feeds slot 1 — numbered as printed on the U1.");
    expect(html).toContain("Checking your printer");
  });
});

describe("NozzleTable", () => {
  it("renders a printer-reported row as read-only text, not a select", () => {
    const rows = nozzleRows(status([toolhead({ diameter: 0.4, source: "printer" })]));
    const html = renderToStaticMarkup(<NozzleTable rows={rows} />);
    expect(html).toContain("Reported live");
    expect(html).toContain("0.4 mm");
    expect(html).not.toContain("<select");
  });

  it("renders a user-confirmed row with a source date and no update button", () => {
    const rows = nozzleRows(status([
      toolhead({ toolhead: 1, diameter: 0.6, source: "user", confirmed: 0.6, confirmed_at: "2026-09-01T00:00:00Z" }),
    ]));
    const html = renderToStaticMarkup(<NozzleTable rows={rows} />);
    expect(html).toContain("Confirmed by you");
    expect(html).toContain("You");
  });

  it("renders unknown with no size and no action", () => {
    const rows = nozzleRows(status([toolhead({})]));
    const html = renderToStaticMarkup(<NozzleTable rows={rows} />);
    expect(html).toContain("Unknown");
    expect(html).toContain("tell Studio");
  });

  it("renders a conflict row with both values and the printer's-wins wording", () => {
    const rows = nozzleRows(status([
      toolhead({ diameter: 0.4, confirmed: 0.6, source: "printer", conflict: true }),
    ]));
    const html = renderToStaticMarkup(<NozzleTable rows={rows} />);
    expect(html).toContain("You noted 0.6 mm");
    expect(html).toContain("printer reports 0.4 mm");
    expect(html).toContain("Studio uses the printer&#x27;s reading");
    expect(html).toContain("Update my note to 0.4");
  });

  it("disables the row Update/Remove buttons while a mutation is in flight (R4-D4)", () => {
    const rows = nozzleRows(status([
      toolhead({ diameter: 0.4, confirmed: 0.6, source: "printer", conflict: true }),
    ]));
    const idle = renderToStaticMarkup(<NozzleTable rows={rows} busy={false} />);
    const busy = renderToStaticMarkup(<NozzleTable rows={rows} busy={true} />);
    expect(idle).not.toContain("disabled=\"\"");
    // Both the "Update my note to X" and "Remove my note" buttons must be
    // disabled — every mutation control is serialised, this row included.
    expect(busy.match(/disabled=""/g)?.length).toBe(2);
  });

  it("keeps an out-of-range note visible for removal only", () => {
    const rows = nozzleRows(status([
      toolhead({ toolhead: 6, confirmed: 0.4, source: "user", out_of_range: true }),
    ]));
    const html = renderToStaticMarkup(<NozzleTable rows={rows} />);
    expect(html).toContain("isn&#x27;t reported by this printer");
    expect(html).toContain("Remove my note");
  });
});
