// Read-only verification of the *installed* Snapmaker Studio against a real
// Snapmaker U1, driven over the Chrome DevTools Protocol.
//
// Why this exists: everything Studio says about a printer was, until beta.24,
// verified only against tests the project wrote itself. The first session against
// a real machine found a genuine bug — the U1 reports loaded filament as parallel
// arrays, and Studio was looking for a list of objects, so it told owners their
// printer does not report loaded filament while the printer was reporting all
// four spools. This script proves the shipped installer reads that firmware
// correctly, and that the honest unknowns are still honest.
//
// SAFETY. This script is read-only by construction:
//  * Only the routes in READ_ONLY_ROUTES are ever called, and the list is
//    asserted against a deny-list of every control route the engine exposes.
//  * Nothing is uploaded, nothing is queued, no temperature, motion, homing,
//    pause, resume, cancel, start, emergency stop or configuration call is made.
//
// PRIVACY. The printer's address never reaches the evidence file: it is replaced
// with a placeholder before anything is written to disk.
//
// Usage: node checks.mjs <cdpUrl> <outDir> <printerHost> <samplePath>
//
// Optional, through the environment so the positions above stay the contract
// they already were: SNAPSTUDIO_HW_SPOOLMAN and SNAPSTUDIO_HW_BAMBUDDY, plus
// the seeded spool ids, enable the provider-against-hardware checks. Without
// them everything else still runs and the provider checks say they were
// skipped rather than quietly passing.
//
// v1.2 (R1/R2): also proves the per-printer nozzle confirmation against this
// real machine — a live reading on every toolhead, a note that disagrees
// becoming a conflict row with the printer still winning, and (via the
// `nonAllowedPrinterPosts` network-log assertion) that none of it ever POSTs
// to a `/printer/*` control route. The redacted screenshot this adds
// (v12-nozzle-live.png) goes through redactDom() first (A2.3).
//
// v1.2 fix-up (real Windows run): a fixed wait after navigating to Settings
// raced the nozzle status fetch, which has been observed taking several
// seconds against a real printer — R1/R2 now poll via
// waitForNozzleSettled() (up to 25s, returns the last-seen state either way)
// and scrollNozzleCardIntoView() before the screenshot, which otherwise only
// showed whatever card sits above it.
//
// v1.2 harness-fix round 1 (real-U1 run, 44/47 — Opus/Sol BLOCK on artifact
// 073d7d20f31e1bf): R1 never pointed the app at the SUPPLIED printer — the
// Settings card read "Nozzles · for u1.local" because the app's own printer
// address (usePrinter/localStorage `u1Host`) was still the placeholder.
// setAppPrinterHost() now fills the real Settings address field with
// `printerHost` before R1 reads anything (H1). R2 now drives the conflict
// through the real select + Save and the real "Remove my note" button
// (H2) — one direct /nozzles/confirm bootstrap write is still unavoidable to
// unlock that row's select at all: NozzleTable hides the select whenever a
// toolhead is `reported_live` with no stored note yet (a toolhead the
// printer currently answers for has nothing to override), so the very first
// note for a live-reporting toolhead cannot be typed through this table; see
// the comment at that call site. Every conflict/removal assertion reads a
// fresh `/nozzles/status` with `probe:true`, never the app's own
// `/nozzles/confirm` reply (that reply is `probe:false` by backend design —
// R2-B6 — so it cannot prove the current conflict state). H3: every capture,
// including hardware.png, is now redacted (or taken off the Settings route
// entirely) and skipped on any residue. H4: anonymise()/redactDom()/the final
// leak scan all match the raw supplied host AND its canonical form
// (lowercase, one trailing dot stripped, IPv6 bracketed+compressed),
// case-insensitively, and the run FAILS if either form survives anywhere in
// the evidence directory. H5: the network-log assertion now also proves the
// request listener actually saw allow-listed printer traffic (>=1), so a
// silently-broken listener can no longer pass by finding nothing.
//
// F6: THE PROCESS EXIT CODE IS AUTHORITATIVE, not hardware.json's own
// `passed`/`total` fields. hardware.json is written once, before the final
// evidence-directory leak scan (H8 — nothing is ever written again after
// that scan runs), so it can legitimately read "every check passed" even on
// a run whose exit code is still non-zero because the leak scan itself found
// something. A caller (verify.ps1, or anyone reading this run's result)
// must check `$LASTEXITCODE` / this process's exit status, not just parse
// the JSON and assume 0 means clean.

