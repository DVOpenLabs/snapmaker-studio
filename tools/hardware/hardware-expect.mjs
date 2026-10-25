// Pure expectations for the real-U1 checks, kept out of checks.mjs so they can be tested against deliberately
// wrong inputs (a predicate that cannot fail proves nothing). node --test tools/hardware/hardware-expect.test.mjs

/** The U1's printable area, pinned here so the check does not take its expectation from the source it verifies.
 *  Provenance: the Snapmaker U1 machine preset printable_area polygon 0.5x1 -> 270.5x271 (data/profiles/snapmaker_u1.json) is exactly
 *  270 x 270, and the shipped printer profile records the same.
 *  hardware-expect.test.mjs compares this with the shipped profile so drift is caught at test time, not at run time. */
export const U1_PRINTABLE_MM = { x: 270, y: 270 };

/** "%g"-style number text, as the engine writes plate extents: 270 not 270.0. */
export function g(n) {
  return String(Number(n));
}

/**
 * The bed.fit finding for a project with an object past the plate.
 *
 * The printer reports its toolhead AXIS TRAVEL (about 271 x 335 x 281 on a U1). Studio deliberately does not call
 * that a printable area (backend/snapstudio_core/preflight.py `_bed`, bed_fit.py): it judges placement against the
 * printable area of the machine profile and names that area in the evidence. So the correct expectations are:
 *   - the evidence names the profile's printable area (`<x> × <y> mm printable area`), and
 *   - it does not present the printer's axis travel as the area, and
 *   - it counts the deliberately off-plate object(s) as outside.
 * `plate` is the profile's build volume {x, y}; `travel` is what the printer reported {x, y, z}.
 */
export function bedFitEvidenceOk(evidence, plate, travel, expectedOutside = 1) {
  const text = String(evidence ?? "");
  const named = text.includes(`${g(plate.x)} × ${g(plate.y)} mm printable area`);
  const travelAsArea = [travel.x, travel.y, travel.z]
    .filter((v) => Number.isFinite(Number(v)) && Number(v) !== Number(plate.x) && Number(v) !== Number(plate.y))
    .some((v) => new RegExp(String.raw`${g(v)}(\.0)?\s*(×|x|mm)[^.]*(printable|area)`, "i").test(text));
  const outside = /(\d+) object\(s\) fall outside/.exec(text);
  return named && !travelAsArea && Boolean(outside) && Number(outside[1]) === Number(expectedOutside);
}

/** The whole bed.fit finding: the evidence text AND the finding's own verdict. The showcase has exactly one deliberate off-plate object. */
export function bedFitFindingOk(finding, plate, travel, expectedOutside = 1) {
  return Boolean(finding) && finding.result === "attention" && finding.confidence === "confirmed"
    && bedFitEvidenceOk(finding.evidence, plate, travel, expectedOutside);
}

/** A provider's weight for the seeded spool: the exact figure the seed implies, and recorded ("tracked"), not merely positive. */
export function providerWeightOk(slot, expectedG) {
  return typeof slot?.remaining_g === "number" && slot.remaining_g === expectedG && slot.remaining_quality === "tracked";
}

/** True when the page is the Settings page with the printer set up: the Nozzles card rather than its placeholder. */
export function nozzleCardPresent(bodyText) {
  return /Nozzles · for\s+\S/.test(bodyText) && !/Set up your printer above to confirm which nozzles/.test(bodyText);
}
