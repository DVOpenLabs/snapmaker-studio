// Expectations for the geometry-basis routes of the installed engine, kept apart from checks.mjs (which runs on
// import) so they can be tested against recorded responses, including responses that must be refused.
//
// Each expectation is [label, predicate]. A route record that fails names the labels that were false, so a failure
// says which claim broke instead of "HTTP 200" with nothing after it.

import { redact } from "./redact.mjs";

export const SUCCESS_SCHEMA = "successpredict/3";
export const PREDICT_SCOPE = "the print risk signals that rest on the model's size";
export const OFF_PLATE_ID = "placement-off-plate";

const isList = (a) => Array.isArray(a);
const isStrings = (a) => isList(a) && a.every((s) => typeof s === "string");
const has = (a, s) => isList(a) && a.includes(s);
const findingIds = (b) => (isList(b.findings) ? b.findings : []).map((f) => f?.id).filter(Boolean);

/** Labels of the expectations that do not hold for `body`. A predicate that throws counts as not holding. */
export function failedExpectations(expectations, body) {
  return expectations.filter(([, fn]) => { try { return !fn(body); } catch { return true; } }).map(([label]) => label);
}

/** The geometry basis says why the size was not trusted: not established, the given reason code, and a stated reason. */
const refusedFor = (code) => (b) => b.geometry_basis?.established === false && has(b.geometry_basis.reasons, code)
  && typeof b.reason === "string" && b.reason.length > 0 && b.reason === b.geometry_basis.summary;

/** The shape every successpredict/3 answer shares, whatever the geometry. */
const predictShape = [
  ["schema_version is successpredict/3", (b) => b.schema_version === SUCCESS_SCHEMA],
  ["available is true", (b) => b.available === true],
  ["no likelihood field", (b) => !("likelihood" in b)],
  ["no band field", (b) => !("band" in b)],
  ["signals is a list", (b) => isList(b.signals)],
  // Holds for these fixtures because the tool-fit checks are available; a product change that makes them unavailable
  // would show up here as a harness failure to look at, not as a silent pass.
  ["checked lists what was checked", (b) => isStrings(b.checked) && b.checked.length > 0],
  ["not_checked is a list of names", (b) => isStrings(b.not_checked)],
  ["limitations is a non-empty list", (b) => isStrings(b.limitations) && b.limitations.length > 0],
  ["summary is text", (b) => typeof b.summary === "string" && b.summary.length > 0],
];

/** Millimetre file with an established basis: the size-based risk signals were really checked. */
export const predictEstablished = [
  ...predictShape,
  ["no not_checked status", (b) => !("status" in b)],
  // The fixture is a plain 10 x 20 x 30 mm box: any signal here is new and must be looked at, not waved through.
  ["no risk signal is raised for the plain box", (b) => isList(b.signals) && b.signals.length === 0],
  ["first-layer risk was checked", (b) => has(b.checked, "first-layer risk") && !has(b.not_checked, "first-layer risk")],
  ["design validation was checked", (b) => has(b.checked, "design validation") && !has(b.not_checked, "design validation")],
];

/** Inch or scaled file: the size-based signals are withheld, with the exact basis reason, and not reported as checked. */
export const predictNotEstablished = (code) => [
  ...predictShape,
  ["status is not_checked", (b) => b.status === "not_checked"],
  ["scope is the size-based risk signals", (b) => b.scope === PREDICT_SCOPE],
  [`geometry basis not established for ${code}, reason equals the basis summary`, refusedFor(code)],
  ["the basis withholds the print risk signals", (b) => has(b.geometry_basis?.withheld, "the print risk signals")],
  ["first-layer risk is not_checked, not checked", (b) => has(b.not_checked, "first-layer risk") && !has(b.checked, "first-layer risk")],
  ["design validation is not_checked, not checked", (b) => has(b.not_checked, "design validation") && !has(b.checked, "design validation")],
  ["no size-based signal is reported", (b) => isList(b.signals) && b.signals.length === 0],
];

export const BED_SCHEMA = "bedfit/1";
/** The fixtures are one 10 x 20 x 30 mm box; the U1 plate is read from the profile. */
export const FIXTURE_DIMS_MM = { x: 10, y: 20, z: 30 };
const sameDims = (d, want) => !!d && d.x === want.x && d.y === want.y && d.z === want.z;

const bedShape = [
  [`schema_version is ${BED_SCHEMA}`, (b) => b.schema_version === BED_SCHEMA],
  ["available is true", (b) => b.available === true],
  ["model measured as 10 x 20 x 30 mm (units and scale held)", (b) => sameDims(b.dims_mm, FIXTURE_DIMS_MM)],
  ["the one object measured as 10 x 20 x 30 mm", (b) => isList(b.objects_by_size) && b.objects_by_size.length === 1 && sameDims(b.objects_by_size[0]?.dims_mm, FIXTURE_DIMS_MM)],
  ["bed is the 270 mm U1 plate", (b) => b.bed_mm?.x === 270 && b.bed_mm?.y === 270],
  ["placement was checked", (b) => b.placement_checked === true],
  ["no not_checked status", (b) => !("status" in b)],
  ["one object was checked", (b) => b.objects_checked === 1 && b.objects_unmeasured === 0],
  ["every object fits by size", (b) => isList(b.objects_by_size) && b.objects_by_size.length === 1 && b.objects_by_size.every((o) => o.level === "ok")],
];

