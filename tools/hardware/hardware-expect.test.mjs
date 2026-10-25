// node --test tools/hardware/hardware-expect.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { bedFitEvidenceOk, bedFitFindingOk, providerWeightOk, nozzleCardPresent, g, U1_PRINTABLE_MM } from "./hardware-expect.mjs";
import { SPOOL, seedSpoolman, seedBambuddy } from "./seed-providers.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const profile = JSON.parse(readFileSync(join(root, "backend/snapstudio_core/data/printer_profiles/snapmaker_u1.json"), "utf8"));
const plate = profile.build_volume_mm;
const travel = profile.observed_axis_range_mm;
const real = "1 object(s) fall outside this printer's 270 × 270 mm printable area"; // recorded from the RC2 attempt

test("the pinned printable area equals the shipped U1 profile", () => {
  assert.deepEqual({ x: U1_PRINTABLE_MM.x, y: U1_PRINTABLE_MM.y }, { x: plate.x, y: plate.y });
  assert.equal(g(plate.x), "270");
  assert.equal(g(plate.y), "270");
  assert.equal(g(travel.x), "271");
});
test("the real RC2 evidence passes", () => assert.ok(bedFitEvidenceOk(real, plate, travel)));
test("the old v1.6.0 phrasing (axis travel presented as the area) is refused", () => {
  assert.ok(!bedFitEvidenceOk("1 object(s) fall outside this printer's 271.0 × 335.0 × 281.0 mm area", plate, travel));
});
test("a wrong printable area is refused", () => {
  assert.ok(!bedFitEvidenceOk("1 object(s) fall outside this printer's 250 × 250 mm printable area", plate, travel));
});
test("travel presented as the printable area is refused even next to the right area", () => {
  assert.ok(!bedFitEvidenceOk(`${real}; 335 × 281 mm printable area`, plate, travel));
});
test("a fit with no off-plate object is refused: the showcase object is deliberately off the plate", () => {
  assert.ok(!bedFitEvidenceOk("Every object sits inside this printer's 270 × 270 mm printable area", plate, travel));
  assert.ok(!bedFitEvidenceOk("0 object(s) fall outside this printer's 270 × 270 mm printable area", plate, travel));
  assert.ok(!bedFitEvidenceOk("", plate, travel));
  assert.ok(!bedFitEvidenceOk(undefined, plate, travel));
});

test("the Nozzles card is detected, and its not-set-up placeholder is not", () => {
  assert.ok(nozzleCardPresent("Settings\nNozzles · for 192.0.2.1\nToolhead 1"));
  assert.ok(!nozzleCardPresent("Nozzles\nSet up your printer above to confirm which nozzles are fitted."));
  assert.ok(!nozzleCardPresent("Home"));
});

// The UI contract the harness relies on, read from the source that built the candidate: a stale locator is how the
// RC2 attempt failed, so each string it drives must still exist in the desktop source.
test("the desktop source still carries every UI string the nozzle checks drive", () => {
  const read = (p) => readFileSync(join(root, p), "utf8");
  const address = read("desktop/src/components/PrinterAddress.tsx");
  assert.match(address, /aria-label="Printer network name or IP"/);
  assert.match(address, /Save and connect/);
  assert.match(address, /role="status"/);
  assert.ok(address.includes("Set up: " + "${saved}"));
  assert.match(address, /e\.key === "Enter"/);
  assert.match(read("desktop/src/routes/Settings.tsx"), /isPrinterSetUp\(host\) \? <PrinterNozzleSettings/);
  assert.match(read("desktop/src/components/PrinterNozzleSettings.tsx"), /Nozzles · for \{canonical\}/);
  assert.match(read("desktop/src/components/PrinterNozzleSettings.tsx"), /Nozzle size for toolhead/);
  assert.match(read("desktop/src/lib/nozzleRows.ts"), /Remove my note/);
});

// The seed must create the record Studio's adapters demand for "tracked"; a spool that was only created with an
// initial and a used weight is "derived". Fake servers stand in for the providers here; the real adapters were run
// against real containers when the seed was written (see the harness commit message).
function fakeFetch(log) {
  let id = 0;
  return async (url, init) => {
    const path = new URL(url).pathname;
    log.push({ method: init.method, path, body: init.body ? JSON.parse(init.body) : undefined });
    return { ok: true, status: 200, text: async () => JSON.stringify({ id: ++id }) };
  };
}
test("Spoolman seed records consumption for both spools", async () => {
  const log = [];
  const ids = await seedSpoolman("http://x", fakeFetch(log));
  assert.ok(ids.agree && ids.conflict && ids.agree !== ids.conflict);
  const uses = log.filter((c) => c.method === "PUT" && /\/use$/.test(c.path));
  assert.equal(uses.length, 2);
  assert.ok(uses.every((c) => c.body.use_weight === SPOOL.usedG));
  assert.deepEqual(log.filter((c) => /\/filament$/.test(c.path)).map((c) => c.body.material), ["PLA", "PETG"]);
});
test("Bambuddy seed records a weighing for both spools", async () => {
  const log = [];
  await seedBambuddy("http://x", fakeFetch(log), () => new Date("2026-10-25T00:00:00Z"));
  const posts = log.filter((c) => c.method === "POST");
  assert.equal(posts.length, 2);
  for (const c of posts) {
    assert.equal(c.body.last_scale_weight, SPOOL.initialG - SPOOL.usedG);
    assert.equal(c.body.last_weighed_at, "2026-10-25T00:00:00.000");
  }
  assert.deepEqual(posts.map((c) => c.body.material), ["PLA", "PETG"]);
});

test("the whole bed.fit finding must be an attention/confirmed verdict, not just right-looking text", () => {
  const ok = { result: "attention", confidence: "confirmed", evidence: real };
  assert.ok(bedFitFindingOk(ok, plate, travel));
  assert.ok(!bedFitFindingOk({ ...ok, result: "ok" }, plate, travel));
  assert.ok(!bedFitFindingOk({ ...ok, confidence: "informational" }, plate, travel));
  assert.ok(!bedFitFindingOk(undefined, plate, travel));
});
test("the off-plate count is the showcase's exactly one, not 'at least one'", () => {
  assert.ok(!bedFitEvidenceOk("3 object(s) fall outside this printer's 270 × 270 mm printable area", plate, travel));
});
test("provider weight must be the seeded figure and recorded: positive-but-wrong or derived fails", () => {
  const want = SPOOL.initialG - SPOOL.usedG;
  assert.ok(providerWeightOk({ remaining_g: want, remaining_quality: "tracked" }, want));
  assert.ok(!providerWeightOk({ remaining_g: 100, remaining_quality: "tracked" }, want));
  assert.ok(!providerWeightOk({ remaining_g: want, remaining_quality: "derived" }, want));
  assert.ok(!providerWeightOk({ remaining_g: "900", remaining_quality: "tracked" }, want));
  assert.ok(!providerWeightOk(undefined, want));
});
