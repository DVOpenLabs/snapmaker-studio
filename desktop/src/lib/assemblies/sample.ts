/** A made-up six-tile assembly for trying the page. Every name, id and figure is invented. */
export const SAMPLE_ASSEMBLY = {
  name: "Harbour diorama (sample)",
  parts: [
    { part_id: "quay", name: "Quay" },
    { part_id: "road", name: "Road" },
    { part_id: "bridge", name: "Bridge" },
    { part_id: "lighthouse", name: "Lighthouse" },
    { part_id: "harbour", name: "Harbour" },
    { part_id: "beach", name: "Beach" },
    { part_id: "pier", name: "Pier" },
  ],
  bindings: {
    road: { provider_instance_id: "sample", provider_spool_id: "road-1" },
    water: { provider_instance_id: "sample", provider_spool_id: "water-1" },
  },
  attribution: [{ item: "Harbour tile set", author: "Example Maker", license: "CC BY 4.0" }],
  tiles: [
    { tile_id: "t1", name: "Tile 1", plate: 1, part_id: "quay", scale: 100, roles: { road: "slot:0", water: "slot:1" }, usage: { "slot:0": 40, "slot:1": 25 } },
    { tile_id: "t2", name: "Tile 2", plate: 1, part_id: "road", scale: 100, roles: { road: "slot:0", water: "slot:1" }, usage: { "slot:0": 40, "slot:1": 25 } },
    { tile_id: "t3", name: "Tile 3", plate: 2, part_id: "bridge", scale: 100, roles: { road: "slot:1", water: "slot:0" }, usage: { "slot:0": 25, "slot:1": 40 } },
    { tile_id: "t4", name: "Tile 4", plate: 2, part_id: "lighthouse", scale: 100, roles: { road: "slot:0", water: "slot:1" }, usage: { "slot:0": 40, "slot:1": 25 } },
    { tile_id: "t5", name: "Tile 5", plate: 3, part_id: "harbour", scale: 100, roles: { road: "slot:0", water: "slot:1" }, usage: { "slot:0": 40, "slot:1": null } },
    { tile_id: "t6", name: "Tile 6", plate: 3, part_id: "beach", scale: 98, roles: { road: "slot:0", water: "slot:1" }, usage: { "slot:0": 40, "slot:1": 25 } },
  ],
};

/** Sample spool readings, dated now so they are fresh when loaded. The road spool is deliberately short. */
export function sampleSupply(nowSeconds: number) {
  return [
    { spool: { provider_instance_id: "sample", provider_spool_id: "road-1" }, remaining_g: 150, observed_at: nowSeconds, ttl_s: 3600 },
    { spool: { provider_instance_id: "sample", provider_spool_id: "water-1" }, remaining_g: 300, observed_at: nowSeconds, ttl_s: 3600 },
  ];
}
