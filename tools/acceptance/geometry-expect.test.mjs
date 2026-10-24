// node --test tools/acceptance/geometry-expect.test.mjs
// The geometry expectations, run against responses recorded from the candidate's frozen sidecar (fixtures/) and
// against deliberately wrong responses, which must be refused. A predicate that cannot fail proves nothing.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as geo from "./geometry-expect.mjs";

const recorded = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "fixtures", "sidecar-geometry-responses.json"), "utf8"));
const get = (fixture, route) => structuredClone(recorded.responses.find((r) => r.fixture === fixture && r.route === route).body);
const failed = (expectations, body) => geo.failedExpectations(expectations, body);
const refused = (expectations, body, label) => {
  const f = failed(expectations, body);
  assert.ok(f.length > 0, `expected a refusal${label ? ` (${label})` : ""}`);
  return f;
};

test("recorded sidecar responses satisfy their own fixture's expectations", () => {
  assert.deepEqual(failed(geo.predictEstablished, get("mm", "/predict_success")), []);
  assert.deepEqual(failed(geo.predictEstablished, get("mm_onplate", "/predict_success")), []);
  assert.deepEqual(failed(geo.predictNotEstablished("unit_not_millimeter"), get("inch", "/predict_success")), []);
  assert.deepEqual(failed(geo.predictNotEstablished("transform_scaled"), get("scaled", "/predict_success")), []);
  assert.deepEqual(failed(geo.bedOffPlate, get("mm", "/bed_fit")), []);
  assert.deepEqual(failed(geo.bedOnPlate, get("mm_onplate", "/bed_fit")), []);
  assert.deepEqual(failed(geo.bedNotEstablished("unit_not_millimeter"), get("inch", "/bed_fit")), []);
  assert.deepEqual(failed(geo.bedNotEstablished("transform_scaled"), get("scaled", "/bed_fit")), []);
});

test("the origin-corner fixture is a negative control for bed fit: it is not accepted as passing", () => {
  const offPlate = get("mm", "/bed_fit");
  assert.equal(offPlate.overall_level, "risk");
  assert.ok(offPlate.findings.some((f) => f.id === geo.OFF_PLATE_ID));
  refused(geo.bedOnPlate, offPlate, "off-plate answer offered as the passing control");
});

test("the on-plate control is not accepted as the off-plate answer, and ok-with-a-placement-finding is refused", () => {
  const onPlate = get("mm_onplate", "/bed_fit");
  refused(geo.bedOffPlate, onPlate, "passing answer offered as the off-plate control");
  const mixed = get("mm_onplate", "/bed_fit");
  mixed.findings.push({ level: "ok", id: geo.OFF_PLATE_ID, text: "x" });
  assert.ok(refused(geo.bedOnPlate, mixed).some((l) => l.includes(geo.OFF_PLATE_ID)));
  const risk = get("mm_onplate", "/bed_fit");
  risk.overall_level = "risk";
  refused(geo.bedOnPlate, risk, "risk where ok is required");
  const unchecked = get("mm_onplate", "/bed_fit");
  unchecked.placement_checked = false;
  refused(geo.bedOnPlate, unchecked, "placement not checked");
});

test("a bed-fit answer for the wrong basis is refused in both directions", () => {
  refused(geo.bedNotEstablished("unit_not_millimeter"), get("mm_onplate", "/bed_fit"), "established answer for an inch file");
  refused(geo.bedNotEstablished("unit_not_millimeter"), get("scaled", "/bed_fit"), "scaled reason for an inch file");
  refused(geo.bedOnPlate, get("inch", "/bed_fit"), "refusal accepted as a pass");
  const noScope = get("inch", "/bed_fit");
  delete noScope.scope;
  refused(geo.bedNotEstablished("unit_not_millimeter"), noScope, "scope missing");
  const altered = get("inch", "/bed_fit");
  altered.reason = "Some other reason.";
  refused(geo.bedNotEstablished("unit_not_millimeter"), altered, "reason differs from the basis summary");
});

test("predict_success: the removed likelihood and band fields are refused if they come back", () => {
  for (const extra of [{ likelihood: 0.9 }, { likelihood: null }, { band: "good" }, { band: "unknown" }]) {
    const b = { ...get("mm", "/predict_success"), ...extra };
    const f = refused(geo.predictEstablished, b, JSON.stringify(extra));
    assert.ok(f.some((l) => /likelihood|band/.test(l)));
  }
});

