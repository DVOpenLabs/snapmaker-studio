import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => ({ preflight: vi.fn() }));

const store = new Map<string, string>();
(globalThis as { localStorage?: unknown }).localStorage = {
  getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
  setItem: (k: string, v: string) => void store.set(k, String(v)),
  removeItem: (k: string) => void store.delete(k),
  clear: () => store.clear(),
  key: (i: number) => [...store.keys()][i] ?? null,
  get length() { return store.size; },
};

const { PreflightCard, CheckRow } = await import("./PreflightCard");

function check(overrides: Partial<import("@/api").PreflightCheck>): import("@/api").PreflightCheck {
  return {
    id: "nozzle.match", title: "Nozzle size", result: "unknown", evidence: null,
    confidence: "informational", consequence: "Studio cannot tell what is fitted.",
    action: null, source: null, ...overrides,
  };
}

function render() {
  return renderToStaticMarkup(
    <MemoryRouter>
      <PreflightCard path="/tmp/model.stl" />
    </MemoryRouter>,
  );
}

describe("PreflightCard", () => {
  it("renders a loading state before the preflight response arrives", () => {
    const html = render();
    expect(html).toContain("Before you slice");
    expect(html).toContain("Comparing this project to your printer");
  });
});

describe("nozzle.match check row", () => {
  function renderRow(overrides: Partial<import("@/api").PreflightCheck>, printer?: Record<string, unknown>) {
    return renderToStaticMarkup(
      <MemoryRouter><ul><CheckRow check={check(overrides)} printer={printer} /></ul></MemoryRouter>,
    );
  }

  it("points to Settings when unknown with no printer reading", () => {
    const html = renderRow({ result: "unknown" });
    expect(html).toContain("Confirm your nozzle sizes in Settings");
    expect(html).toContain('href="/settings"');
  });

  it("shows the confirmation date and a change link when the user's confirmation is the source used", () => {
    const html = renderRow(
      { result: "ok" },
      { nozzle_confirmed_at: "2026-09-01T00:00:00Z", nozzle_confirmed_by: "user" },
    );
    expect(html).toContain("confirmed by you on");
    expect(html).toContain("change in Settings");
    expect(html).toContain('href="/settings"');
  });

  it("does NOT claim 'confirmed by you' when the live printer's reading was the source used (D9)", () => {
    // A stored confirmation can exist and still lose to a live reading — the
    // regression this guards against showed "confirmed by you" even then.
    const html = renderRow(
      { result: "ok" },
      { nozzle_confirmed_at: "2026-09-01T00:00:00Z", nozzle_confirmed_by: "printer" },
    );
    expect(html).not.toContain("confirmed by you");
  });

  it("renders a conflict check like any other ATTENTION check (no special-casing)", () => {
    const html = renderRow({
      id: "nozzle.confirmation_conflict", result: "attention",
      title: "Nozzle note disagrees with the printer",
      consequence: "Studio uses the printer's reading.",
    });
    expect(html).toContain("Needs attention");
    expect(html).toContain("Nozzle note disagrees with the printer");
  });

  it("says nothing extra for a non-nozzle check", () => {
    const html = renderRow({ id: "bed.size", result: "unknown" });
    expect(html).not.toContain("Confirm your nozzle sizes");
  });
});
