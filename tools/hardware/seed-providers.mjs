// Synthetic spools for the provider-against-hardware checks. Session-owned Spoolman / Bambuddy containers only.
//
// Why this file exists: Studio labels a remaining weight "tracked" only when the provider has a RECORD behind it
// (Spoolman: last_used set and used_weight > 0; Bambuddy: a weighing, or last_used with used weight). A spool that
// was merely created with an initial and a used weight is arithmetic and is labelled "derived" - correctly. The
// RC2 hardware attempt on 2026-10-24 seeded spools without a record and the "provider supplies the weight" checks
// saw "derived". The seed now writes the record through each provider's own API; the check keeps requiring "tracked".
//
import { pathToFileURL } from "node:url";

// Usage: node seed-providers.mjs <spoolmanBase> <bambuddyBase>   -> prints {"SP_AGREE":..,"SP_CONFLICT":..,"BB_AGREE":..,"BB_CONFLICT":..}

export const SPOOL = { vendor: "Snapmaker", name: "Silk", colorHex: "4DB6AC", initialG: 1000, usedG: 100 };

async function send(fetchFn, method, url, body) {
  const res = await fetchFn(url, {
    method, headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${new URL(url).pathname} -> ${res.status} ${text.slice(0, 160)}`);
  return text ? JSON.parse(text) : {};
}

/** Spoolman: create the spool, then record consumption through /use so last_used is written. */
export async function seedSpoolman(base, fetchFn = fetch) {
  const api = `${base.replace(/\/+$/, "")}/api/v1`;
  const vendor = await send(fetchFn, "POST", `${api}/vendor`, { name: SPOOL.vendor });
  const ids = {};
  for (const [key, material, density] of [["agree", "PLA", 1.24], ["conflict", "PETG", 1.27]]) {
    const filament = await send(fetchFn, "POST", `${api}/filament`, {
      name: SPOOL.name, vendor_id: vendor.id, material, density, diameter: 1.75,
      weight: SPOOL.initialG, color_hex: SPOOL.colorHex,
    });
    const spool = await send(fetchFn, "POST", `${api}/spool`, { filament_id: filament.id, initial_weight: SPOOL.initialG });
    await send(fetchFn, "PUT", `${api}/spool/${spool.id}/use`, { use_weight: SPOOL.usedG });
    ids[key] = spool.id;
  }
  return ids;
}

/** Bambuddy: a recorded weighing (last_scale_weight + last_weighed_at) is the record its adapter requires. */
export async function seedBambuddy(base, fetchFn = fetch, now = () => new Date()) {
  const api = `${base.replace(/\/+$/, "")}/api/v1`;
  const ids = {};
  for (const [key, material] of [["agree", "PLA"], ["conflict", "PETG"]]) {
    const spool = await send(fetchFn, "POST", `${api}/inventory/spools`, {
      material, subtype: SPOOL.name, color_name: "Teal", rgba: `${SPOOL.colorHex}FF`, brand: SPOOL.vendor,
      label_weight: SPOOL.initialG, weight_used: SPOOL.usedG,
      last_scale_weight: SPOOL.initialG - SPOOL.usedG, last_weighed_at: now().toISOString().replace("Z", ""),
    });
    ids[key] = spool.id;
  }
  return ids;
}

export async function seedAll(spoolmanBase, bambuddyBase, fetchFn = fetch) {
  const sp = await seedSpoolman(spoolmanBase, fetchFn);
  const bb = await seedBambuddy(bambuddyBase, fetchFn);
  return { SP_AGREE: sp.agree, SP_CONFLICT: sp.conflict, BB_AGREE: bb.agree, BB_CONFLICT: bb.conflict };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [sp, bb] = process.argv.slice(2);
  if (!sp || !bb) { console.error("usage: node seed-providers.mjs <spoolmanBase> <bambuddyBase>"); process.exit(2); }
  console.log(JSON.stringify(await seedAll(sp, bb)));
}