test("predict_success: malformed responses are refused", () => {
  const cases = {
    "old schema": (b) => { b.schema_version = "successpredict/2"; },
    "no schema": (b) => { delete b.schema_version; },
    "unavailable": (b) => { b.available = false; },
    "signals not a list": (b) => { b.signals = "none"; },
    "checked empty": (b) => { b.checked = []; },
    "checked with a non-string": (b) => { b.checked = [1]; },
    "no not_checked": (b) => { delete b.not_checked; },
    "no limitations": (b) => { b.limitations = []; },
    "no summary": (b) => { b.summary = ""; },
  };
  for (const [name, mutate] of Object.entries(cases)) {
    const b = get("mm", "/predict_success");
    mutate(b);
    refused(geo.predictEstablished, b, name);
    const n = get("inch", "/predict_success");
    mutate(n);
    refused(geo.predictNotEstablished("unit_not_millimeter"), n, `${name} (inch)`);
  }
  assert.ok(failed(geo.predictEstablished, null).length > 0, "null body");
  assert.ok(failed(geo.predictEstablished, "text").length > 0, "string body");
});

test("predict_success: incorrectly established geometry is refused", () => {
  // An inch or scaled file answered as if its size were trusted.
  for (const [fixture, code] of [["inch", "unit_not_millimeter"], ["scaled", "transform_scaled"]]) {
    refused(geo.predictNotEstablished(code), get("mm", "/predict_success"), `mm answer for ${fixture}`);
    const claimed = get(fixture, "/predict_success");
    claimed.checked = [...claimed.checked, "first-layer risk", "design validation"];
    claimed.not_checked = claimed.not_checked.filter((n) => n !== "first-layer risk" && n !== "design validation");
    refused(geo.predictNotEstablished(code), claimed, `${fixture} claims the size-based checks ran`);
    const noStatus = get(fixture, "/predict_success");
    delete noStatus.status;
    refused(geo.predictNotEstablished(code), noStatus, `${fixture} without a not_checked status`);
    const wrongScope = get(fixture, "/predict_success");
    wrongScope.scope = "the print-success estimate";
    refused(geo.predictNotEstablished(code), wrongScope, `${fixture} with the old scope`);
    const established = get(fixture, "/predict_success");
    established.geometry_basis.established = true;
    refused(geo.predictNotEstablished(code), established, `${fixture} basis marked established`);
    const mismatched = get(fixture, "/predict_success");
    mismatched.reason = "Another reason.";
    refused(geo.predictNotEstablished(code), mismatched, `${fixture} reason differs from the basis`);
    const withSignal = get(fixture, "/predict_success");
    withSignal.signals = [{ id: "x" }];
    refused(geo.predictNotEstablished(code), withSignal, `${fixture} reports a size-based signal`);
  }
  // The wrong reason code for the file.
  refused(geo.predictNotEstablished("transform_scaled"), get("inch", "/predict_success"), "inch answer offered for scaled");
  // An established file answered as withheld.
  refused(geo.predictEstablished, get("inch", "/predict_success"), "withheld answer offered as established");
  const stillStatus = get("mm", "/predict_success");
  stillStatus.status = "not_checked";
  refused(geo.predictEstablished, stillStatus, "established file reporting not_checked");
});

