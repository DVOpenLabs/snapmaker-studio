import { describe, expect, it } from "vitest";
import type { Topology } from "./extTypes";
import {
  checkTopology, describeTopology, NO_SETUP, prepareBlockedBy, selectionFromEvaluate, selectionFromFailure, setupFor, setupStatusLine,
  outcomeIsGood, topologyOutcome, topologyOutcomeLine, topologyToSend,
} from "./prepareSetup";

/** Synthetic setups only: n heads, n logical slots, one feeder with `lanes` lanes. */
function topo(heads: number, slots: number, lanes = slots, over: Partial<Topology> = {}): Topology {
  return {
    schema_version: "topology/1", snapshot_id: "snap-synthetic", received_at: "2026-01-01T12:00:00Z", observed_at: null,
    mapping_revision: null, complete: true, evidence: [], diagnostics: [],
    heads: Array.from({ length: heads }, (_, i) => ({ id: `head:${i}`, index: i, nozzle_mm: 0.4, evidence: [] })),
    slots: Array.from({ length: slots }, (_, i) => ({ id: `slot:${i}`, index: i, binding: null, nozzle_mm: null })),
    units: [{
      id: "unit:demo", kind: "demo", source_version: null,
      lanes: Array.from({ length: lanes }, (_, i) => ({
        id: `lane:${i}`, unit_id: "unit:demo", index: i, reachable_heads: [`head:${i % heads}`], path: null, state: "unknown" as const, occupancy: null,
      })),
    }],
    bindings: Array.from({ length: Math.min(slots, lanes) }, (_, i) => ({ slot_id: `slot:${i}`, target: `lane:${i}`, evidence: [] })),
    ...over,
  };
}
const base = { token: 7, projectPath: "C:/p/a.3mf", label: "u1-demo.local:7125" };
const slot = (id: string, index: number) => ({ id, index, binding: null, nozzle_mm: null });

describe("checkTopology", () => {
  it("accepts the stock four-head setup and an eight-slot, four-head setup", () => {
    expect(checkTopology(topo(4, 4)).ok).toBe(true);
    expect(checkTopology(topo(4, 8)).ok).toBe(true);
  });

  it("accepts a host-reported setup whose bindings target toolheads directly (no feeder), as the engine does", () => {
    const t = topo(4, 8, 0, { units: [], bindings: Array.from({ length: 8 }, (_, i) => ({ slot_id: `slot:${i}`, target: `head:${i % 4}`, evidence: ["extruder_map_table"] })) } as never);
    expect(checkTopology(t).ok).toBe(true);
    expect(checkTopology({ ...t, bindings: [{ slot_id: "slot:0", target: "head:9", evidence: [] }] } as never)).toMatchObject({ ok: false, kind: "invalid" });
  });

  it("calls an incomplete or unnumbered setup unknown, not invalid, and never repairs it", () => {
    expect(checkTopology(topo(4, 8, 8, { complete: false }))).toMatchObject({ ok: false, kind: "unknown" });
    expect(checkTopology(topo(4, 4, 4, { heads: [], units: [], bindings: [] }))).toMatchObject({ ok: false, kind: "unknown" });
    expect(checkTopology(topo(4, 4, 4, { slots: [slot("a", 0), slot("b", 2)], bindings: [] })))
      .toMatchObject({ ok: false, kind: "unknown", reason: expect.stringMatching(/not numbered/) });
  });

  it.each([
    ["null", null, /no readable setup/],
    ["a different schema", { ...topo(4, 4), schema_version: "topology/9" }, /format this version does not read/],
    ["missing arrays", { ...topo(4, 4), units: undefined }, /missing/],
    ["a lane reaching an unlisted head", (() => { const t = topo(4, 4); t.units[0].lanes[0].reachable_heads = ["head:99"]; return t; })(), /not listed/],
    ["a binding to an unlisted slot", topo(4, 4, 4, { bindings: [{ slot_id: "slot:99", target: null, evidence: [] }] }), /slot that is not listed/],
    ["a binding to an unlisted lane", topo(4, 4, 4, { bindings: [{ slot_id: "slot:0", target: "lane:99", evidence: [] }] }), /lane or toolhead that is not listed/],
    ["duplicate slot ids", topo(4, 4, 4, { slots: [slot("s", 0), slot("s", 1)], bindings: [] }), /share the same id/],
  ])("calls %s invalid", (_n, raw, reason) => {
    const r = checkTopology(raw);
    expect(r).toMatchObject({ ok: false, kind: "invalid" });
    expect((r as { reason: string }).reason).toMatch(reason);
  });
});

