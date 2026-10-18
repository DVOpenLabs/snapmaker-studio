import { describe, expect, it } from "vitest";
import type { ReceiptFact, ReceiptStep, SettingsReceipt } from "@/api";
import { stageCell, valueLines } from "@/lib/settingsReceipt";

type State = "read" | "unreadable" | "not_provided";
const step = (o: Partial<ReceiptStep>): ReceiptStep =>
  ({ from: "original", to: "sliced", from_value: null, to_value: null, status: "unchanged", detail: "", next_action: null, ...o });
const fact = (id: ReceiptFact["id"], steps: ReceiptStep[]): ReceiptFact => ({ id, label: id, status: "unchanged", steps });
const receipt = (stages: Partial<Record<"original" | "prepared" | "sliced", State>>): SettingsReceipt => ({
  schema_version: "x", scope: "project", scope_note: "", facts: [], summary: "", separate_from: "",
  stages: {
    original: { state: stages.original ?? "read" },
    prepared: { state: stages.prepared ?? "not_provided" },
    sliced: { state: stages.sliced ?? "read" },
  },
});

describe("receipt values", () => {
  it("keeps Tool 1 to Tool 4 in order, one tool per line", () => {
    expect(valueLines("nozzles", [0.4, 0.2, 0.6, 0.4])).toEqual(["Tool 1: 0.4 mm", "Tool 2: 0.2 mm", "Tool 3: 0.6 mm", "Tool 4: 0.4 mm"]);
  });

  it("words flags as On/Off and layer height in mm", () => {
    expect(valueLines("supports", true)).toEqual(["On"]);
    expect(valueLines("prime_tower", false)).toEqual(["Off"]);
    expect(valueLines("layer_height", 0.2)).toEqual(["0.2 mm"]);
  });
});

describe("receipt cells keep changed, unchanged, missing and not checked apart", () => {
  const f = fact("layer_height", [step({ from_value: 0.2, to_value: 0.16, status: "changed" })]);

  it("shows each file's own value", () => {
    const r = receipt({});
    expect(stageCell(r, f, "original")).toEqual({ kind: "value", lines: ["0.2 mm"] });
    expect(stageCell(r, f, "sliced")).toEqual({ kind: "value", lines: ["0.16 mm"] });
  });

  it("a prepared copy that was not provided is not included, not 'not stated'", () => {
    expect(stageCell(receipt({}), f, "prepared")).toEqual({ kind: "not_included" });
  });

  it("a value a read file does not state is not stated", () => {
    const missing = fact("supports", [step({ from_value: true, to_value: null, status: "missing" })]);
    expect(stageCell(receipt({}), missing, "sliced")).toEqual({ kind: "not_stated" });
    expect(stageCell(receipt({}), missing, "original")).toEqual({ kind: "value", lines: ["On"] });
  });

  it("an unreadable file, or a step that could not run, is not checked and never lends its empty values", () => {
    expect(stageCell(receipt({ sliced: "unreadable" }), f, "sliced")).toEqual({ kind: "not_checked" });
    const skipped = fact("supports", [step({ status: "not_checked" })]);
    expect(stageCell(receipt({}), skipped, "original")).toEqual({ kind: "not_checked" });
  });

  it("a receipt with no steps checks nothing", () => {
    expect(stageCell(receipt({}), fact("supports", []), "original")).toEqual({ kind: "not_checked" });
  });
});
