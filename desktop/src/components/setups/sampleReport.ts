import type { SetupReport } from "@/lib/setupsTypes";

/** Synthetic report for static renders and tests. Invented values only; no real device or address. */
export const SAMPLE_REPORT: SetupReport = {
  schema_version: "setup_report/1",
  advisory: "This report describes what was read. It is advisory and does not promise a print outcome.",
  inputs_revision: { revision: "sha256:sample" },
  legacy_limitation: {
    applies: true,
    reasons: ["This setup reports 8 logical slots, more than the four older screens assume."],
    text: "Older Studio screens assume four heads, and legacy preparation is not validated for this setup. Review any prepared copy in Orca before slicing.",
  },
  entries: [{
    label: "Host", status: "ok", kind: "moonraker", variant: "stock", adapter_id: "host.moonraker_stock",
    source_version: "host_bundle/1", reason: null, reason_text: null, topology: null, unknowns: ["spool"],
    counts: { physical_heads: 4, logical_slots: 8, lanes: 0, lanes_with_known_reach: 0, complete: true },
    capabilities: [
      { key: "physical_heads", label: "Physical heads", state: "available", reason: "The host reports 4 physical heads.", historical: false },
      { key: "logical_slots", label: "Logical material slots", state: "available", reason: "The host reports 8 logical material slots.", historical: false },
      { key: "slot_mapping", label: "Slot-to-head mapping", state: "unknown", reason: "The host did not say which head each slot uses. Studio does not assume slot n is head n.", historical: false },
      { key: "material_data", label: "Material data", state: "stale", reason: "Material details were reported. This was read earlier and is older than its lifetime.", historical: false },
      { key: "slot_occupancy", label: "Physical-head occupancy", state: "available", reason: "Restored from an earlier session.", historical: true },
      { key: "spool_identity", label: "Spool identity", state: "unknown", reason: "The host did not report which spool is loaded. It is not treated as cleared.", historical: false },
    ],
    observations: [],
    assignability: {
      verdict: "cannot_match", assignable: false, requested: 8, bound: { min: 4, max: 4 }, per_requirement: [], reasons: [],
      text: "This setup cannot give every requested material a head. This is advisory. At most 4 of the 8 requested materials can be matched.",
    },
  }],
};