test("describeResponse keeps the fields that explain a failure and no paths", () => {
  const body = get("inch", "/predict_success");
  body.reason = "Could not read C:\\Users\\someone\\private\\model.3mf at all";
  body.geometry_basis.summary = "D:/work/secret.3mf";
  const shown = geo.describeResponse(body);
  assert.match(shown, /successpredict\/3/);
  assert.match(shown, /unit_not_millimeter/);
  assert.match(shown, /not_checked/);
  assert.doesNotMatch(shown, /Users|someone|private|secret|work\//);
  assert.equal(typeof JSON.parse(shown), "object");
  assert.equal(geo.describeResponse(undefined), '{"value":"undefined"}');
});

test("bed_fit: wrong schema, wrong dimensions and malformed bodies are refused", () => {
  for (const [expectations, fixture] of [[geo.bedOnPlate, "mm_onplate"], [geo.bedOffPlate, "mm"]]) {
    const wrongSchema = get(fixture, "/bed_fit");
    wrongSchema.schema_version = "bedfit/2";
    assert.ok(refused(expectations, wrongSchema, "schema").some((l) => l.includes("schema_version")));
    const noSchema = get(fixture, "/bed_fit");
    delete noSchema.schema_version;
    refused(expectations, noSchema, "no schema");
    // The file was read at the wrong size (an inch file taken as millimetres would be 25.4x larger, a x20 scale 20x).
    for (const dims of [{ x: 254, y: 508, z: 762 }, { x: 200, y: 400, z: 600 }, { x: 10, y: 20, z: 31 }]) {
      const wrongDims = get(fixture, "/bed_fit");
      wrongDims.dims_mm = dims;
      refused(expectations, wrongDims, `model dims ${JSON.stringify(dims)}`);
      const wrongObject = get(fixture, "/bed_fit");
      wrongObject.objects_by_size[0].dims_mm = dims;
      refused(expectations, wrongObject, `object dims ${JSON.stringify(dims)}`);
    }
    const missingDims = get(fixture, "/bed_fit");
    delete missingDims.dims_mm;
    refused(expectations, missingDims, "dims missing");
    const wrongBed = get(fixture, "/bed_fit");
    wrongBed.bed_mm = { x: 256, y: 256, z: 256 };
    refused(expectations, wrongBed, "bed is not the U1 plate");
    const noObjects = get(fixture, "/bed_fit");
    noObjects.objects_checked = 0;
    refused(expectations, noObjects, "no object checked");
    const unmeasured = get(fixture, "/bed_fit");
    unmeasured.objects_unmeasured = 1;
    refused(expectations, unmeasured, "an unmeasured object");
    const unfit = get(fixture, "/bed_fit");
    unfit.objects_by_size[0].level = "risk";
    refused(expectations, unfit, "object does not fit by size");
    assert.ok(failed(expectations, null).length > 0, "null body");
    assert.ok(failed(expectations, []).length > 0, "array body");
    assert.ok(failed(expectations, "text").length > 0, "string body");
  }
  const refusalWrongSchema = get("inch", "/bed_fit");
  refusalWrongSchema.schema_version = "bedfit/2";
  refused(geo.bedNotEstablished("unit_not_millimeter"), refusalWrongSchema, "refusal with a wrong schema");
  const withVerdict = get("scaled", "/bed_fit");
  withVerdict.overall_level = "ok";
  refused(geo.bedNotEstablished("transform_scaled"), withVerdict, "refusal that also carries a verdict");
});

test("an unexpected finding on the on-plate control is refused, and unexpected extras on the off-plate control are refused", () => {
  const extra = get("mm_onplate", "/bed_fit");
  extra.findings.push({ level: "warn", text: "something new" });
  refused(geo.bedOnPlate, extra, "non-ok finding on the passing control");
  const otherFinding = get("mm", "/bed_fit");
  otherFinding.findings = [{ level: "risk", id: "some-other-finding", text: "x" }];
  refused(geo.bedOffPlate, otherFinding, "off-plate control without the placement finding");
  const wrongLevel = get("mm", "/bed_fit");
  wrongLevel.findings[0].level = "warn";
  refused(geo.bedOffPlate, wrongLevel, "placement finding at the wrong level");
});

test("describeFields is a real object even for long responses, and route evidence keeps the failed labels' inputs", () => {
  const body = get("mm", "/predict_success");
  body.checked = Array.from({ length: 200 }, (_, i) => `check number ${i} with a long descriptive name`);
  const fields = geo.describeFields(body);
  assert.equal(typeof fields, "object");
  assert.equal(fields.schema_version, "successpredict/3");
  assert.equal(fields.checked.length, 200);
  assert.equal(JSON.parse(geo.describeResponse(body)).checked.length, 200, "the record detail stays valid JSON, never cut mid-token");
  assert.deepEqual(geo.describeFields(get("mm", "/bed_fit")).dims_mm, { x: 10, y: 20, z: 30 });
  assert.deepEqual(geo.describeFields("text"), { value: "text" });
});

test("off-plate control: an extra finding appended beside the placement finding is refused", () => {
  for (const extra of [{ level: "risk", id: "placement-over-height", text: "x" }, { level: "warn", text: "no id" }, { level: "ok", text: "fine" }]) {
    const b = get("mm", "/bed_fit");
    b.findings.push(extra);
    refused(geo.bedOffPlate, b, JSON.stringify(extra));
  }
});

test("established predict_success: any signal, malformed or not, is refused for the plain box", () => {
  for (const fixture of ["mm", "mm_onplate"]) {
    for (const signals of [[null], [1], [{}], [{ id: "x" }], [{ id: "first-layer-footprint", level: "risk", text: "t" }]]) {
      const b = get(fixture, "/predict_success");
      b.signals = signals;
      refused(geo.predictEstablished, b, `${fixture} signals ${JSON.stringify(signals)}`);
    }
  }
});

test("redaction: spaced, UNC, posix-home and primitive-body paths never reach the evidence", () => {
  const dirty = [
    "Could not read D:\\STL Files\\private\\model.3mf at all",
    "failed \\\\nas01\\share\\My Models\\x.3mf",
    "open /Users/someone/My Models/x.3mf failed",
    "open /home/someone/models/x.3mf failed",
    "C:/Users/someone/AppData/x.3mf",
  ];
  for (const text of dirty) {
    const out = geo.redact(text);
    assert.doesNotMatch(out, /STL|private|model\.3mf|nas01|share|My Models|someone|AppData/, out);
    assert.match(out, /<path>/);
    const body = get("inch", "/predict_success");
    body.reason = text;
    body.geometry_basis.reasons = [text];
    const shown = geo.describeResponse(body);
    assert.doesNotMatch(shown, /STL|private|nas01|My Models|someone|AppData/, shown);
    assert.doesNotMatch(JSON.stringify(geo.describeFields(body)), /STL|private|nas01|My Models|someone|AppData/);
    assert.doesNotMatch(geo.describeResponse(text), /STL|private|nas01|My Models|someone|AppData/);
    assert.doesNotMatch(JSON.stringify(geo.describeFields(text)), /STL|private|nas01|My Models|someone|AppData/);
  }
  assert.equal(geo.redact(new Error("boom at D:\\a b\\c.txt")), "Error: boom at <path>");
  assert.equal(geo.redact("plain text"), "plain text");
});

test("redaction: apostrophes in folder names cannot end a path early, other mounts are covered, URLs survive", () => {
  for (const text of [
    "Could not read D:\\STL Files\\O'Brien\\private\\model.3mf",
    "Could not read D:\\Kunal's Models\\x.3mf",
    "failed \\\\nas01\\O'Brien\\share\\x.3mf",
    "open /Users/O'Brien/My Models/x.3mf",
    "open /media/kunal/Kunal's Disk/x.3mf",
    "open /mnt/c/Users/kunal/x.3mf",
    "open /Volumes/Kunal's Disk/x.3mf",
    "open /root/x.3mf",
  ]) {
    const out = geo.redact(text);
    assert.doesNotMatch(out, /Brien|private|model|Kunal|Models|nas01|share|kunal|Disk|x\.3mf/, out);
    assert.match(out, /<path>/);
    const body = get("inch", "/predict_success");
    body.reason = text;
    body.geometry_basis.summary = text;
    const shown = JSON.stringify(geo.describeFields(body));
    assert.doesNotMatch(shown, /Brien|private|Kunal|Models|nas01|kunal|Disk|x\.3mf/, shown);
  }
  const url = "request to http://127.0.0.1:7125/bed_fit failed: ECONNRESET";
  assert.equal(geo.redact(url), url, "a URL is not a drive path");
  assert.equal(geo.redact("see D:\\x and http://127.0.0.1:7125/y"), "see <path>");
});

test("route evidence keeps the inputs of every expectation, so a failure can be read from the file alone", () => {
  const f = geo.describeFields(get("mm", "/bed_fit"));
  assert.deepEqual(f.bed_mm, { x: 270, y: 270, z: 270.05 });
  assert.deepEqual(f.objects, [{ level: "ok", dims_mm: { x: 10, y: 20, z: 30 } }]);
  assert.deepEqual(f.finding_levels, ["risk"]);
  assert.equal(f.objects_checked, 1);
  assert.equal(f.objects_unmeasured, 0);
  const g = geo.describeFields(get("inch", "/bed_fit"));
  assert.match(g.basis_summary, /declares its unit as inch/);
  assert.deepEqual(g.basis.reasons, ["unit_not_millimeter"]);
  assert.ok(g.basis.withheld.includes("bed fit"));
});
