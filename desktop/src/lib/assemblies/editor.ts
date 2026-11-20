import type { SpoolRef } from "./types";

export type TileInput = { tile_id: string; name: string; plate?: string | null; scale?: number | null; roles: Record<string, string>; usage: Record<string, number | null>; usage_source?: string; attribution?: Record<string, string | null>; library?: { project_id: number; sha256: string | null }; [key: string]: unknown };
export type AssemblyDocument = { name: string; tiles: TileInput[]; bindings: Record<string, SpoolRef>; [key: string]: unknown };
export type Supply = { spool: SpoolRef; remaining_g: number | null; observed_at: number | string | null; ttl_s: number | null; historical?: boolean };
const obj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

export function decodeDocument(raw: unknown): AssemblyDocument {
  if (!obj(raw) || typeof raw.name !== "string" || !Array.isArray(raw.tiles) || raw.tiles.length > 64 || !obj(raw.bindings ?? {})) throw new Error("An assembly needs a name, up to 64 tiles and a bindings object.");
  const seen = new Set<string>();
  const tiles = raw.tiles.map(value => {
    if (!obj(value) || typeof value.tile_id !== "string" || typeof value.name !== "string" || seen.has(value.tile_id) || !obj(value.roles ?? {}) || !obj(value.usage ?? {})) throw new Error("Each tile needs a unique ID, name, roles and usage objects.");
    if (value.slot_usage || value.gcode_facts) throw new Error("Use file import to read sliced usage before editing the assembly.");
    if (value.plate != null && typeof value.plate !== "string" && typeof value.plate !== "number") throw new Error("Tile plate must be text or a number.");
    if (value.scale != null && (typeof value.scale !== "number" || !Number.isFinite(value.scale))) throw new Error("Tile scale must be a finite number.");
    if (value.usage_source != null && typeof value.usage_source !== "string") throw new Error("Invalid usage source.");
    if (value.attribution != null && (!obj(value.attribution) || Object.values(value.attribution).some(v => v !== null && typeof v !== "string"))) throw new Error("Attribution values must be text.");
    seen.add(value.tile_id);
    const roles = value.roles ?? {};
    const usage = value.usage ?? {};
    if (Object.keys(roles).length > 32 || Object.keys(usage).length > 64 || Object.values(roles).some(v => typeof v !== "string" || !/^slot:(?:[0-9]|[1-5][0-9]|6[0-3])$/.test(v)) || Object.entries(usage).some(([k, v]) => !/^slot:(?:[0-9]|[1-5][0-9]|6[0-3])$/.test(k) || (v !== null && (typeof v !== "number" || !Number.isFinite(v) || v < 0 || v > 1e6)))) throw new Error("A tile has invalid slot usage.");
    return { ...value, roles, usage } as TileInput;
  });
  const bindings = raw.bindings ?? {};
  for (const ref of Object.values(bindings)) if (!obj(ref) || typeof ref.provider_instance_id !== "string" || typeof ref.provider_spool_id !== "string") throw new Error("Bindings need provider instance and spool IDs.");
  return { ...raw, tiles, bindings } as AssemblyDocument;
}

export function decodeSupply(raw: unknown): Supply[] {
  if (!Array.isArray(raw) || raw.length > 64) throw new Error("Supply must be a list of at most 64 observations.");
  for (const item of raw) {
    if (!obj(item) || !obj(item.spool) || typeof item.spool.provider_instance_id !== "string" || typeof item.spool.provider_spool_id !== "string" || (item.remaining_g != null && (typeof item.remaining_g !== "number" || !Number.isFinite(item.remaining_g) || item.remaining_g < 0))) throw new Error("A spool observation has an invalid identity or weight.");
  }
  return raw as Supply[];
}

export function slotRows(tile: TileInput) {
  const slots = [...new Set([...Object.values(tile.roles), ...Object.keys(tile.usage)])].sort((a, b) => Number(a.split(":")[1]) - Number(b.split(":")[1]));
  return slots.map(slot => ({ slot, role: Object.keys(tile.roles).filter(role => tile.roles[role] === slot).join(" / "), grams: tile.usage[slot] ?? null }));
}

export function updateSlot(doc: AssemblyDocument, index: number, slot: string, values: { role?: string; grams?: string }): AssemblyDocument {
  const tile = doc.tiles[index];
  const roles = { ...tile.roles };
  const previous = Object.keys(roles).filter(key => roles[key] === slot);
  if (values.role !== undefined) {
    if (previous.length > 1) throw new Error("This slot has multiple roles. Resolve it in Advanced JSON first.");
    if (values.role && !/^[A-Za-z0-9_][A-Za-z0-9_ \-]{0,39}$/.test(values.role)) throw new Error("Use up to 40 letters, digits, spaces, dashes or underscores for a role.");
    if (values.role && roles[values.role] !== undefined && roles[values.role] !== slot) throw new Error("That role already names another slot in this tile.");
    previous.forEach(key => delete roles[key]);
    if (values.role) roles[values.role] = slot;
  }
  const usage = { ...tile.usage };
  if (values.grams !== undefined) {
    const number = values.grams === "" ? null : Number(values.grams);
    if (number !== null && (!Number.isFinite(number) || number < 0 || number > 1e6)) throw new Error("Required grams must be from 0 to 1000000, or blank for unknown.");
    usage[slot] = number;
  }
  const tiles = doc.tiles.map((t, i) => i === index ? { ...t, roles, usage, ...(values.grams !== undefined ? { usage_source: "declared", attribution: { ...t.attribution, usage_origin: "user-declared" } } : {}) } : t);
  const referenced = new Set(tiles.flatMap(t => Object.keys(t.roles)));
  return { ...doc, tiles, bindings: Object.fromEntries(Object.entries(doc.bindings).filter(([role]) => referenced.has(role))) };
}

export function appendTiles(doc: AssemblyDocument, imported: TileInput[]): AssemblyDocument {
  if (doc.tiles.length + imported.length > 64) throw new Error("An assembly can contain at most 64 tiles.");
  // An import is an independent source. Share roles only within its own plates,
  // never with the existing assembly simply because their labels happen to match.
  const usedRoles = new Set([...doc.tiles.flatMap(t => Object.keys(t.roles)), ...Object.keys(doc.bindings)]);
  const renamed = new Map<string, string>();
  for (const role of new Set(imported.flatMap(t => Object.keys(t.roles)))) {
    let next = role, counter = 2;
    while (usedRoles.has(next)) {
      const suffix = ` import ${counter++}`;
      next = role.slice(0, 40 - suffix.length) + suffix;
    }
    renamed.set(role, next); usedRoles.add(next);
  }
  const ids = new Set(doc.tiles.map(t => t.tile_id));
  const tiles = imported.map(tile => {
    let id = tile.tile_id; let counter = 2;
    while (ids.has(id)) { const suffix = `-${counter++}`; id = tile.tile_id.slice(0, 64 - suffix.length) + suffix; }
    ids.add(id);
    const roles = Object.fromEntries(Object.entries(tile.roles).map(([role, slot]) => [renamed.get(role)!, slot]));
    return { ...tile, tile_id: id, roles };
  });
  return { ...doc, tiles: [...doc.tiles, ...tiles] };
}
