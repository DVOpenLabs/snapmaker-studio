import { describe, expect, it } from "vitest";
import { appendTiles, decodeDocument, decodeSupply, slotRows, updateSlot } from "./editor";
const doc = () => decodeDocument({ name: "Synthetic", bindings: {}, attribution: [{ author: "Example Maker" }], tiles: [{ tile_id: "one", name: "One", roles: { Road: "slot:0" }, usage: { "slot:0": null }, attribution: { source_sha256: "a".repeat(64) } }] });
describe("guided assembly editor", () => {
  it("keeps unknown grams distinct from zero and preserves provenance", () => {
    expect(slotRows(doc().tiles[0])[0].grams).toBeNull();
    const changed = updateSlot(doc(), 0, "slot:0", { grams: "0" });
    expect(changed.tiles[0].usage["slot:0"]).toBe(0);
    expect(changed.tiles[0].attribution?.usage_origin).toBe("user-declared");
    expect(changed.attribution).toEqual([{ author: "Example Maker" }]);
    expect(changed.tiles[0].attribution?.source_sha256).toBe("a".repeat(64));
  });
  it("renames roles without changing slot positions", () => {
    const changed = updateSlot(doc(), 0, "slot:0", { role: "Surface" });
    expect(changed.tiles[0].roles).toEqual({ Surface: "slot:0" });
  });
  it("does not silently collapse conflicting roles", () => {
    const input = doc(); input.tiles[0].roles.Water = "slot:0";
    expect(() => updateSlot(input, 0, "slot:0", { role: "New" })).toThrow(/multiple roles/);
  });
  it("gives repeated imports distinct tile identities", () => {
    expect(appendTiles(doc(), doc().tiles).tiles.map(t => t.tile_id)).toEqual(["one", "one-2"]);
  });
  it("rejects malformed input instead of crashing the guided controls", () => {
    expect(() => decodeDocument({ name: "Invalid", tiles: [{ tile_id: "x", name: "X", roles: [] }] })).toThrow();
    expect(() => decodeSupply([{}])).toThrow();
    expect(() => updateSlot(doc(), 0, "slot:0", { grams: "-2" })).toThrow();
  });
});


it("isolates each import's roles and retains sharing only inside that import", () => {
  const first=doc(); first.bindings.Road={provider_instance_id:"synthetic",provider_spool_id:"one"};
  const merged=appendTiles(first,[{...first.tiles[0],tile_id:"two"},{...first.tiles[0],tile_id:"three"}]);
  const role=Object.keys(merged.tiles[1].roles)[0];
  expect(role).not.toBe("Road");expect(Object.keys(merged.tiles[2].roles)).toEqual([role]);
  expect(merged.bindings[role]).toBeUndefined();expect(merged.bindings.Road).toEqual(first.bindings.Road);
});
it("bounds collision suffixes and removes only orphaned bindings after renaming", () => {
  const first=doc();first.tiles[0].tile_id="a".repeat(64);first.bindings.Road={provider_instance_id:"synthetic",provider_spool_id:"one"};
  expect(appendTiles(first,[first.tiles[0]]).tiles[1].tile_id.length).toBeLessThanOrEqual(64);
  expect(updateSlot(first,0,"slot:0",{role:"Other"}).bindings.Road).toBeUndefined();
});
