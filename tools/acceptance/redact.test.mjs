// node --test tools/acceptance/redact.test.mjs
// Pure tests for the shared evidence sanitizer and the formatters that feed it. Nothing here imports job-journey.mjs or
// checks.mjs (both run browser and fixture start-up code on import); the wiring is checked by reading their source.
//
// SYNTHETIC FIXTURES: every path below is made up from fictional names (Avery, Fictional Workshop, Sample Models,
// fileserver, O'Brien) and assembled from readable segments by synthetic-paths.mjs, so the repository tracks no
// absolute-path literal. None of these identities is real.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { redact, formatResult } from "./redact.mjs";
import * as geo from "./geometry-expect.mjs";
import { win, winSlash, unc, posix } from "./synthetic-paths.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const source = (f) => readFileSync(join(here, f), "utf8");
const recorded = JSON.parse(readFileSync(join(here, "fixtures", "sidecar-geometry-responses.json"), "utf8"));
const get = (fixture, route) => structuredClone(recorded.responses.find((r) => r.fixture === fixture && r.route === route).body);

const FILE = "secret-sample-widget.3mf";
// Every fictional fragment below must be gone after redaction.
const PRIVATE = /Brien|Avery|avery|Workshop|workshop|Fictional|Sample Models|Models|fileserver|share|Disk|AppData|widget|\.3mf/;

const LOCAL_PATHS = [
  // the two reproductions from the review, with fictional names
  win("D:", "Models", "O'Brien", FILE),
  `open ${posix("tmp", "workshop-files", FILE)} failed`,
  `open ${posix("var", "tmp", FILE)} failed`,
  // windows
  `Could not read ${win("D:", "Fictional Workshop", "O'Brien", "private", FILE)}`,
  `Could not read ${win("D:", "Avery's Sample Models", FILE)}`,
  winSlash("C:", "Users", "Avery", "AppData", FILE),
  win("C:", "", "double", "", "separators", FILE),
  // UNC
  `failed ${unc("fileserver", "O'Brien", "share", FILE)}`,
  `failed ${unc("?", win("C:", "Users", "Avery", FILE))}`,
  // posix
  `open ${posix("Users", "O'Brien", "Sample Models", FILE)}`,
  `open ${posix("home", "avery", "models", FILE)}`,
  `open ${posix("media", "avery", "Avery's Disk", FILE)}`,
  `open ${posix("mnt", "c", "Users", "avery", FILE)}`,
  `open ${posix("Volumes", "Avery's Disk", FILE)}`,
  `open ${posix("root", FILE)}`,
  `open ${posix("var", "folders", "zz", "workshop files", FILE)}`,
  `open ${posix("TMP", "Workshop-Files", FILE)}`,
  // quoted and file URLs
  `read '${posix("tmp", "workshop-files", FILE)}'`,
  `read (${posix("var", "tmp", "O'Brien", FILE)})`,
  `file:///${winSlash("C:", "Users", "Avery", FILE)}`,
  `file://${posix("tmp", "workshop-files", FILE)}`,
];

test("local paths are redacted whole: spaces, apostrophes, UNC and POSIX roots cannot expose a suffix", () => {
  for (const text of LOCAL_PATHS) {
    const out = redact(text);
    assert.match(out, /<path>/, text);
    assert.doesNotMatch(out, PRIVATE, `${text} -> ${out}`);
  }
  assert.equal(redact(win("D:", "Models", "O'Brien", FILE)), "<path>");
  assert.equal(redact(`open ${posix("tmp", "workshop-files", FILE)} failed`), "open <path>");
  assert.equal(redact(`open ${posix("var", "tmp", FILE)} failed`), "open <path>");
});

test("URLs stay intact, including URLs with /tmp and /var segments", () => {
  for (const url of [
    "request to http://127.0.0.1:7125/bed_fit failed: ECONNRESET",
    "GET http://127.0.0.1:7125/tmp/status ok",
    "GET http://127.0.0.1:7125/var/state ok",
    "GET https://example.com/a/tmp/b and https://example.com/var/tmp/c",
    "GET http://tmp/x and http://var/y",
    "GET https://example.com/home/page and https://example.com/Users/list",
    "ws://localhost:9222/devtools/page/ABC",
    "plain text with no path, a/b and 3/4 and tmp and var",
  ]) assert.equal(redact(url), url);
});

test("mixed URL and local-path text does not leak the local path", () => {
  const a = redact(`GET http://127.0.0.1:7125/tmp/status failed reading ${posix("tmp", "workshop-files", FILE)}`);
  assert.equal(a, "GET http://127.0.0.1:7125/tmp/status failed reading <path>");
  const b = redact(`request to https://example.com/var/x failed; file ${win("D:", "Models", "O'Brien", FILE)}`);
  assert.equal(b, "request to https://example.com/var/x failed; file <path>");
  const c = redact(`open ${posix("var", "tmp", FILE)} via http://127.0.0.1:7125/tmp/x`);
  assert.doesNotMatch(c, PRIVATE);
  assert.match(c, /<path>/);
});

