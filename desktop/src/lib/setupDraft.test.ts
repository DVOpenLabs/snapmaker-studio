import { expect, it } from "vitest";
import { saveSetupDraft, readSetupDraft, forgetSetupDraft } from "./setupDraft";
import { EMPTY_ACCESSORY } from "@/components/setups/AccessorySetupFields";
it("copies only explicit input fields, never keys, reports or trusted topology", () => {
  const value = { host: "synthetic.local", port: "9411", accessory: { ...EMPTY_ACCESSORY }, key: "synthetic-key", topology: { complete: true } };
  saveSetupDraft("synthetic.3mf", value);
  const draft = readSetupDraft("synthetic.3mf")!;
  expect(Object.keys(draft).sort()).toEqual(["accessory", "host", "port"]);
  draft.accessory.mapping = "changed outside store";
  expect(readSetupDraft("synthetic.3mf")!.accessory.mapping).toBe("");
  expect(readSetupDraft("another.3mf")).toBeUndefined(); forgetSetupDraft("synthetic.3mf");
});
it("bounds project history and removes old input rather than truncating oversized content", () => {
  const draft = { host: "synthetic.local", port: "9411", accessory: { ...EMPTY_ACCESSORY } };
  for (let i = 0; i < 9; i++) saveSetupDraft(`synthetic-${i}.3mf`, draft);
  expect(readSetupDraft("synthetic-0.3mf")).toBeUndefined();
  expect(saveSetupDraft("synthetic-8.3mf", { ...draft, accessory: { ...draft.accessory, snapshot: "x".repeat(256 * 1024 + 1) } })).toBe(false);
  expect(readSetupDraft("synthetic-8.3mf")).toBeUndefined();
});