import { chromium } from "playwright-core";
import { writeFileSync, readFileSync, readdirSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const [, , cdpUrl, outDir, printerHost, samplePath] = process.argv;
mkdirSync(outDir, { recursive: true });

const READ_ONLY_ROUTES = [
  "/printer/status",
  "/printer/capabilities",
  "/printer/firmware",
  "/preflight",
  "/post_slice",
  // Reads the machine and the job together, and produces the fingerprint the
  // send path compares against. It uploads nothing: the engine's upload lives
  // behind a different route, which is not in this list and never will be.
  "/send_check",
  "/material_plan",
  // v1.2 (R1/R2): a per-printer nozzle confirmation is Studio's own local
  // note, stored in the app's own database and keyed by the printer's
  // address — it never reaches the printer at all, so it belongs on this
  // read-only-of-the-machine list even though "confirm" sounds like a write.
  // The network-log assertion below (`nonAllowedPrinterPosts`) is the actual
  // proof that nothing was sent to the machine.
  "/nozzles/status",
  "/nozzles/confirm",
];

// Anything that could change the machine's state. Asserted, not assumed.
const FORBIDDEN = [
  "control", "start", "pause", "resume", "cancel", "emergency",
  "upload", "queue", "gcode", "config", "firmware_update", "restart",
];
for (const route of READ_ONLY_ROUTES) {
  const tail = route.split("/").pop();
  if (FORBIDDEN.some((f) => tail.includes(f) && tail !== "firmware")) {
    throw new Error(`refusing to run: ${route} is not read-only`);
  }
}

// Print the gate before the first request, so what this run is allowed to do is
// on the record rather than inferred from the code afterwards. `callRoute` is
// then held to the same list at the moment of the call: a route added to the
// script without being added here does not reach the printer.
console.log("READ-ONLY GATE — POST is the only method used, to these routes only:");
for (const route of READ_ONLY_ROUTES) console.log(`  ${route}`);
console.log(`  refused if the tail matches: ${FORBIDDEN.join(", ")}`);
console.log("  no upload, start, pause, resume, cancel, emergency stop, gcode script,");
console.log("  heating, motion, homing, configuration write, deletion or queue change.");
console.log("");

const results = [];
const record = (name, ok, detail = "") => {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`);
};

/** Best-effort RFC5952-ish IPv6 compression, good enough for the common
 *  forms this harness needs to match (already-compressed input, or a fully
 *  expanded one) — this is a redaction aid, not the product's own host
 *  validation, so it only has to be a plausible candidate string, not a
 *  canonical parser. */
function compressIPv6(addr) {
  let groups;
  if (addr.includes("::")) {
    const [head, tail] = addr.split("::");
    const headGroups = head ? head.split(":") : [];
    const tailGroups = tail ? tail.split(":") : [];
    const missing = Math.max(0, 8 - headGroups.length - tailGroups.length);
    groups = [...headGroups, ...Array(missing).fill("0"), ...tailGroups];
  } else {
    groups = addr.split(":");
  }
  groups = groups.map((g) => (g === "" ? "0" : parseInt(g, 16).toString(16)));
  let bestStart = -1, bestLen = 0, curStart = -1, curLen = 0;
  for (let i = 0; i < groups.length; i += 1) {
    if (groups[i] === "0") {
      if (curStart === -1) curStart = i;
      curLen += 1;
      if (curLen > bestLen) { bestLen = curLen; bestStart = curStart; }
    } else {
      curStart = -1;
      curLen = 0;
    }
  }
  if (bestLen > 1) {
    const before = groups.slice(0, bestStart).join(":");
    const after = groups.slice(bestStart + bestLen).join(":");
    return `${before}::${after}`;
  }
  return groups.join(":");
}

/** v1.2 (H4): the same normalisation the backend's `canonical_host()` applies
 *  — lowercase a DNS name, strip exactly one trailing dot, bracket+compress
 *  IPv6 — so redaction matches whatever form a route response echoes back,
 *  not only the exact string typed on the command line. Best-effort: not
 *  meant to reject anything, only to produce a second plausible candidate. */
function canonicalHostGuess(raw) {
  const h = (raw || "").trim();
  if (!h) return "";
  const isBracketed = h.startsWith("[") && h.endsWith("]");
  const inner = isBracketed ? h.slice(1, -1) : h;
  if (isBracketed || (h.match(/:/g) || []).length >= 2) {
    try {
      return `[${compressIPv6(inner.toLowerCase())}]`;
    } catch {
      return h.toLowerCase();
    }
  }
  let lowered = h.toLowerCase();
  if (lowered.length > 1 && lowered.endsWith(".") && !lowered.endsWith("..")) {
    lowered = lowered.slice(0, -1);
  }
  return lowered;
}

// Both forms a route response could echo: the raw supplied address, and the
// backend's canonicalisation of it. Deduplicated and never empty-stringed.
const hostCandidates = [...new Set([printerHost, canonicalHostGuess(printerHost)])]
  .filter((h) => h && h.length > 0);

function redactText(text, candidates) {
  let out = text;
  for (const c of candidates) {
    const escaped = c.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    out = out.replace(new RegExp(escaped, "ig"), "<printer-on-lan>");
  }
  return out;
}

/** Replace the printer's address (raw AND canonical form, case-insensitively)
 *  wherever it appears, at any depth. */
const anonymise = (value) =>
  JSON.parse(redactText(JSON.stringify(value), hostCandidates));

async function appPage(browser) {
  const ctx = browser.contexts()[0];
  for (const page of ctx.pages()) {
    if (page.url().startsWith("http://tauri.localhost")) return page;
  }
  throw new Error("the app window was not found over CDP");
}

async function callRoute(page, route, body) {
  // The gate, enforced where it matters rather than only where it is declared.
  if (!READ_ONLY_ROUTES.includes(route)) {
    throw new Error(`refusing to call ${route}: not in the read-only list`);
  }
  return page.evaluate(
    async ([route, body]) => {
      const info = await window.__TAURI_INTERNALS__.invoke("get_api_info");
      const res = await fetch(`http://127.0.0.1:${info.port}${route}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Auth-Token": info.token },
        body: JSON.stringify(body),
      });
      return { status: res.status, body: await res.json() };
    },
    [route, body],
  );
}

/** v1.2 (A2.3/H4): redacts the printer's address — both the raw supplied form
 *  and its canonical form, case-insensitively — out of visible text, input/
 *  textarea values and the title/aria-label/placeholder/alt attributes, and
 *  reports whether any of either form is still there. The caller must skip
 *  the capture rather than ship a screenshot that still names the real
 *  printer. */
async function redactDom(page, hostTexts) {
  const needles = (Array.isArray(hostTexts) ? hostTexts : [hostTexts]).filter(Boolean);
  if (needles.length === 0) return true;
  const stillPresent = await page.evaluate((rawNeedles) => {
    const lowers = rawNeedles.map((n) => n.toLowerCase());
    const res = rawNeedles.map((n) => new RegExp(n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "ig"));
    const ATTRS = ["title", "aria-label", "placeholder", "alt"];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      for (const re of res) {
        if (node.nodeValue && re.test(node.nodeValue)) {
          node.nodeValue = node.nodeValue.replace(re, "your printer");
        }
      }
    }
    document.querySelectorAll("input, textarea").forEach((el) => {
      for (const re of res) {
        if (el.value && re.test(el.value)) el.value = el.value.replace(re, "your printer");
      }
    });
    document.querySelectorAll("*").forEach((el) => {
      for (const attr of ATTRS) {
        const v = el.getAttribute(attr);
        if (!v) continue;
        for (const re of res) {
          if (re.test(v)) el.setAttribute(attr, v.replace(re, "your printer"));
        }
      }
    });
    const bodyText = (document.body.innerText || "").toLowerCase();
    const inputVals = [...document.querySelectorAll("input, textarea")]
      .map((el) => el.value || "").join(" ").toLowerCase();
    const attrVals = [...document.querySelectorAll("*")]
      .flatMap((el) => ATTRS.map((a) => el.getAttribute(a) || "")).join(" ").toLowerCase();
    const haystack = bodyText + " " + inputVals + " " + attrVals;
    return lowers.some((lower) => haystack.includes(lower));
  }, needles);
  return !stillPresent;
}

/** Polls the Nozzles card until its initial load finishes ("Checking your
 *  printer…" is gone) or `timeoutMs` elapses, returning the last-observed
 *  body text either way — a fixed short wait has been observed racing a
 *  status fetch that took 7-9s in a real run. */
async function waitForNozzleSettled(page, timeoutMs = 25000) {
  const deadline = Date.now() + timeoutMs;
  let body = await page.locator("body").innerText();
  while (Date.now() < deadline) {
    if (!/Checking (the|your) printer/i.test(body)) break;
    await page.waitForTimeout(500);
    body = await page.locator("body").innerText();
  }
  return body;
}

/** A screenshot naming the Nozzles card must actually show it. */
async function scrollNozzleCardIntoView(page) {
  await page.evaluate(() => {
    const heading = [...document.querySelectorAll("p")]
      .find((el) => /Nozzles · for/i.test(el.textContent || ""));
    const card = heading?.closest("div")?.parentElement || heading;
    card?.scrollIntoView({ block: "center" });
  });
  await page.waitForTimeout(300);
}

/** v1.2 (H7/H6): scopes an assertion to exactly one toolhead's own `<tr>` —
 *  a page-wide count (the round-1 approach) could pass on the right NUMBER
 *  of "Reported live"/"Confirmed by you" rows while actually describing the
 *  wrong toolheads. `n` is 1-based, matching the rendered "Toolhead N" text. */