describe("describeTopology", () => {
  it("counts what the host reported and does not call anything ready", () => {
    const s = describeTopology(topo(4, 8, 8));
    expect(s).toMatchObject({ heads: 4, slots: 8, lanes: 8, boundSlots: 8 });
    expect(s.text).toBe("4 toolheads, 8 logical slots, 8 feeder lanes; 8 of 8 slots are bound (8 to feeder lanes, 0 directly to toolheads)");
    expect(s.text).not.toMatch(/ready|will print|compatible|fits/i);
  });
  it("reports slots bound straight to a toolhead apart from feeder-lane bindings", () => {
    const t = topo(4, 8, 0, { units: [], bindings: Array.from({ length: 8 }, (_, i) => ({ slot_id: `slot:${i}`, target: `head:${i % 4}`, evidence: [] })) } as never);
    const s = describeTopology(t);
    expect(s).toMatchObject({ lanes: 0, boundSlots: 8, laneBound: 0, headBound: 8 });
    expect(s.text).toBe("4 toolheads, 8 logical slots, 0 feeder lanes; 8 of 8 slots are bound (0 to feeder lanes, 8 directly to toolheads)");
    expect(s.text).not.toMatch(/lane binding/);
  });
  it("counts unbound slots from the bindings, never assuming them", () => {
    expect(describeTopology(topo(4, 8, 4)).boundSlots).toBe(4);
    expect(describeTopology(topo(4, 8, 4)).text).toContain("4 of 8 slots");
  });
});

describe("selectionFromEvaluate", () => {
  it("is ready with the host's own topology object", () => {
    const t = topo(4, 8);
    const sel = selectionFromEvaluate(base, { report: {}, read: {}, topology: t });
    expect(sel.status).toBe("ready");
    if (sel.status === "ready") expect(sel.topology).toBe(t);
  });
  it("is unknown, with the host's reason, when no topology came back", () => {
    expect(selectionFromEvaluate(base, { report: { entries: [{ reason_text: "The host did not answer." }] }, read: { reason: "timeout" }, topology: null }))
      .toMatchObject({ status: "unknown", reason: "The host did not answer." });
    expect(selectionFromEvaluate(base, { read: { reason: "unsupported" } })).toMatchObject({ status: "unknown", reason: "unsupported" });
    expect(selectionFromEvaluate(base, {})).toMatchObject({ status: "unknown", reason: "the host did not report its setup" });
  });
  it("is invalid for a contradicting setup and unknown for an incomplete one", () => {
    expect(selectionFromEvaluate(base, { topology: { ...topo(4, 4), schema_version: "x" } }).status).toBe("invalid");
    expect(selectionFromEvaluate(base, { topology: topo(4, 4, 4, { complete: false }) }).status).toBe("unknown");
  });
  it("is failed for a failed read, keeping the reason", () => {
    expect(selectionFromFailure(base, new Error("Setup check failed (500)"))).toMatchObject({ status: "failed", reason: "Setup check failed (500)" });
    expect(selectionFromFailure(base, "x")).toMatchObject({ status: "failed", reason: "the read failed" });
  });
});

describe("what Prepare may send", () => {
  const ready = selectionFromEvaluate(base, { topology: topo(4, 8) });
  it("sends the topology only for a ready setup of the same project", () => {
    expect(topologyToSend(ready, "C:/p/a.3mf")).toBeDefined();
    expect(topologyToSend(ready, "C:/p/b.3mf")).toBeUndefined();
    expect(topologyToSend(NO_SETUP(), "C:/p/a.3mf")).toBeUndefined();
    for (const status of ["unknown", "invalid", "failed"] as const) {
      expect(topologyToSend({ status, ...base, reason: "r" }, base.projectPath)).toBeUndefined();
    }
    expect(topologyToSend({ status: "reading", ...base }, base.projectPath)).toBeUndefined();
  });
  it("pauses Prepare for a setup that cannot be used, and says how to continue", () => {
    expect(prepareBlockedBy(NO_SETUP(), "C:/p/a.3mf")).toBeNull();
    expect(prepareBlockedBy(ready, "C:/p/a.3mf")).toBeNull();
    expect(prepareBlockedBy({ status: "reading", ...base }, base.projectPath)).toMatch(/still reading/);
    const msg = prepareBlockedBy({ status: "failed", ...base, reason: "boom" }, base.projectPath)!;
    expect(msg).toContain("u1-demo.local:7125");
    expect(msg).toContain("boom");
    expect(msg).toMatch(/Prepare without a setup/);
  });
  it("treats a setup chosen for another project as no setup", () => {
    expect(prepareBlockedBy({ status: "failed", ...base, reason: "boom" }, "C:/p/b.3mf")).toBeNull();
    expect(setupFor({ status: "failed", ...base, reason: "x" }, "C:/p/b.3mf")).toEqual({ status: "none", token: 7 });
    expect(setupFor(ready, "C:/p/a.3mf")).toBe(ready);
  });
});