/** The origin-corner box: fits the bed by size, but its corner sits off the plate. The negative control. */
export const bedOffPlate = [
  ...bedShape,
  ["overall level is risk", (b) => b.overall_level === "risk"],
  [`placement finding ${OFF_PLATE_ID} is present at risk level`, (b) => isList(b.findings) && b.findings.some((f) => f?.id === OFF_PLATE_ID && f.level === "risk")],
  ["the placement finding is the only finding (nothing unexpected alongside it)", (b) => isList(b.findings) && b.findings.length === 1 && b.findings[0]?.id === OFF_PLATE_ID],
];

/** The same box placed on the plate: established, passing, and no placement finding. */
export const bedOnPlate = [
  ...bedShape,
  ["overall level is ok", (b) => b.overall_level === "ok"],
  [`no ${OFF_PLATE_ID} finding`, (b) => !findingIds(b).includes(OFF_PLATE_ID)],
  ["every finding is ok", (b) => isList(b.findings) && b.findings.length > 0 && b.findings.every((f) => f?.level === "ok")],
];

/** Inch or scaled file: bed fit is refused with the exact basis reason and carries no verdict. */
export const bedNotEstablished = (code) => [
  [`schema_version is ${BED_SCHEMA}`, (b) => b.schema_version === BED_SCHEMA],
  ["available is false", (b) => b.available === false],
  ["no overall level", (b) => !("overall_level" in b)],
  ["status is not_checked", (b) => b.status === "not_checked"],
  ["scope is bed fit", (b) => b.scope === "bed fit"],
  [`geometry basis not established for ${code}, reason equals the basis summary`, refusedFor(code)],
];

// Path redaction is shared with job-journey.mjs (see redact.mjs for exactly what is covered).
export { redact };

const redactDeep = (v) => (typeof v === "string" ? redact(v) : isList(v) ? v.map(redactDeep)
  : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, redactDeep(x)])) : v);

/** The fields of a response that the expectations read, as a plain object with no paths. */
export function describeFields(body) {
  if (!body || typeof body !== "object") return { value: redact(body).slice(0, 80) };
  const keep = {};
  for (const k of ["schema_version", "available", "status", "scope", "overall_level", "placement_checked", "dims_mm", "likelihood", "band"]) {
    if (k in body) keep[k] = body[k];
  }
  if (isList(body.findings)) keep.finding_ids = findingIds(body);
  for (const k of ["checked", "not_checked"]) if (isList(body[k])) keep[k] = body[k];
  if (isList(body.signals)) keep.signals = body.signals.length;
  if (body.geometry_basis) keep.basis = { established: body.geometry_basis.established, reasons: body.geometry_basis.reasons, withheld: body.geometry_basis.withheld };
  if (isList(body.findings)) keep.finding_levels = body.findings.map((f) => f?.level);
  for (const k of ["bed_mm", "objects_checked", "objects_unmeasured"]) if (k in body) keep[k] = body[k];
  if (isList(body.objects_by_size)) keep.objects = body.objects_by_size.map((o) => ({ level: o?.level, dims_mm: o?.dims_mm }));
  if (typeof body.geometry_basis?.summary === "string") keep.basis_summary = redact(body.geometry_basis.summary).slice(0, 160);
  if (typeof body.reason === "string") keep.reason = redact(body.reason).slice(0, 90);
  return redactDeep(keep);
}

/** A path-free one-line rendering of a response for a route record. Always valid JSON (not length-capped). */
export function describeResponse(body) {
  return JSON.stringify(describeFields(body));
}

/** The record detail for a geometry route that answered. Every part that can carry response text is sanitized. */
export function routeDetail({ status, ok, failed, payload }) {
  const verdict = ok ? "all expectations held"
    : status === 200 ? `failed: ${failed.join(" | ") || "(none named)"}` : `expectations not evaluated (HTTP ${status})`;
  // describeResponse already sanitizes the response text; the labels in `verdict` are fixed strings from this file.
  return `HTTP ${status}; ${verdict}; ${describeResponse(payload)}`;
}

/** The structured evidence entry for a geometry route that answered. */
export function routeEvidence({ route, fixture, status, failed, payload }) {
  return { route, fixture, status, failed, response: describeFields(payload) };
}

/** The error text and structured evidence entry for a geometry route whose call threw. */
export function routeError({ route, fixture, error }) {
  const text = redact(error).slice(0, 160);
  return { text, evidence: { route, fixture, status: "unavailable", failed: [], error: text } };
}