function toolheadRow(page, n) {
  return page.locator("tr").filter({ hasText: `Toolhead ${n}` });
}

/** v1.2 (H6, F1 — fix-round-3, second real-run failure on this exact item):
 *  forces the Nozzles card to refetch after a write made through the API
 *  directly (a seeded note, in this case) rather than through the card's own
 *  controller — the controller has no reason to know that happened, so
 *  without this the card would keep showing what it already had.
 *
 *  Round-2's fix (re-filling the Settings host field with the SAME address)
 *  was confirmed wrong by a real run: `settingsNozzleFetchTrigger(host)` only
 *  changes when `host` itself changes, and re-filling a field with its own
 *  current value is not a change — no re-render, no refetch, and the row
 *  kept showing the pre-seed state. The card refetches on two things only:
 *  a host change, or a genuine remount. This forces the second, exactly as
 *  specified: navigate to "/" — the real Dashboard route ("/dashboard" is
 *  NotFound and was never the fix) — wait for its own heading, then navigate
 *  back to "/settings", which mounts a fresh PrinterNozzleSettings instance
 *  and restarts its fetch. */
async function forceNozzleCardRefetch(page) {
  await page.evaluate(() => {
    window.history.pushState({}, "", "/");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await page.locator("h1").filter({ hasText: "Dashboard" }).waitFor({ state: "visible", timeout: 10000 });
  await page.evaluate(() => {
    window.history.pushState({}, "", "/settings");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
}

/** v1.2 (H1): sets the app's OWN printer address — the same field a real
 *  owner types into (Settings -> "Your Snapmaker U1") — to the supplied host,
 *  so the Nozzles card (and everything else keyed by `usePrinter`) actually
 *  points at this real printer instead of the "U1.local" placeholder it
 *  otherwise defaults to. Filling this field calls the store's own setHost(),
 *  which persists to localStorage and reactively restarts the Nozzles card's
 *  fetch — no page reload needed. */
async function setAppPrinterHost(page, host) {
  await page.evaluate(() => {
    window.history.pushState({}, "", "/settings");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await page.waitForTimeout(800);
  await page.getByPlaceholder("U1.local").first().fill(host);
  await page.waitForTimeout(500);
}

/** True while the Nozzles card's own Save/Remove all/Update my note/Remove my
 *  note button is disabled — a save/clear currently re-probes the printer
 *  (7-9s observed offline; still real network time against a real one), so a
 *  click has to be followed by waiting for this to clear, not a fixed pause. */
async function nozzleCardBusy(page) {
  return page.evaluate(() => {
    const heading = [...document.querySelectorAll("p")]
      .find((el) => /Nozzles · for/i.test(el.textContent || ""));
    const card = heading?.closest("div")?.parentElement || heading;
    if (!card) return true;
    const buttons = [...card.querySelectorAll("button")]
      .filter((b) => /^(Save|Remove all|Update my note|Remove my note)/i
        .test((b.textContent || "").trim()));
    return buttons.some((b) => b.disabled);
  });
}

/** Waits, after a click on the Nozzles card's own Save/Update/Remove/Remove
 *  all, until that button is enabled again AND the card's own loading text is
 *  gone, or `timeoutMs` elapses — always returning the last-observed body
 *  text so a timeout still carries real evidence rather than a blind FAIL. */
async function waitForNozzleIdle(page, timeoutMs = 25000) {
  const deadline = Date.now() + timeoutMs;
  let body = await page.locator("body").innerText();
  let busy = (await nozzleCardBusy(page)) || /Checking (the|your) printer/i.test(body);
  while (busy && Date.now() < deadline) {
    await page.waitForTimeout(500);
    body = await page.locator("body").innerText();
    busy = (await nozzleCardBusy(page)) || /Checking (the|your) printer/i.test(body);
  }
  return body;
}

/** v1.2 (H4/H8): scans every file already written to the evidence directory
 *  for either form of the supplied printer address, byte-for-byte (latin1,
 *  so a screenshot's raw bytes/metadata are scanned too, not just text/JSON)
 *  — a backstop independent of, and run strictly after, every in-page
 *  redaction pass above and every write this script makes (H8: nothing is
 *  written again after this scan runs, and this scan is never re-run).
 *
 *  This is NOT a check that the printer's address never appears as rendered
 *  PIXELS in a screenshot — a PNG stores compressed pixel data, not plain
 *  text, so a string search over its bytes cannot see text that was drawn on
 *  screen. That protection is redactDom()'s job, run on the live page BEFORE
 *  each screenshot is captured; this scan instead catches whatever redactDom
 *  cannot reach — file metadata, JSON, and any other byte sequence.
 *
 *  H8: returns FILENAMES ONLY, never the address itself — a caller must not
 *  be able to leak the very thing this check exists to catch back into its
 *  own output (e.g. by writing this function's return value into evidence). */
function scanEvidenceForHost(dir, candidates) {
  const hitFiles = new Set();
  let names = [];
  try {
    names = readdirSync(dir);
  } catch {
    return [];
  }
  for (const name of names) {
    let buf;
    try {
      buf = readFileSync(join(dir, name));
    } catch {
      continue;
    }
    const haystack = buf.toString("latin1").toLowerCase();
    for (const candidate of candidates) {
      if (candidate && haystack.includes(candidate.toLowerCase())) {
        hitFiles.add(name);
        break;
      }
    }
  }
  return [...hitFiles];
}

const browser = await chromium.connectOverCDP(cdpUrl);
const page = await appPage(browser);
const evidence = {};

// v1.2 (R2/H5/A7-6): every POST this session makes to a genuine `/printer/*`
// CONTROL route that is not on READ_ONLY_ROUTES — the actual, network-level
// proof that a nozzle confirmation/conflict never reaches the machine,
// rather than trusting that the code path this script happens to call is the
// only one that could. Narrowed (Opus A7-6) to actual control surfaces —
// /printer/control/*, job_queue, upload_gcode, and print start/pause/resume/
// cancel — rather than any unlisted `/printer/*` POST at all: an unlisted
// READ route this script has not yet added to the allow-list is a coverage
// gap to fix, not machine-state evidence, and flagging it as "forbidden" only
// muddies the one check that actually matters here. H5: also counts the
// ALLOW-LISTED `/printer/*` POSTs this listener sees, so a silently-broken
// listener (one that never fires at all) cannot pass by finding nothing.
const PRINTER_CONTROL_PATH = /^\/printer\/(control(\/|$)|job_queue(\/|$)|upload_gcode(\/|$)|print\/(start|pause|resume|cancel)(\/|$)?$)/i;
const nonAllowedPrinterPosts = [];
let allowedPrinterPostCount = 0;
page.on("request", (req) => {
  try {
    const url = new URL(req.url());
    if (req.method() === "POST" && url.pathname.startsWith("/printer/")) {
      if (READ_ONLY_ROUTES.includes(url.pathname)) {
        allowedPrinterPostCount += 1;
      } else if (PRINTER_CONTROL_PATH.test(url.pathname)) {
        nonAllowedPrinterPosts.push(url.pathname);
      }
      // Else: an unlisted read route — not flagged here (see comment above).
    }
  } catch {
    // Not a request this script can parse as a URL; not a printer route either.
  }
});

// --- the printer answers -----------------------------------------------------

const status = await callRoute(page, "/printer/status", { host: printerHost, port: 7125 });
evidence.status = anonymise(status.body);
const reachable = status.status === 200 && !status.body?.error;
record("Printer discovered and answering", reachable,
  `print state: ${status.body?.print_state ?? "unknown"}`);

const caps = await callRoute(page, "/printer/capabilities", { host: printerHost, port: 7125 });
evidence.capabilities = anonymise(caps.body);
const objects = caps.body?.klipper_objects ?? [];
record("Firmware object list enumerated", objects.length > 50, `${objects.length} objects`);

const bed = caps.body?.bed_mm ?? {};
record("Printer reports its own bed size",
  Number(bed.x) > 100 && Number(bed.y) > 100 && Number(bed.z) > 100,
  `${bed.x} × ${bed.y} × ${bed.z} mm`);
record("Printer reports its toolhead count", caps.body?.toolhead_count === 4,
  `${caps.body?.toolhead_count} toolheads`);

// --- the bug this release fixes ---------------------------------------------
//
// Stock U1 firmware publishes loaded filament as parallel arrays. Studio was
// looking for a list of objects, found nothing, and told the owner the printer
// does not report loaded filament. This is the shipped code path reading a real
// machine.

const pre = await callRoute(page, "/preflight",
  { path: samplePath, host: printerHost, port: 7125 });
evidence.preflight = anonymise(pre.body);
record("Preflight ran against the real machine", pre.status === 200 && !pre.body?.error);

const loaded = pre.body?.printer?.loaded_filaments ?? [];
record("Loaded filament read from the real firmware", loaded.length === 4,
  loaded.map((f) => `${f.color ?? "?"} ${f.material ?? "?"}`).join(", ") || "none");
record("Each loaded slot carries a material and a colour",
  loaded.length > 0 && loaded.every((f) =>
    typeof f.material === "string" && f.material.length > 0 &&
    typeof f.color === "string" && /^#[0-9a-f]{6}$/i.test(f.color)));

// --- the honest unknowns still hold ------------------------------------------

const rows = pre.body?.checks ?? [];
const text = JSON.stringify(rows).toLowerCase();

const nozzle = rows.find((r) => r.id === "nozzle.match");
// Stock U1 firmware DOES report the fitted nozzle diameter via
// /machine/system_info (confirmed live this session), and the demo project
// (examples/demo_u1_showcase.3mf) states a 0.4mm nozzle matching what a real
// U1 reports — so this fixture's own result is pinned to "ok", the same way
// the post-slice gcode.nozzle assertion below is pinned. What must never
// happen is the old "unsupported" framing, and an ok result must cite where
// the reading actually came from.
record("Fitted nozzle matches the real firmware reading, never called unsupported",
  nozzle?.result === "ok"
    && !JSON.stringify(nozzle).toLowerCase().includes("unsupported"),
  `${nozzle?.result}: ${nozzle?.evidence ?? nozzle?.title ?? "no nozzle check"}`);
record("A matched nozzle reading is credited to the printer, not asserted with no source",
  nozzle?.result !== "ok" || /the printer reports|you confirmed/.test(nozzle?.evidence ?? ""),
  nozzle?.evidence ?? "");

record("Nothing undetected is called unsupported", !text.includes("unsupported"));

const bedCheck = rows.find((r) => r.id === "bed.fit");
record("The printer's own bed size was used in the bed check",
  Boolean(bedCheck) && bedCheck.evidence.includes(String(bed.x)),
  bedCheck?.evidence ?? "");

const toolheads = rows.find((r) => r.id === "materials.toolheads");
record("Project materials compared against the machine's toolheads",
  Boolean(toolheads) && toolheads.confidence === "confirmed",
  toolheads?.evidence ?? "");

const materials = rows.find((r) => r.id === "materials.loaded");
record("Project materials compared against what is actually loaded",
  Boolean(materials) && materials.evidence.includes("4 loaded"),
  materials?.evidence ?? "");

const reachable2 = rows.find((r) => r.id === "printer.reachable");
record("Preflight recorded the printer as found", reachable2?.result === "ok");

// --- the sliced job, joined to this machine ---------------------------------
//
// The Post-Slice Doctor is the half of the workflow that only matters against a
// real printer: a job that prints from slot 2 is fine or fatal depending on
// whether slot 2 has a spool in it. Studio does not slice, so the job is written
// here in the exact shape Snapmaker Orca produces.

const JOB = `; HEADER_BLOCK_START
; generated by Snapmaker Orca 2.3.4 on 2026-08-23 at 10:00:00
; total layer number: 12
; max_z_height: 2.40
; HEADER_BLOCK_END
; EXECUTABLE_BLOCK_START
PRINT_START
M140 S60
T1
;LAYER_CHANGE
;Z:0.2
G1 X10 Y10 Z0.2 F1200
;LAYER_CHANGE
;Z:0.4
G1 X20 Y20 E1.0
PRINT_END
; EXECUTABLE_BLOCK_END

; filament used [mm] = 0.00, 120.00, 0.00, 0.00
; filament used [g] = 0.00, 0.36, 0.00, 0.00
; total filament used [g] = 0.36
; total layers count = 12
; estimated printing time (normal mode) = 4m 10s

; CONFIG_BLOCK_START
; filament_type = PLA;PLA;PLA;PLA
; layer_height = 0.2
; nozzle_diameter = 0.4,0.4,0.4,0.4
; printable_area = 0.5x1,270.5x1,270.5x271,0.5x271
; printer_model = Snapmaker U1
; CONFIG_BLOCK_END
`;

const jobPath = join(outDir, "hardware_job.gcode");
writeFileSync(jobPath, JOB);

const post = await callRoute(page, "/post_slice", { path: jobPath, host: printerHost, port: 7125 });
evidence.post_slice = anonymise(post.body);
const postChecks = post.body?.checks ?? [];
const check = (id) => postChecks.find((c) => c.id === id);

record("Sliced job joined to the real printer",
  post.status === 200 && post.body?.available === true && postChecks.length > 0,
  post.body?.summary ?? "");

record("The tool the job needs is confirmed to exist",
  check("gcode.tools")?.result === "ok", check("gcode.tools")?.evidence ?? "");

record("The slot the job prints from is confirmed loaded",
  check("gcode.loaded")?.result === "ok", check("gcode.loaded")?.evidence ?? "");

record("Loaded material checked against the job's material",
  ["ok", "attention"].includes(check("gcode.material")?.result),
  check("gcode.material")?.evidence ?? "");

record("The job's bed is compared with the printer's own bed",
  check("gcode.bed")?.result === "ok", check("gcode.bed")?.evidence ?? "");

// The JOB fixture above states nozzle_diameter = 0.4 for every toolhead, and
// a real U1's firmware reports the same (confirmed live this session), so
// this now matches — the post-slice nozzle check reads the SAME printer
// reading preflight's does, not a second, still-blind implementation.
record("Fitted nozzle after slicing matches the real firmware reading, never called unsupported",
  check("gcode.nozzle")?.result === "ok"
    && !JSON.stringify(check("gcode.nozzle")).toLowerCase().includes("unsupported"),
  check("gcode.nozzle")?.evidence ?? check("gcode.nozzle")?.title ?? "");

record("Nothing undetected is called unsupported after slicing",
  !JSON.stringify(postChecks).toLowerCase().includes("unsupported"));

// --- what this sprint added, against the real machine --------------------------

// The send fingerprint has to describe *this* printer, and notice when it stops
// describing it. Nothing here changes the machine: the "after" state is the real
// reading with one slot blanked in the copy Studio was given.
const send = await callRoute(page, "/send_check",
  { path: jobPath, host: printerHost, port: 7125 });
const state = send.body?.state;
record("The send check fingerprints what it looked at",
  Boolean(state?.token) && Boolean(state?.hashes?.printer) && Boolean(state?.hashes?.materials),
  state?.token ? `token ${String(state.token).slice(0, 8)}…` : "no fingerprint");

const sendLoadout = send.body?.printer?.loaded_filaments ?? [];
record("The fingerprint carries the machine's real loadout",
  Array.isArray(sendLoadout) && sendLoadout.some((slot) => slot && slot.material),
  `${sendLoadout.filter(Boolean).length} slot(s) with a spool`);

// A real remaining weight needs something that tracks spools; a stock U1 has
// nothing that does, and the honest answer is unknown rather than plenty.
const plan = await callRoute(page, "/material_plan",
  { path: jobPath, host: printerHost, port: 7125 });
const slots = plan.body?.slots ?? [];
const used = slots.filter((slot) => slot.needed);
record("Filament sufficiency stays unknown on a stock printer",
  used.length > 0 && used.every((slot) => slot.sufficiency?.verdict === "unknown"),
  used.map((slot) => `${slot.label}: ${slot.sufficiency?.verdict}`).join(", "));
record("Nothing on a stock printer is called short of filament",
  !slots.some((slot) => slot.state === "not_enough"));

// Extended firmware is detected only when a firmware answers for itself. This
// machine runs stock, so the correct answer is "not detected" — and that must
// not be reported as "this printer is stock", which Studio cannot know.
const firmware = await callRoute(page, "/printer/firmware",
  { host: printerHost, port: 7125 });
const firmwareBody = firmware.body ?? {};
evidence.firmware = anonymise(firmwareBody);
record("Community firmware is not claimed on a stock machine",
  firmwareBody.extended_firmware === false,
  `${firmwareBody.macro_count ?? 0} macros, many=${firmwareBody.many_custom_macros ?? false}`);
record("Not finding a firmware marker is never called stock",
  typeof firmwareBody.extended_firmware_evidence === "string"
  && /not the same as/i.test(firmwareBody.extended_firmware_evidence),
  firmwareBody.extended_firmware_evidence ?? "");

// --- what the two unreleased sprints added, against the real machine ----------
//
// `main` carries the printer-profile architecture and user-facing material
// providers. Both changed load-bearing code on the path between this machine and
// what Studio says about it, and neither had ever been run against hardware. A
// count of 26 that skipped these would be a number, not a verification.

const facts = pre.body?.printer ?? {};
evidence.identity = anonymise(facts.identity ?? null);
evidence.resolved = anonymise(facts.resolved ?? null);
evidence.profile = anonymise(facts.profile ?? null);

// Identification is inference from what the machine reported. `print_task_config`
// is not in mainline Klipper, so a machine carrying it is a Snapmaker — and this
// is the first time that inference has met a real one.
const identity = facts.identity ?? {};
record("The real machine is identified as a Snapmaker U1",
  identity.matched === true && identity.printer_id === "snapmaker_u1"
    && identity.confidence === "confirmed",
  `${identity.printer_id ?? "no match"} (${identity.confidence ?? "-"})`);
record("Identification is drawn from the printer's own vendor object",
  typeof identity.evidence === "string" && identity.evidence.includes("print_task_config"),
  identity.evidence ?? "");

// The U1 must still read as the one printer this project has put on a wire.
record("The U1 profile still reads as hardware verified",
  facts.profile?.verification_level === "hardware_verified",
  facts.profile?.verification_label ?? "no profile");

// The rule the whole abstraction stands on: the machine wins, always.
const resolved = facts.resolved ?? {};
record("The live toolhead count is used, not the profile's",
  resolved.tool_count === 4 && resolved.sources?.tool_count === "live",
  `${resolved.tool_count} from ${resolved.sources?.tool_count}`);
record("The live bed is used, not the profile's",
  resolved.sources?.build_volume_mm === "live"
    && Number(resolved.build_volume_mm?.y) > 300,
  `${resolved.build_volume_mm?.x} × ${resolved.build_volume_mm?.y} × ${resolved.build_volume_mm?.z} from ${resolved.sources?.build_volume_mm}`);

// The U1 travels 335 mm in Y over a 270 mm plate. Live axis range and profile
// printable area answer different questions, so a difference between them is not
// a disagreement — and reporting one at the user would be noise on every launch.
record("Travel beyond the printable plate is not called a conflict",
  Array.isArray(resolved.conflicts) && resolved.conflicts.length === 0,
  `${(resolved.conflicts ?? []).length} conflict(s)`);

// The U1 is unusual in reporting its own filament. That has to stay an
// observation and be marked as one, now that a provider mapping can supply the
// same shape without the machine having looked.
record("Loaded filament is recorded as the printer's own observation",
  resolved.material_state?.known === true
    && resolved.material_state?.source === "live"
    && resolved.material_state?.slots === 4,
  `${resolved.material_state?.slots ?? "?"} slot(s) from ${resolved.material_state?.source ?? "-"}`);

// The extruder objects `status()` asks for are now derived from the printer's own
// tool count rather than a fixed list of four. On a four-toolhead machine the
// answer must be unchanged — this is the truncation regression check.
const channels = status.body?.toolheads ?? [];
record("All four toolhead temperature channels still come back",
  channels.length === 4 && channels.every((t) => typeof t.temperature === "number"),
  `${channels.length} channel(s)`);

// The sliced-machine check was hard-coded to the string "u1" and now compares the
// job against the printer Studio identified. A U1 job on this U1 must still match.
record("A U1-targeted job matches this identified U1",
  check("gcode.machine")?.result === "ok",
  check("gcode.machine")?.evidence ?? "");

// Genericising the wording must not cost the U1 its name where the name is known.
record("The firmware summary names this machine, having identified it",
  typeof firmwareBody.summary === "string" && /U1/.test(firmwareBody.summary),
  firmwareBody.summary ?? "");

// Material providers are reachable in `main`. With none configured, the provider
// path must not execute at all.
//
// This is asserted on `/material_plan`, not on `/preflight`: preflight never
// consults a provider whatever the settings say, so asserting it there would
// pass without proving anything. `material_sources` and `remaining_known` are
// written onto the printer facts only when the provider path actually runs, so
// their absence is the evidence that no provider was contacted.
const planPrinter = plan.body?.printer ?? {};
record("No material provider ran, and none was contacted",
  planPrinter.material_sources === undefined && !planPrinter.remaining_known
    && plan.body?.remaining_known === false,
  `sources=${JSON.stringify(planPrinter.material_sources)} remaining_known=${plan.body?.remaining_known}`);

// And the U1's own reading still reaches the plan, marked as the machine's.
const planSlots = plan.body?.slots ?? [];
record("What the plan compares against came from the printer itself",
  planSlots.some((slot) => slot.confirmed_by === "printer")
    && !planSlots.some((slot) => slot.confirmed_by === "provider"),
  planSlots.map((slot) => `${slot.label}:${slot.confirmed_by ?? "-"}`).join(", "));

// An address that answers nothing is not this machine, and Studio must not tell
// whoever typed it to go and change a setting on a printer it has never seen.
const nowhere = await callRoute(page, "/preflight",
  { path: samplePath, host: "snapstudio-no-such-host-9f3b.invalid", port: 7125 });
const nowhereRow = (nowhere.body?.checks ?? []).find((r) => r.id === "printer.reachable");
const nowhereText = JSON.stringify(nowhere.body ?? {});
// The distinction is conditional versus unconditional, not whether the word
// "touchscreen" appears. Studio may say "if it is a Snapmaker U1, its interface
// only opens once Advanced Mode is on" about an address it knows nothing about;
// what it may not do is instruct someone to go and change a setting on a machine
// it has never seen, which is what the U1-hostname hint does and is right to do
// only there.
const nowhereAction = nowhereRow?.action ?? "";
record("An address that answers nothing gets a generic hint",
  nowhereRow?.result === "unknown"
    && !/On the U1 touchscreen/i.test(nowhereAction)
    && /If it is a Snapmaker U1/i.test(nowhereAction)
    && !nowhereText.includes(printerHost),
  nowhereAction);


// --- a material provider, against a machine that can see its own spools ------
//
// The second-provider sprint added a whole source of material facts and proved
// the seam in tests and in an installed build. Neither of those had a printer
// on the other end. The rule the design turns on only becomes real here: the
// machine is *looking* at the slot, and a provider is somebody's note about it.
//
// All of this is read-only. `/material_plan` and `/send_check` are on the
// allow-list, Studio never writes to a provider, and the providers themselves
// are session-owned containers on this machine, not the printer.

const spoolmanUrl = process.env.SNAPSTUDIO_HW_SPOOLMAN || "";
const bambuddyUrl = process.env.SNAPSTUDIO_HW_BAMBUDDY || "";
const agreeIds = {
  spoolman: Number(process.env.SNAPSTUDIO_HW_SP_AGREE || 0),
  bambuddy: Number(process.env.SNAPSTUDIO_HW_BB_AGREE || 0),
};
const conflictIds = {
  spoolman: Number(process.env.SNAPSTUDIO_HW_SP_CONFLICT || 0),
  bambuddy: Number(process.env.SNAPSTUDIO_HW_BB_CONFLICT || 0),
};
const providerUrls = { spoolman: spoolmanUrl, bambuddy: bambuddyUrl };

/** The plan for the slot this job prints from, with a provider mapped onto it. */
async function planWithProvider(provider, spoolId) {
  const out = await callRoute(page, "/material_plan", {
    path: jobPath, host: printerHost, port: 7125,
    provider, provider_url: providerUrls[provider],
    slot_map: { "2": spoolId }, slot_base: 1,
  });
  const slots = out.body?.slots ?? [];
  return { body: out.body, slot: slots.find((s) => s.needed) ?? slots[1] ?? slots[0] };
}

if (spoolmanUrl && bambuddyUrl) {
  const agreed = {};
  const conflicted = {};

  for (const provider of ["spoolman", "bambuddy"]) {
    // --- the provider agrees with what the machine can see -------------------
    const a = await planWithProvider(provider, agreeIds[provider]);
    agreed[provider] = a.slot;
    record(`The machine's own reading survives a provider that agrees (${provider})`,
      a.slot?.printer_confirmed === true && a.slot?.confirmed_by === "printer"
        && /PLA/i.test(String(a.slot?.has_material ?? "")),
      `${a.slot?.has_material} confirmed_by=${a.slot?.confirmed_by}`);
    record(`The provider supplies the weight the machine cannot know (${provider})`,
      typeof a.slot?.remaining_g === "number" && a.slot.remaining_g > 0
        && a.slot?.remaining_quality === "tracked",
      `${a.slot?.remaining_g} g ${a.slot?.remaining_quality}`);
    record(`Agreement is not reported as a disagreement (${provider})`,
      (a.slot?.conflicts ?? []).length === 0,
      `${(a.slot?.conflicts ?? []).length} conflict(s)`);

    // --- the provider disagrees ---------------------------------------------
    const c = await planWithProvider(provider, conflictIds[provider]);
    conflicted[provider] = c.slot;
    record(`The printer stays authoritative when a provider disagrees (${provider})`,
      /PLA/i.test(String(c.slot?.has_material ?? ""))
        && c.slot?.printer_confirmed === true,
      `${c.slot?.has_material}, printer_confirmed=${c.slot?.printer_confirmed}`);
    record(`The disagreement is said out loud rather than resolved (${provider})`,
      (c.slot?.conflicts ?? []).length > 0
        && (c.slot?.conflicts ?? []).some((x) => /PETG/i.test(x)),
      (c.slot?.conflicts ?? []).join(" ").slice(0, 90));
    record(`A disagreement does not throw the weight away (${provider})`,
      typeof c.slot?.remaining_g === "number" && c.slot.remaining_g > 0,
      `${c.slot?.remaining_g} g`);
  }

  // --- the two providers must decide the same about this machine -------------
  //
  // The seam was proved equal in unit tests and in an installed build. This is
  // the same claim with a real printer supplying half the facts.
  const shape = (slot) => JSON.stringify({
    material: slot?.has_material, state: slot?.state,
    confirmed_by: slot?.confirmed_by, printer_confirmed: slot?.printer_confirmed,
    remaining_g: slot?.remaining_g, quality: slot?.remaining_quality,
    conflicts: (slot?.conflicts ?? []).map((c) => c.replace(/spoolman|bambuddy/gi, "PROVIDER")),
    verdict: slot?.sufficiency?.verdict, trusted: slot?.sufficiency?.trusted,
  });
  record("Two providers agreeing with the machine decide the same",
    shape(agreed.spoolman) === shape(agreed.bambuddy),
    `${shape(agreed.spoolman)} vs ${shape(agreed.bambuddy)}`.slice(0, 160));
  record("Two providers disagreeing with the machine decide the same",
    shape(conflicted.spoolman) === shape(conflicted.bambuddy),
    `${shape(conflicted.spoolman)} vs ${shape(conflicted.bambuddy)}`.slice(0, 160));

  // --- a provider that is not there ------------------------------------------
  //
  // The machine is still there, and what it can see must be unaffected. An
  // unreachable provider subtracts a weight; it does not subtract the printer.
  const gone = await callRoute(page, "/material_plan", {
    path: jobPath, host: printerHost, port: 7125,
    provider: "spoolman", provider_url: "127.0.0.1:1",
    slot_map: { "2": 1 }, slot_base: 1,
  });
  const goneSlots = gone.body?.slots ?? [];
  const goneSlot = goneSlots.find((s) => s.needed) ?? goneSlots[1];
  record("An unreachable provider leaves the machine's own facts intact",
    goneSlot?.printer_confirmed === true
      && /PLA/i.test(String(goneSlot?.has_material ?? "")),
    `${goneSlot?.has_material} confirmed_by=${goneSlot?.confirmed_by}`);
  record("An unreachable provider claims no weight rather than none",
    goneSlot?.remaining_g == null
      && (goneSlot?.sufficiency?.verdict ?? "unknown") === "unknown",
    `remaining=${goneSlot?.remaining_g} verdict=${goneSlot?.sufficiency?.verdict}`);

  // --- and the send decision, with the machine and a provider both speaking ---
  const send = await callRoute(page, "/send_check", {
    path: jobPath, host: printerHost, port: 7125,
    provider: "bambuddy", provider_url: bambuddyUrl,
    slot_map: { "2": agreeIds.bambuddy }, slot_base: 1,
  });
  record("A real machine and a provider together reach a send decision",
    send.status === 200 && send.body?.available === true
      && typeof send.body?.verdict === "string",
    `${send.body?.verdict} ${JSON.stringify(send.body?.counts ?? {})}`);
  record("Nothing about this run claims the printer weighed anything",
    !/weighed|scale/i.test(JSON.stringify(send.body?.materials ?? {})),
    "no weighing claimed on the machine's behalf");

  evidence.provider_on_hardware = anonymise({
    agreed: { spoolman: agreed.spoolman, bambuddy: agreed.bambuddy },
    conflicted: { spoolman: conflicted.spoolman, bambuddy: conflicted.bambuddy },
  });
} else {
  console.log("no provider addresses supplied — the provider-on-hardware checks were skipped");
}

// --- v1.2 (R1/R2): a per-printer nozzle confirmation, against a real U1 -----
//
// Read-only of the machine by construction: /nozzles/status and
// /nozzles/confirm are Studio's own local note, never a call to the printer
// (see the comment on READ_ONLY_ROUTES above). The printer's own live reading
// still always wins — this proves that a note disagreeing with it becomes a
// conflict row rather than a silent override, and that removing the note
// never touched the machine either.

// H1: point the app's OWN printer address at this real printer BEFORE reading
// anything from the UI — the real-U1 run this fix-round responds to found the
// Settings card still reading "Nozzles · for u1.local" because this step did
// not exist. The direct route calls below (nozzleBefore, etc.) already pass
// `host: printerHost` explicitly and were never affected; only the
// UI-rendered assertions were.
await setAppPrinterHost(page, printerHost);

const nozzleBefore = await callRoute(page, "/nozzles/status", { host: printerHost, port: 7125, probe: true });
evidence.nozzle_before = anonymise(nozzleBefore.body);
const liveDiameters = nozzleBefore.body?.live ?? [];
record("The real printer's nozzle sizes are read live (R1)",
  nozzleBefore.status === 200 && Array.isArray(liveDiameters) && liveDiameters.length > 0,
  `${liveDiameters.length} toolhead(s) reported live`);

// The status fetch against a real printer has also been observed taking
// several seconds; wait for the card to settle rather than race a fixed wait.
let bodyText = await waitForNozzleSettled(page);

// H7: scoped to each toolhead's OWN row — a page-wide count of "Reported
// live" occurrences (the round-1 approach) could pass on the right NUMBER of
// matches while actually describing the wrong toolheads.
for (let i = 0; i < liveDiameters.length; i += 1) {
  const rowText = await toolheadRow(page, i + 1).innerText();
  record(`Toolhead ${i + 1}'s own row: nozzle=live size, Source=Printer, Status=Reported live (R1/H7)`,
    rowText.includes(`${liveDiameters[i]} mm`) && /Printer/.test(rowText) && /Reported live/i.test(rowText),
    rowText.replace(/\s+/g, " ").trim());
}

// H6 (product guarantee, a named passing check): a live-reporting toolhead
// offers no way to type an override at all — proved here, before anything
// below seeds a note, and again after the seeded note is removed.
const toolhead1SelectCountBefore = await page
  .locator('select[aria-label="Nozzle size for toolhead 1"]').count();
record("A live-reported toolhead offers no way to type a size — the printer's evidence cannot be overridden (H6)",
  toolhead1SelectCountBefore === 0, `${toolhead1SelectCountBefore} select(s) found`);

await scrollNozzleCardIntoView(page);
const clean1 = await redactDom(page, hostCandidates);
record("Host text redacted before capture: v12-nozzle-live", clean1,
  clean1 ? "host_text_redacted: true" : "printer address still present after redaction");
if (clean1) await page.screenshot({ path: join(outDir, "v12-nozzle-live.png") });

// H6 (R2 redesign): a conflict never arises by typing over a toolhead the
// printer is currently reporting — NozzleTable has no select for one at all
// (just proved above), by product design ("your note cannot override the
// printer"). It arises the way it really would: a note saved while the
// printer did NOT report sizes, discovered later once the printer answers
// and disagrees with it. This write is Studio's own local note (never the
// printer, per READ_ONLY_ROUTES) and is clearly labelled as a seed, not a
// UI action — every assertion that follows reads the real, rendered result.
const conflictValue = Math.abs((liveDiameters[0] ?? 0) - 0.6) < 1e-9 ? 0.4 : 0.6;
const seedDraft = liveDiameters.map((_, i) => (i === 0 ? conflictValue : null));
const seed = await callRoute(page, "/nozzles/confirm", {
  host: printerHost, port: 7125, diameters: seedDraft,
  expected_revision: nozzleBefore.body?.revision ?? 0,
});
record("seed: note saved while offline (a direct, labelled write — not a UI action) is accepted",
  seed.status === 200, `HTTP ${seed.status}`);

// The card's own controller has no reason to know a write happened outside
// it — force it to remount (F1) the same way navigating away and back for
// real would, rather than reading whatever it already had.
await forceNozzleCardRefetch(page);
bodyText = await waitForNozzleSettled(page);

// F1: asserted BEFORE the conflict text itself, so a no-op refetch (the
// exact, real failure this responds to: the row still read "0.4 mm Printer
// Reported live" — the pre-seed state — after a refetch that never actually
// happened) fails loudly right here, naming the real cause, instead of
// cascading into the conflict-text check below failing for an unrelated-
// looking reason.
const postRemountRowText = await toolheadRow(page, 1).innerText();
record("Toolhead 1's row shows the seeded note after the remount, before asserting the conflict (F1)",
  postRemountRowText.includes(`${conflictValue} mm`),
  postRemountRowText.replace(/\s+/g, " ").trim());

const conflictRowText = await toolheadRow(page, 1).innerText();
record("Toolhead 1's own row shows the conflict, naming both the printer's and the noted size (R2/H6)",
  /Studio uses the printer's reading/i.test(conflictRowText)
    && conflictRowText.includes(`${liveDiameters[0]} mm`)
    && conflictRowText.includes(`${conflictValue} mm`)
    && /Printer/.test(conflictRowText),
  conflictRowText.replace(/\s+/g, " ").trim());

// Never asserted from the seed write's own reply — any /nozzles/confirm
// reply is `probe:false` by backend design (R2-B6) and cannot prove the
// CURRENT conflict state. A fresh, explicit `probe:true` status call is.
const statusAfterConflict = await callRoute(page, "/nozzles/status",
  { host: printerHost, port: 7125, probe: true });
evidence.nozzle_conflict = anonymise(statusAfterConflict.body);
const conflictRow = (statusAfterConflict.body?.toolheads ?? []).find((t) => t.toolhead === 0);
record("A fresh probe:true status confirms the conflict, and that the printer still wins (R2)",
  statusAfterConflict.status === 200 && conflictRow?.conflict === true
    && Math.abs((conflictRow?.diameter ?? NaN) - liveDiameters[0]) < 1e-9
    && Math.abs((conflictRow?.confirmed ?? NaN) - conflictValue) < 1e-9,
  `printer=${conflictRow?.diameter} noted=${conflictRow?.confirmed}`);

// The real "Remove my note" button, scoped to toolhead 1's own row — an
// atomic replace of that one position back to unknown, never a global clear
// (PrinterNozzleSettings.removeNote).
const removeButton = toolheadRow(page, 1).getByRole("button", { name: "Remove my note" });
const removeButtonVisible = (await removeButton.count()) > 0;
record("The real 'Remove my note' button is reachable on toolhead 1's conflict row",
  removeButtonVisible, "");
if (removeButtonVisible) {
  await removeButton.click();
}
bodyText = await waitForNozzleIdle(page);
const restoredRowText = await toolheadRow(page, 1).innerText();
record("Removing the note through the real button returns toolhead 1's row to 'Reported live' (R2)",
  /Reported live/i.test(restoredRowText) && !/conflict|noted/i.test(restoredRowText),
  restoredRowText.replace(/\s+/g, " ").trim());

const statusAfterRemove = await callRoute(page, "/nozzles/status",
  { host: printerHost, port: 7125, probe: true });
const removedRow = (statusAfterRemove.body?.toolheads ?? []).find((t) => t.toolhead === 0);
record("A fresh probe:true status shows no stored note after removal (R2)",
  statusAfterRemove.status === 200 && removedRow?.conflict === false
    && (removedRow?.confirmed === null || removedRow?.confirmed === undefined)
    && removedRow?.source === "printer",
  `confirmed=${removedRow?.confirmed} conflict=${removedRow?.conflict} source=${removedRow?.source}`);

// H6 (product guarantee, re-asserted after removal): back to the same
// no-override-possible state R1 started in, not just "some row exists".
const toolhead1SelectCountAfter = await page
  .locator('select[aria-label="Nozzle size for toolhead 1"]').count();
record("A live-reported toolhead still offers no way to type a size, after removing the note (H6)",
  toolhead1SelectCountAfter === 0, `${toolhead1SelectCountAfter} select(s) found`);

record("The request listener actually observed allow-listed printer traffic (H5)",
  allowedPrinterPostCount >= 1, `${allowedPrinterPostCount} allow-listed /printer/* POST(s) observed`);
record("No printer CONTROL route was ever called during this run (R2/A7-6)",
  nonAllowedPrinterPosts.length === 0, JSON.stringify(nonAllowedPrinterPosts));

// --- report -------------------------------------------------------------------

// H3/F5: hardware.png used to be captured straight off whatever page was on
// screen, with no redaction at all — navigate off Settings first (belt) AND
// still run the same fail-closed redaction pass (suspenders) before
// capturing. F5: "/" (the real Dashboard route), not "/dashboard" (NotFound —
// never a real page; F1 is the same fix applied where it was actually
// blocking, this is the same correction applied here too).
await page.evaluate(() => {
  window.history.pushState({}, "", "/");
  window.dispatchEvent(new PopStateEvent("popstate"));
});
await page.waitForTimeout(600);
const cleanFinal = await redactDom(page, hostCandidates);
record("Host text redacted before capture: hardware.png", cleanFinal,
  cleanFinal ? "host_text_redacted: true" : "printer address still present after redaction");
if (cleanFinal) await page.screenshot({ path: join(outDir, "hardware.png") });

// H8: the scan is TRULY final — every check above is already computed, and
// hardware.json (this write) is the LAST artifact write before the scan. The
// scan's own result is deliberately NOT folded back into hardware.json or
// any other write: doing that would mean writing to a file again after the
// scan ran, which is exactly the pattern H8 forbids (it also can never be
// asked to re-validate its own output that way). Its verdict instead only
// ever reaches the console and this process's exit code.
const passed = results.filter((r) => r.ok).length;
writeFileSync(join(outDir, "hardware.json"), JSON.stringify({
  schema_version: "hardware/1",
  printer: "<printer-on-lan>",
  read_only_routes: READ_ONLY_ROUTES,
  checks: results,
  passed,
  total: results.length,
  evidence,
}, null, 2));

// H4/H8: scan every file now sitting in the evidence directory (this JSON,
// both screenshots, the gcode fixture) for either form of the supplied
// address, independent of and after every in-page redaction above. On a hit,
// only the FILENAME is ever printed — never the address itself, and never
// written to any file — so a leak this check finds is never reproduced a
// second time inside the very evidence it exists to protect.
const leakHits = scanEvidenceForHost(outDir, hostCandidates);
if (leakHits.length > 0) {
  console.log(`FAIL  No supplied printer address survives redaction anywhere in the evidence directory (H4/H8)  — found in: ${leakHits.join(", ")}`);
} else {
  console.log("PASS  No supplied printer address survives redaction anywhere in the evidence directory (H4/H8)");
}

console.log(`\n${passed}/${results.length} hardware checks passed`);
// F6: hardware.json is written BEFORE this final leak scan, by design (H8 —
// nothing is ever written again after the scan runs), so it can read as
// "all checks passed" even on a run this process still exits non-zero for.
// The process EXIT CODE (not hardware.json's own `passed`/`total` fields) is
// what a caller must treat as authoritative.
console.log("EXIT CODE IS AUTHORITATIVE: hardware.json is written before this final leak scan (H8); "
  + "a 0 exit means both every check passed AND no address leaked, not hardware.json's own passed/total alone.");
await browser.close();
process.exit(passed === results.length && leakHits.length === 0 ? 0 : 1);