test("paths inside JSON-encoded text are redacted, including after an escaped newline or tab", () => {
  for (const text of [
    `boom\n${win("D:", "Fictional Workshop", "Acme", FILE)}`,
    `boom\t${win("D:", "Models", "O'Brien", FILE)}`,
    `boom\r\n${winSlash("C:", "Users", "Avery", FILE)}`,
    `boom\n${posix("Users", "O'Brien", FILE)}`,
    `boom\n${posix("home", "avery", FILE)}`,
    `boom\n${posix("tmp", "workshop-files", FILE)}`,
    `boom\t${posix("var", "tmp", FILE)}`,
    `boom\n${unc("fileserver", "share", FILE)}`,
  ]) {
    const encoded = JSON.stringify([text]);
    assert.match(encoded, /\\[nrt]/, "the fixture really is JSON-escaped");
    const out = redact(encoded);
    assert.match(out, /<path>/, out);
    assert.doesNotMatch(out, PRIVATE, out);
    const line = formatResult("A check", false, JSON.stringify(text));
    assert.doesNotMatch(line.detail, PRIVATE, line.detail);
    assert.doesNotMatch(line.line, PRIVATE, line.line);
  }
  // The escape exception must not reopen the URL and word-boundary cases.
  for (const kept of [
    JSON.stringify("boom\nGET http://127.0.0.1:7125/tmp/status"),
    JSON.stringify("boom\tGET https://example.com/a/var/b"),
    "fooC:",
    "xhttp://h/tmp",
  ]) assert.equal(redact(kept), kept);
});

test("the sanitizer is pure: repeated calls give the same answer and carry no regex state", () => {
  const text = `open ${posix("tmp", "a", FILE)} and ${win("D:", "x", "y")}`;
  const first = redact(text);
  for (let i = 0; i < 5; i++) assert.equal(redact(text), first);
  assert.equal(redact(undefined), "undefined");
  assert.equal(redact(null), "null");
  assert.equal(redact(new Error(`boom at ${posix("var", "tmp", FILE)}`)), "Error: boom at <path>");
  assert.equal(redact(""), "");
});

test("formatResult (job-journey result line and saved detail) is sanitized", () => {
  for (const text of LOCAL_PATHS) {
    const r = formatResult("A check", false, `native picker failed: ${text}`);
    assert.doesNotMatch(r.detail, PRIVATE, r.detail);
    assert.doesNotMatch(r.line, PRIVATE, r.line);
    assert.match(r.line, /^FAIL {2}A check {2}— native picker failed: /);
  }
  assert.equal(formatResult("ok", true).line, "PASS  ok");
  assert.equal(formatResult("ok", true, "http://127.0.0.1:7125/tmp/x").detail, "http://127.0.0.1:7125/tmp/x");
});

test("geometry evidence output (response summary, record detail, error entry) is sanitized", () => {
  for (const text of LOCAL_PATHS) {
    const payload = get("inch", "/predict_success");
    payload.reason = text;
    payload.geometry_basis.summary = text;
    payload.geometry_basis.reasons = [text];
    payload.checked = [text];
    for (const out of [
      geo.describeResponse(payload),
      JSON.stringify(geo.describeFields(payload)),
      geo.routeDetail({ status: 200, ok: false, failed: ["x"], payload }),
      JSON.stringify(geo.routeEvidence({ route: "/predict_success", fixture: "inch", status: 200, failed: [], payload })),
    ]) assert.doesNotMatch(out, PRIVATE, out);
    const err = geo.routeError({ route: "/bed_fit", fixture: "mm", error: new Error(`failed on ${text}`) });
    assert.doesNotMatch(err.text, PRIVATE, err.text);
    assert.doesNotMatch(JSON.stringify(err.evidence), PRIVATE);
    assert.equal(err.evidence.status, "unavailable");
  }
  // primitive bodies and non-200 answers
  assert.doesNotMatch(geo.describeResponse(`open ${posix("tmp", "workshop-files", FILE)}`), PRIVATE);
  assert.doesNotMatch(geo.routeDetail({ status: 500, ok: false, failed: [], payload: win("D:", "Models", "O'Brien", FILE) }), PRIVATE);
  assert.match(geo.routeDetail({ status: 500, ok: false, failed: [], payload: {} }), /expectations not evaluated \(HTTP 500\)/);
  // a normal answer keeps its diagnostic content
  const good = get("mm", "/bed_fit");
  assert.match(geo.routeDetail({ status: 200, ok: true, failed: [], payload: good }), /^HTTP 200; all expectations held; \{.*"overall_level":"risk"/);
});

test("both evidence scripts use the shared sanitizer and carry no private scrubber", () => {
  const journey = source("job-journey.mjs");
  assert.match(journey, /import \{[^}]*\bredact\b[^}]*\bformatResult\b[^}]*\} from "\.\/redact\.mjs"/);
  assert.match(journey, /formatResult\(name, ok, detail\)/);
  assert.match(journey, /known\.map\(scrub\)/);
  assert.match(journey, /faults\.map\(scrub\)/);
  assert.doesNotMatch(journey, /\.replace\(\/\[A-Za-z\]:/, "job-journey.mjs must not keep its own drive-path regex");
  assert.doesNotMatch(journey, /\.replace\(\/\[\\\\\/\]\+Users/, "job-journey.mjs must not keep its own Users regex");

  const checks = source("checks.mjs");
  assert.match(checks, /geo\.routeDetail\(/);
  assert.match(checks, /geo\.routeEvidence\(/);
  assert.match(checks, /geo\.routeError\(/);
  assert.doesNotMatch(checks, /geo\.describeResponse\(|geo\.redact\(/, "checks.mjs formats geometry evidence only through the shared helpers");

  const expect = source("geometry-expect.mjs");
  assert.match(expect, /from "\.\/redact\.mjs"/);
  assert.doesNotMatch(expect, /PATHISH/, "geometry-expect.mjs must not keep its own path regex");
  assert.equal(geo.redact, redact, "geometry-expect re-exports the shared sanitizer");
});