describe("setupStatusLine", () => {
  it("never claims readiness", () => {
    for (const sel of [NO_SETUP(), { status: "reading" as const, ...base }, selectionFromEvaluate(base, { topology: topo(4, 8) }),
      { status: "unknown" as const, ...base, reason: "why" }]) {
      expect(setupStatusLine(sel)).not.toMatch(/safe|guarantee|will print|100%|compatible/i);
    }
    expect(setupStatusLine(NO_SETUP())).toMatch(/stock four-toolhead/);
  });
});

describe("topologyOutcome (engine-authoritative)", () => {
  const sent = { heads: 4, slots: 8 };
  const result = (setup: object | undefined, blocked = false) => ({ blocked, settings_summary: setup === undefined ? null : { setup } });
  it("reads a Recommended-mode report as not applied and shows the engine's own reason", () => {
    const o = topologyOutcome(true, result({ state: "valid", applied: false, heads: 4, slots: 8, unbound: [],
      not_applied_reason: "U1 starter settings build stock U1 values and do not use a printer setup. Use Preserve creator settings to keep per-head values." }), sent);
    expect(o.state).toBe("unused");
    const line = topologyOutcomeLine(o)!;
    expect(line).toMatch(/did not apply it/);
    expect(line).toMatch(/U1 starter settings build stock U1 values/);
    expect(outcomeIsGood(o)).toBe(false);
  });
  it("is unknown, not used, when the engine says nothing or omits applied; used only on applied: true", () => {
    expect(topologyOutcome(true, result(undefined), sent).state).toBe("unknown");
    expect(topologyOutcome(true, result({ state: "valid", heads: 4, slots: 8, unbound: [] }), sent).state).toBe("unknown");   // older engine: no applied field
    expect(topologyOutcome(true, result({ state: "valid", applied: true, heads: 4, slots: 8, unbound: [] }), sent).state).toBe("used");
    expect(topologyOutcome(false, result({ state: "valid", applied: true }), sent).state).toBe("not_requested");
  });
  it("a blocked invalid setup never reads as success and carries the stock alternative", () => {
    const o = topologyOutcome(true, result({ state: "invalid", reasons: ["3 heads"], stock_alternative: "Prepare without a printer setup." }, true), sent);
    expect(o).toEqual({ state: "blocked", reasons: ["3 heads"], alternative: "Prepare without a printer setup." });
    expect(outcomeIsGood(o)).toBe(false);
  });
  it("a block for another reason (Project Materials guard) says nothing false about a valid setup", () => {
    const guard = { blocked: true, settings_summary: { project_materials: { guard: {} } } } as never;
    const o = topologyOutcome(true, guard, sent);
    expect(o).toEqual({ state: "not_evaluated" });
    expect(outcomeIsGood(o)).toBe(false);
    const line = topologyOutcomeLine(o)!;
    expect(line).toMatch(/stopped for another reason/);
    expect(line).not.toMatch(/could not use this printer setup/);
    expect(topologyOutcome(true, result({ state: "valid", applied: true, heads: 4, slots: 8 }, true), sent)).toEqual({ state: "not_evaluated" });
  });
  it("an engine echoing a different shape, or a non-boolean applied, is unknown, not used", () => {
    expect(topologyOutcome(true, result({ state: "valid", applied: true, heads: 3, slots: 8 }), sent).state).toBe("unknown");
    expect(topologyOutcome(true, result({ state: "valid", applied: "true", heads: 4, slots: 8 }), sent).state).toBe("unknown");
  });
  it("names unbound slots as having no reported binding", () => {
    const line = topologyOutcomeLine({ state: "used", heads: 4, slots: 8, unbound: ["slot 5"] })!;
    expect(line).toContain("no reported binding: slot 5");
  });
  it("does not double the full stop when a read failure already ends its sentence", () => {
    const sel = selectionFromFailure({ label: "host:1", projectPath: "p", token: 1 } as never, new Error("That address was refused."));
    expect(setupStatusLine(sel)).toBe("host:1: That address was refused.");
    expect(prepareBlockedBy(sel, "p")).toContain("can't be used: That address was refused. Read it again");
  });
  it("starts the engine's reason with a capital letter after the sentence it follows", () => {
    const line = topologyOutcomeLine({ state: "blocked", reasons: ["the printer setup has 3 physical heads"], alternative: null });
    expect(line).toContain("nothing was prepared. The printer setup has 3 physical heads.");
  });
});
