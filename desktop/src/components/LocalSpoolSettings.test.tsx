import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { LocalSpoolRow } from "@/api";

vi.mock("@/api", () => ({
  localSpoolsList: vi.fn().mockResolvedValue({ rows: [] }),
  localSpoolsSave: vi.fn(),
  localSpoolsDelete: vi.fn(),
  localSpoolsMarkUsed: vi.fn(),
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

const LocalSpoolSettings = (await import("./LocalSpoolSettings")).default;
const { SpoolRowsList } = await import("./LocalSpoolSettings");

function row(overrides: Partial<LocalSpoolRow>): LocalSpoolRow {
  return {
    id: 1, host_as_stored: "u1.local", slot: 0, material: "PLA", subtype: null,
    color: null, vendor: null, starting_g: null, remaining_g: null,
    remaining_quality: "unknown", remaining_as_of: null, notes: null,
    updated_at: "2026-09-01T00:00:00Z", alias_conflict: false, ...overrides,
  };
}

describe("LocalSpoolSettings (container)", () => {
  it("renders the always-visible header and copy before the fetch resolves", () => {
    const html = renderToStaticMarkup(<LocalSpoolSettings />);
    expect(html).toContain("Your spool notes");
    expect(html).toContain("Studio uses a note only for what the printer");
  });

  it("shows a loading state before any data has arrived", () => {
    const html = renderToStaticMarkup(<LocalSpoolSettings />);
    expect(html).toContain("Loading your notes");
  });
});

describe("SpoolRowsList", () => {
  it("renders the empty state's 'Add a note' affordance for every slot", () => {
    const html = renderToStaticMarkup(
      <SpoolRowsList rows={[]} busy={false} onEdit={vi.fn()} onRemove={vi.fn()} onAdd={vi.fn()} />,
    );
    expect(html).toContain("Slot 1");
    expect(html).toContain("Slot 4");
    expect(html).toContain("Add a note");
  });

  it("shows a spool row with its quality label (D1: entered-by-you, not estimated)", () => {
    // A directly typed-in weight is "entered by you"; "estimated from what you
    // recorded" belongs to a "derived" figure (worked out from a mark-used
    // entry) — this test previously locked the two mappings swapped.
    const html = renderToStaticMarkup(
      <SpoolRowsList
        rows={[row({ slot: 1, material: "PETG", remaining_g: 320, remaining_quality: "user_confirmed" })]}
        busy={false} onEdit={vi.fn()} onRemove={vi.fn()} onAdd={vi.fn()}
      />,
    );
    expect(html).toContain("Slot 2");
    expect(html).toContain("PETG");
    expect(html).toContain("320 g · entered by you");
  });

  it("shows a derived weight (from 'Record filament used') as estimated, with its date", () => {
    const html = renderToStaticMarkup(
      <SpoolRowsList
        rows={[row({
          slot: 2, material: "PLA", remaining_g: 280, remaining_quality: "derived",
          remaining_as_of: "2026-09-12T00:00:00Z",
        })]}
        busy={false} onEdit={vi.fn()} onRemove={vi.fn()} onAdd={vi.fn()}
      />,
    );
    expect(html).toContain("280 g · estimated from what you recorded ·");
  });

  it("tolerates a legacy row with no material recorded (D8)", () => {
    const html = renderToStaticMarkup(
      <SpoolRowsList rows={[row({ material: null, color: "#112233" })]} busy={false} onEdit={vi.fn()} onRemove={vi.fn()} onAdd={vi.fn()} />,
    );
    expect(html).toContain("(no material recorded)");
  });

  it("shows 'no weight recorded' when nothing was entered", () => {
    const html = renderToStaticMarkup(
      <SpoolRowsList rows={[row({})]} busy={false} onEdit={vi.fn()} onRemove={vi.fn()} onAdd={vi.fn()} />,
    );
    expect(html).toContain("no weight recorded");
  });

  it("renders an alias conflict as two removable rows, never merged", () => {
    const html = renderToStaticMarkup(
      <SpoolRowsList
        rows={[
          row({ id: 1, slot: 2, alias_conflict: true }),
          row({ id: 2, slot: 2, alias_conflict: true }),
        ]}
        busy={false} onEdit={vi.fn()} onRemove={vi.fn()} onAdd={vi.fn()}
      />,
    );
    expect(html).toContain("Two notes exist for slot 3 — remove one");
    const removeCount = (html.match(/Remove/g) ?? []).length;
    expect(removeCount).toBeGreaterThanOrEqual(2);
  });
});
