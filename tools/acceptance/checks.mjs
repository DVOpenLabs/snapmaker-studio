// Installed-build acceptance checks, driven over the Chrome DevTools Protocol
// against the *installed* Snapmaker Studio — not the dev server.
//
// Tauri renders the UI in WebView2, and WebView2 accepts browser arguments via
// WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS. Launching the installed app with
// `--remote-debugging-port` therefore exposes the real, shipped webview to a
// standard CDP client. That is what makes this a genuine installed-build test
// rather than pixel-poking: every assertion reads the DOM the user sees, and the
// API calls run inside the app's own origin against the frozen sidecar.
//
// Run one phase per invocation so the PowerShell driver can interleave native
// steps (the file dialog) that CDP cannot reach.
//
// Usage: node checks.mjs <phase> <cdpUrl> <outDir> [samplePath] [gcodePath] [paintedPath]
//                        [spoolmanUrl]
//
// The second provider, the probe servers and the seeded spool ids arrive as
// environment variables rather than as more positional arguments. That is
// deliberate: the positions above are the contract this harness already had,
// and a run that predates the second provider must keep working unchanged.
//
// v1.2: added phases spool-nozzle-empty, spool-notes-create,
// spool-edit-validate, spool-record-used, nozzle-confirm,
// spool-nozzle-restored and spool-nozzle-remove — local spool notes and
// per-printer nozzle confirmation (plan v12-plan-final.md, brief W1-W9), all
// against the placeholder host "u1.local" (no printer required). The real-U1
// half of the same feature (a live nozzle reading and a conflict against it)
// is tools/hardware/checks.mjs, run separately with a real printer. Every new
// screenshot goes through shotRedacted()/redactAndAssert() first (A2.3).
//
// v1.2 fix-up (real Windows run, v2 installer): the Nozzles card's status
// fetch against an unreachable printer took 7-9s in practice, so every nozzle
// assertion now polls via waitForNozzleSettled() (up to 25s, returns the
// last-seen state on timeout) instead of racing a fixed wait. Offline, the
// card shows the "no size reported" banner ABOVE 4 rows sourced from the U1
// profile (D-6) — never zero rows — so the empty-state and post-"Remove all"
// checks assert banner-and-rows, and W6's first confirmation is now driven
// through those rows' own selects + Save (a route call remains only as a
// fallback diagnostic). scrollNozzleCardIntoView() brings the Nozzles card
// on screen before v12-nozzle-confirmed, which otherwise only showed the
// Materials card above it.

import { chromium } from "playwright-core";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [, , phase, cdpUrl, outDir, samplePath, gcodePath, paintedPath, spoolmanUrl] = process.argv;

// A material provider is optional everywhere in Studio, so it is optional here.
// Without one, the checks below still prove the important half: that the frozen
// sidecar carries the provider code, refuses an address that is not on the
// user's own network, and answers "unknown" rather than inventing a figure.
// Given one — pass a local Spoolman address as the last argument — they also
// prove the whole path end to end inside the installed build.
mkdirSync(outDir, { recursive: true });

const results = [];
const record = (name, ok, detail = "") => {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`);
};

async function appPage(browser) {
  const ctx = browser.contexts()[0];
  for (const page of ctx.pages()) {
    if (page.url().startsWith("http://tauri.localhost")) return page;
  }
  throw new Error("the app window was not found over CDP");
}

/** Call a documented route from inside the app's own origin. */
async function callRoute(page, route, body) {
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

const shot = async (page, name) => {
  await page.screenshot({ path: join(outDir, `${name}.png`) });
};

/**
 * v1.2 (A2.3/A3.7): before EVERY screenshot that could show a printer address,
 * replace it in text nodes, input/textarea values and the title/aria-label/
 * placeholder/alt attributes, then re-scan and report whether anything still
 * carries it. Returns true ("clean") only when the address is gone everywhere
 * this pass looks; the caller must skip the capture rather than ship a
 * screenshot that still names a real printer.
 */
async function redactAndAssert(page, hostText) {
  if (!hostText) return true;
  const stillPresent = await page.evaluate((needle) => {
    const lower = needle.toLowerCase();
    const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(escaped, "ig");
    const ATTRS = ["title", "aria-label", "placeholder", "alt"];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.nodeValue && re.test(node.nodeValue)) {
        node.nodeValue = node.nodeValue.replace(re, "your printer");
      }
    }
    document.querySelectorAll("input, textarea").forEach((el) => {
      if (el.value && re.test(el.value)) el.value = el.value.replace(re, "your printer");
    });
    document.querySelectorAll("*").forEach((el) => {
      for (const attr of ATTRS) {
        const v = el.getAttribute(attr);
        if (v && re.test(v)) el.setAttribute(attr, v.replace(re, "your printer"));
      }
    });
    const bodyText = (document.body.innerText || "").toLowerCase();
    const inputVals = [...document.querySelectorAll("input, textarea")]
      .map((el) => el.value || "").join(" ").toLowerCase();
    const attrVals = [...document.querySelectorAll("*")]
      .flatMap((el) => ATTRS.map((a) => el.getAttribute(a) || "")).join(" ").toLowerCase();
    return bodyText.includes(lower) || inputVals.includes(lower) || attrVals.includes(lower);
  }, hostText);
  return !stillPresent;
}

/** v1.2 (A6): scrolls the section this capture is meant to document — named
 *  by its own heading text — into view, and confirms it actually landed
 *  inside the viewport, rather than trusting that whatever an earlier phase
 *  last scrolled to is still the right thing on screen. The real bug this
 *  fixes: v12-spool-notes.png captured the Nozzles card, because the page was
 *  still scrolled to wherever the PRIOR phase (nozzle-confirm) had left it. */
async function scrollHeadingIntoView(page, headingPattern) {
  return page.evaluate((pattern) => {
    const re = new RegExp(pattern, "i");
    const heading = [...document.querySelectorAll("p")]
      .find((el) => re.test(el.textContent || ""));
    if (!heading) return false;
    heading.scrollIntoView({ block: "center" });
    const rect = heading.getBoundingClientRect();
    const viewportW = window.innerWidth || document.documentElement.clientWidth;
    const viewportH = window.innerHeight || document.documentElement.clientHeight;
    return rect.top >= 0 && rect.left >= 0 && rect.bottom <= viewportH && rect.right <= viewportW;
  }, headingPattern);
}

/** Redacts, records the outcome (`host_text_redacted: true` on success), and
 *  only ever writes the screenshot when the capture is actually clean. When
 *  `headingPattern` is given (A6), the capture is ALSO skipped unless that
 *  section's own heading is confirmed inside the viewport right before the
 *  screenshot — the previous phase's scroll position is never trusted. */
async function shotRedacted(page, name, hostText, headingPattern) {
  if (headingPattern) {
    await page.waitForTimeout(200); // let a just-completed re-render settle
    const inView = await scrollHeadingIntoView(page, headingPattern);
    record(`Section heading in view before capture: ${name}`, inView,
      inView ? "" : `heading matching /${headingPattern}/i was not found in the viewport`);
    if (!inView) return false;
  }
  const clean = await redactAndAssert(page, hostText);
  record(`Host text redacted before capture: ${name}`, clean,
    clean ? "host_text_redacted: true" : `"${hostText}" still present after redaction`);
  if (clean) await shot(page, name);
  return clean;
}

/** Navigates within the SPA without a full reload, forcing a remount of the
 *  route's components (used to re-fetch nozzle/spool state after a direct
 *  route call changed it under the currently-mounted page). */
async function bounceRoute(page, path) {
  await page.evaluate(() => {
    window.history.pushState({}, "", "/dashboard");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await page.waitForTimeout(400);
  await page.evaluate((p) => {
    window.history.pushState({}, "", p);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, path);
  await page.waitForTimeout(1500);
}

/** Polls the Nozzles card's own DOM until its initial load finishes ("Checking
 *  your printer…" is gone, or a load error is shown) or `timeoutMs` elapses —
 *  status against an unreachable printer has been observed taking 7-9s in a
 *  real run, and a fixed short wait races that rather than proving anything.
 *  Always returns the last-observed body text, settled or not, so a caller
 *  that times out still has real evidence in its failure detail instead of
 *  asserting against a stale/loading DOM. */
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

/** True while the Nozzles card is still loading, or mid-save/mid-clear (its
 *  own Save/Remove all button is disabled) — confirming currently re-probes
 *  the printer (7-9s observed offline), so a click has to be followed by
 *  waiting for this to clear, not a fixed pause. */
async function nozzleCardBusy(page) {
  return page.evaluate(() => {
    const heading = [...document.querySelectorAll("p")]
      .find((el) => /Nozzles · for/i.test(el.textContent || ""));
    const card = heading?.closest("div")?.parentElement || heading;
    if (!card) return true; // the card itself isn't there yet — not settled
    const buttons = [...card.querySelectorAll("button")]
      .filter((b) => /^(Save|Remove all)$/i.test((b.textContent || "").trim()));
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

/** Scrolls the Nozzles card into view — a screenshot naming the Nozzles card
 *  must actually show it, not whatever the Materials card leaves on screen. */
async function scrollNozzleCardIntoView(page) {
  await page.evaluate(() => {
    const heading = [...document.querySelectorAll("p")]
      .find((el) => /Nozzles · for/i.test(el.textContent || ""));
    const card = heading?.closest("div")?.parentElement || heading;
    card?.scrollIntoView({ block: "center" });
  });
  await page.waitForTimeout(300);
}

// --- v1.2 (A3): spool-editor helpers that wait on a real signal — the editor
// opening/closing, or the row's own text changing — rather than a fixed
// sleep, which either raced a slow save or padded every phase with dead time
// for no proof of anything.

/** Scopes every following assertion to exactly one slot's own `<li>` element
 *  — the vacuous-pass Sol flagged came from asserting against the whole page
 *  body, which a completely unrelated row (or the editor's own copy of the
 *  same words) could satisfy just as well. */
function slotRow(page, slotN) {
  return page.locator("li").filter({ hasText: `Slot ${slotN}` });
}

async function slotRowText(page, slotN) {
  return slotRow(page, slotN).innerText();
}

/** v1.2 (real-run fix): polls a slot's own row until its text matches
 *  `pattern`, or `timeoutMs` elapses — always returning the last-observed
 *  text so a timeout still carries real evidence rather than a blind FAIL.
 *
 *  The editor closing is NOT the completion signal for save()/
 *  confirmMarkUsed(): both call `setEditor(null)` BEFORE `await refresh()`
 *  lands (LocalSpoolSettings.tsx), so the editor can detach — and
 *  clickSaveExpectClose() return — while the row list still shows the
 *  PRE-save data. Confirmed by a real run: W4 read Slot 2 immediately after
 *  the editor closed and saw the OLD "750 g · entered by you" instead of the
 *  new "700 g · estimated from what you recorded"; only after a relaunch
 *  (which re-fetches from scratch) did the row read correctly, and W7/W8
 *  then failed only because they compared against that stale snapshot. Every
 *  assertion that reads a slot's row right after a save/confirm must wait
 *  for THIS — the row's own expected content — not the editor's DOM state. */
async function waitForRowText(page, slotN, predicate, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  let text = await slotRowText(page, slotN);
  while (Date.now() < deadline) {
    if (predicate(text)) break;
    await page.waitForTimeout(300);
    text = await slotRowText(page, slotN);
  }
  return text;
}

/** v1.2 (A5): whitespace-normalised exact-match comparison for a slot row's
 *  full text — a substring/regex check could pass even if some OTHER part of
 *  the row (vendor, weight, label) silently changed; this requires the whole
 *  thing to still read exactly the same.
 *
 *  F7 (Opus polish): a remaining-weight label can carry a trailing
 *  "· <date>" (remainingLabel's `fmtAsOf`, locale-formatted via
 *  toLocaleDateString()) — every date-shaped substring is replaced with a
 *  fixed placeholder before comparing, so this snapshot compare is tolerant
 *  of that date (which can legitimately differ, e.g. across a day boundary
 *  during a slow run) while still catching any OTHER change to the row. */
function normalizeRowText(s) {
  return (s || "")
    .replace(/\s+/g, " ")
    .replace(/\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}/g, "<date>")
    .trim();
}

function readSlot2Snapshot(outDir) {
  try {
    return JSON.parse(readFileSync(join(outDir, "slot2-snapshot.json"), "utf8")).text;
  } catch {
    return null;
  }
}

async function openEditorForSlot(page, slotN) {
  await slotRow(page, slotN).getByRole("button", { name: "Edit" }).first().click();
  await page.locator('input[aria-label="Material"]').waitFor({ state: "visible", timeout: 5000 });
}

/** Clicks the editor's Save button and waits for the editor to actually
 *  close (the app's own success signal — save() only calls setEditor(null)
 *  once the request round-trips) rather than a fixed pause that could read
 *  a save still in flight, or that could time out before a slow one lands. */
async function clickSaveExpectClose(page, timeoutMs = 15000) {
  const materialField = page.locator('input[aria-label="Material"]');
  await page.getByRole("button", { name: "Save" }).first().click();
  await materialField.waitFor({ state: "detached", timeout: timeoutMs });
}

async function phaseStartup(page) {
  record("App window present", (await page.title()) === "Snapmaker Studio", await page.title());

  const info = await page.evaluate(() =>
    window.__TAURI_INTERNALS__.invoke("get_api_info"));
  record("Sidecar handshake", Boolean(info?.port && info?.token),
    `port ${info?.port}`);

  const health = await page.evaluate(async () => {
    const i = await window.__TAURI_INTERNALS__.invoke("get_api_info");
    const r = await fetch(`http://127.0.0.1:${i.port}/health`);
    return { status: r.status, body: await r.json() };
  });
  record("Engine /health from the app origin", health.status === 200,
    JSON.stringify(health.body).slice(0, 90));

  // The shipped Rust command table, exercised against the real machine.
  const tools = await page.evaluate(() =>
    window.__TAURI_INTERNALS__.invoke("detect_tools"));
  record("Ecosystem tool detection (shell)", typeof tools === "object",
    `${Object.keys(tools || {}).length} installed tool(s) found: ${Object.keys(tools || {}).join(", ") || "none"}`);

  const orca = await page.evaluate(() =>
    window.__TAURI_INTERNALS__.invoke("detect_orca"));
  record("Snapmaker Orca detection", orca === null || typeof orca === "string",
    orca ? "installed" : "not installed on this machine");

  await shot(page, "01-dashboard");
}

async function phaseRoutes(page) {
  const routes = [
    ["/project_traits", { path: samplePath }, (b) => b.readable === true],
    ["/placement_check", { path: samplePath }, (b) => b.available === true && b.off_plate.length === 1],
    ["/color_plan", { path: samplePath }, (b) => b.color_count === 6 && b.verdict === "possible_with_swaps"],
    // Painted colour, read by the engine this installer actually ships. The
    // project is painted with filament 2 at the bottom and filament 3 thirty
    // millimetres up, so the answers are known before the app is asked: two
    // slots, and a separation the geometry proves.
    ["/project_traits", { path: paintedPath }, (b) => b.has_painted_color?.value === true],
    ["/color_plan", { path: paintedPath },
      (b) => b.painted?.painted === true
        && JSON.stringify(b.painted?.slots) === "[2,3]"
        && b.painted?.painted_facets === 2],
    // The flagship answer: two painted colours whose objects cannot meet on a
    // layer are offered as a planned swap rather than each demanding a toolhead.
    ["/color_plan", { path: paintedPath },
      (b) => b.layer_based.some((c) => c.slot === 3 && c.painted === true
        && Math.abs((c.from_z_mm ?? 0) - 30) < 0.01)],
    ["/color_plan", { path: paintedPath },
      (b) => (b.painted?.coexistence?.pairs ?? []).length > 0
        && (b.painted?.coexistence?.pairs ?? []).every((p) => p.verdict === "separate")],
    ["/project_cost", { path: samplePath }, (b) => b.available === false && Boolean(b.reason)],
    ["/ecosystem_advice", { path: samplePath }, (b) => Boolean(b.primary?.why?.length)],
    ["/preflight", { path: samplePath, host: "", port: 7125 }, (b) => Array.isArray(b.checks) && b.checks.length > 0],
    ["/fix_history", {}, (b) => Array.isArray(b.entries)],
    // The post-slice half. gcodePath is written by the PowerShell driver next to
    // the sample, because a sliced job is the one input the installed build
    // cannot produce for itself — Studio does not slice.
    ["/gcode_facts", { path: gcodePath },
      (b) => b.available === true && b.printer_model === "Snapmaker U1" && b.layer_count === 12],
    ["/post_slice", { path: gcodePath, host: "", port: 7125 },
      (b) => b.available === true && Array.isArray(b.checks) && b.checks.length > 0
             && !b.checks.some((c) => c.result === "blocked" || c.result === "attention")],
    ["/sliced_cost", { path: gcodePath },
      (b) => b.available === true && b.total_grams === 0.36 && b.waste.separable === false],
    ["/diagnostics_preview", {},
      (b) => typeof b.text === "string" && b.text.length > 0 && /Nothing has been sent/.test(b.note)],
    ["/print_plan", { path: gcodePath },
      (b) => b.available === true && b.layers_seen > 0 && Array.isArray(b.narration)
             && b.narration.every((line) => Boolean(line.evidence))],
    ["/material_plan", { path: gcodePath, host: "", port: 7125 },
      (b) => b.available === true && b.printer_known === false],
    // The frozen sidecar carries the provider route at all. Before this sprint
    // the engine had provider support and nothing shipped could reach it, which
    // is exactly the class of gap an installed-build check exists to catch.
    ["/provider/test", { url: "" },
      (b) => b.ok === false && typeof b.reason === "string" && b.reason.length > 0],
    // Local-first is a promise about where requests go. The installed build must
    // refuse a public address rather than fetching it.
    ["/provider/test", { url: "http://example.com" },
      (b) => b.ok === false && /your own network/.test(b.reason ?? "")],
    ["/provider/test", { url: "file:///c:/windows/win.ini" },
      (b) => b.ok === false],
    // And a provider that is simply not there is an answer, not a crash.
    ["/provider/test", { url: "http://127.0.0.1:1" },
      (b) => b.ok === false && b.spools === 0],
    // With no provider configured, nothing about remaining filament is claimed.
    ["/send_check", { path: gcodePath, host: "", port: 7125, spoolman: "" },
      (b) => b.available === true
             && (b.materials?.slots ?? []).every(
                  (s) => (s.sufficiency?.verdict ?? "unknown") === "unknown")],
    ["/send_check", { path: gcodePath, host: "", port: 7125 },
      (b) => b.available === true && b.counts.blocker === 0
             && b.items.some((i) => i.kind === "unknown")],
    // Only when a provider address was supplied: the whole path, in the frozen
    // build. Reading a real Spoolman, mapping a spool to a slot, and getting a
    // figure back with the provenance that decides how hard Studio may lean on it.
    ...(spoolmanUrl ? [
      ["/provider/test", { url: spoolmanUrl },
        (b) => b.ok === true && b.spools > 0 && Array.isArray(b.choices)],
      // The sample job prints from the second slot, so the mapping names the
      // second slot as a person counting from 1 would. Getting that wrong maps a
      // spool into a slot the job never touches, which is exactly the mistake the
      // stated slot numbering exists to prevent.
      ["/material_plan", { path: gcodePath, host: "", port: 7125,
                           spoolman: spoolmanUrl, slot_map: { "2": 2 }, slot_base: 1 },
        (b) => b.available === true && b.printer_known === true
               && (b.slots ?? []).some((s) => s.needed === true
                                              && s.remaining_g !== null
                                              && s.confirmed_by === "provider"
                                              && s.printer_confirmed === false)],
    ] : []),
    // The round-trip: the folder holding the job is watched, and a job that did
    // not come from the open project must never be claimed as a match.
    ["/watch_folder", { folder: outDir },
      (b) => b.available === true && Array.isArray(b.candidates)],
    ["/slice_provenance", { project_path: samplePath, gcode_path: gcodePath },
      (b) => ["confirmed", "likely", "ambiguous", "no_match", "unknown"].includes(b.verdict)],
  ];
  for (const [route, body, verify] of routes) {
    try {
      const { status, body: payload } = await callRoute(page, route, body);
      record(`Engine route ${route}`, status === 200 && verify(payload),
        status === 200 ? "" : `HTTP ${status}`);
    } catch (e) {
      record(`Engine route ${route}`, false, String(e).slice(0, 90));
    }
  }
}

async function phasePostSlice(page) {
  await page.evaluate(() => {
    window.history.pushState({}, "", "/after-slicing");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await page.waitForTimeout(1500);

  let body = await page.locator("body").innerText();
  record("After Slicing page renders", body.includes("After slicing"), "");

  // Type the sliced job's path in, the way a user without a file association would.
  const field = page.locator('input[aria-label="Path to a sliced G-code file"]').first();
  if (await field.count()) {
    await field.fill(gcodePath);
    await page.getByRole("button", { name: /Check this job/i }).first().click();
    // Four cards each read the file and ask the printer. A fixed three seconds
    // asserted against spinners when the printer was slow to answer, which reads
    // as "the app does not render this" and is not what happened.
    for (let waited = 0; waited < 40000; waited += 1000) {
      const text = await page.locator("body").innerText();
      const settling = /checking whether this job is ready|reading the sliced file|checking what is loaded/i;
      if (!settling.test(text)) break;
      await page.waitForTimeout(1000);
    }
  }
  body = await page.locator("body").innerText();
  const has = (s) => body.includes(s);

  record("Sliced job read in the installed app",
    has("What the printer will actually do") && has("Snapmaker Orca"), "");
  // The labels are uppercased by CSS, and innerText returns the transformed
  // text, so this compares case-insensitively rather than against the source.
  const lower = body.toLowerCase();
  record("Job facts rendered from the file",
    lower.includes("prints from") && lower.includes("layers")
    && lower.includes("estimated time"), "");
  record("Post-slice honest unknown present",
    has("Studio can’t tell") || has("Studio can't tell"), "");
  record("Purge is not split when the file does not split it",
    /not separate|will not split|no tool-change purge/i.test(body), "");
  record("No print-success promise after slicing",
    !/will print successfully|guaranteed/i.test(body), "");

  // The three answers that only exist after slicing.
  record("Ready-to-send verdict rendered", lower.includes("ready to send?"), "");
  record("What to load rendered", lower.includes("what to load"), "");
  record("Send confirmation blocks nothing without a printer",
    !/will stop the print/i.test(body), "");

  const planButton = page.getByRole("button", { name: /Read the whole job/i }).first();
  if (await planButton.count()) {
    await planButton.click();
    await page.waitForTimeout(2500);
  }
  const withPlan = await page.locator("body").innerText();
  record("Print plan timeline rendered on request",
    /what happens during this print/i.test(withPlan) && /prints with slot/i.test(withPlan), "");
  record("Timeline keeps its evidence", /evidence/i.test(withPlan), "");
  record("The round-trip watcher is offered", /pick up sliced jobs automatically/i.test(withPlan)
    || /watching for sliced jobs/i.test(withPlan), "");

  // The send button lives with the checks it is based on, and says what it does —
  // or says why it is not there, which is the case a novice hits first.
  record("Sending is offered, or its absence is explained",
    /send this job to the printer/i.test(withPlan)
    || /connect your u1 in printer hub/i.test(withPlan)
    || /cannot reach your printer/i.test(withPlan), "");
  record("Sending never claims to start a print",
    !/start (the|this) print automatically/i.test(withPlan), "");

  await shot(page, "05-after-slicing");
}

async function phaseCockpit(page) {
  await page.evaluate(() => {
    window.history.pushState({}, "", "/this-print");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await page.waitForTimeout(4000);
  const body = await page.locator("body").innerText();
  const lower = body.toLowerCase();

  record("Cockpit renders the job's stages",
    lower.includes("this print") && lower.includes("before slicing")
    && lower.includes("after slicing"), "");
  record("Cockpit shows the real findings, not placeholders",
    /hangs [\d.]+ mm past the \w+ edge/i.test(body), "");
  record("Cockpit keeps the honest unknown",
    lower.includes("studio can’t tell") || lower.includes("studio can't tell"), "");
  record("Cockpit still says Orca slices", /snapmaker orca/i.test(body), "");
  await shot(page, "06-cockpit");
}

/**
 * The half of provenance a person actually reads.
 *
 * The engine can be right about a job and still leave someone unable to act on
 * it. This drives the real page and asserts that the verdict is stated, that the
 * reasoning is reachable, and that a model's object names never appear in it.
 */
async function phaseProvenance(page) {
  await page.evaluate(() => {
    window.history.pushState({}, "", "/after-slicing");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await page.waitForTimeout(1500);
  const field = page.locator('input[aria-label="Path to a sliced G-code file"]').first();
  if (await field.count()) {
    await field.fill(gcodePath);
    await page.getByRole("button", { name: /Check this job/i }).first().click();
    await page.waitForTimeout(3000);
  }

  // The send card gathers a G-code read, a printer probe and a provenance
  // comparison before it can say anything. Waiting a fixed three seconds caught
  // it mid-thought and read the spinner as an empty answer.
  const settled = /what studio compared|no project is open, so studio cannot tell/i;
  for (let waited = 0; waited < 30000; waited += 1000) {
    const text = await page.locator("body").innerText();
    if (settled.test(text)) break;
    await page.waitForTimeout(1000);
  }

  const details = page.getByText(/What Studio compared/i).first();
  const offered = (await details.count()) > 0;
  if (offered) {
    await details.click();
    await page.waitForTimeout(600);
  }
  const body = await page.locator("body").innerText();
  // Opened without a project there is nothing to compare, and that must be said
  // rather than left blank: silence on this page reads as "fine".
  record("Why Studio reads a job as it does is reachable",
    offered || /no project is open, so studio cannot tell/i.test(body),
    offered ? "" : "compared against no open project");
  if (offered) {
    record("The two kinds of evidence are kept apart",
      /identifies the model/i.test(body) && /describes the setup/i.test(body), "");
    record("Object names stay out of the explanation",
      /fingerprints of the object names/i.test(body), "");
  }

  // The expert half: every simplified verdict can show what it was read from,
  // and the page says how old the printer reading is.
  const wheres = page.getByText(/Where this came from/i);
  const count = await wheres.count();
  record("Every verdict can show what it was read from", count > 0, `${count} item(s)`);
  if (count > 0) {
    for (let index = 0; index < Math.min(count, 4); index += 1) {
      await wheres.nth(index).click();
    }
    await page.waitForTimeout(500);
    const expanded = await page.locator("body").innerText();
    record("The disclosure names a source, not a placeholder",
      /g-code|printer|project and job|firmware|traced on a real u1/i.test(expanded), "");
    // The sliced job in this harness is named for the sample project; a source
    // line must never carry a file or model name.
    const model = gcodePath.split(/[\\/]/).pop().replace(/\.gcode$/i, "");
    const sources = expanded.split(/Where this came from/i).slice(1)
      .map((chunk) => chunk.split(/\r?\n/).slice(0, 3).join(" ")).join(" ");
    record("Expert evidence carries no file or model name",
      !sources.toLowerCase().includes(model.toLowerCase()),
      sources.slice(0, 80));
  }
  record("The age of the printer reading is stated, or there is no reading",
    /read from the printer|no printer to check against|cannot reach your printer|connect your u1/i
      .test(body), "");

  await shot(page, "07-provenance");
}

/**
 * The states a person hits on their first evening, driven through the shipped UI.
 *
 * Each one is a place where Studio could say nothing and leave someone stuck. The
 * assertions are not about wording; they are that *something* is said, in the
 * place the person is looking, naming what happened and what to do next.
 *
 * These are the cases reachable without a printer. The rest — an empty slot, the
 * wrong material, not enough filament, a pending upload — are checked against a
 * real U1 by tools/hardware/verify.ps1.
 */
async function phaseNovice(page) {
  await page.evaluate(() => {
    window.history.pushState({}, "", "/after-slicing");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await page.waitForTimeout(1200);

  const field = () => page.locator('input[aria-label="Path to a sliced G-code file"]').first();
  const check = async (path) => {
    // With a job already open the page shows that job; swapping files is what
    // "Choose another file" is for, and it is the route a person takes too.
    if (!(await field().count())) {
      const another = page.getByRole("button", { name: /Choose another file/i }).first();
      if (await another.count()) {
        await another.click();
        await page.waitForTimeout(800);
      }
    }
    if (!(await field().count())) return "";
    await field().fill(path);
    await page.getByRole("button", { name: /Check this job/i }).first().click();
    // Reading a file, probing the printer and comparing to the project all
    // happen before there is anything to read. A fixed wait caught the spinner.
    for (let waited = 0; waited < 20000; waited += 1000) {
      const text = await page.locator("body").innerText();
      if (!/checking whether this job is ready/i.test(text)) return text;
      await page.waitForTimeout(1000);
    }
    return page.locator("body").innerText();
  };

  // The likeliest first mistake: handing Studio the project instead of the slice.
  let body = await check(samplePath);
  record("A project file handed in as a sliced job is named, not shrugged at",
    /project file, not a sliced/i.test(body), body ? "" : "no path field on the page");

  // Something that is not a job at all.
  const notAJob = join(outDir, "notes.gcode");
  writeFileSync(notAJob, "these are my notes about the print, not a program");
  body = await check(notAJob);
  record("A file that is not a sliced job says so",
    /does not look like a sliced g-code file/i.test(body), "");

  // A watched folder with nothing in it yet.
  const emptyFolder = join(outDir, "watch-empty");
  mkdirSync(emptyFolder, { recursive: true });
  const empty = await callRoute(page, "/watch_folder", { folder: emptyFolder });
  record("An empty export folder says what will happen next",
    /nothing new in that folder yet/i.test(empty.body.summary || ""),
    empty.body.summary || "");

  // Two candidates that cannot be told apart must be a question, not a pick.
  const twoFolder = join(outDir, "watch-two");
  mkdirSync(twoFolder, { recursive: true });
  const job = readFileSync(gcodePath);
  writeFileSync(join(twoFolder, "job-a.gcode"), job);
  writeFileSync(join(twoFolder, "job-b.gcode"), job);
  await page.waitForTimeout(2500);            // let both settle
  const two = await callRoute(page, "/watch_folder",
    { folder: twoFolder, project_path: samplePath });
  const seen = (two.body.candidates || []).length;
  record("Two indistinguishable jobs are a question, not a guess",
    seen === 2 && !two.body.best,
    `${seen} candidate(s), best=${two.body.best ?? "none"}`);

  await shot(page, "08-novice");
}

async function phaseUi(page) {
  // The placement finding, read from the DOM the user sees.
  const body = await page.locator("body").innerText();
  const has = (s) => body.includes(s);

  record("Placement finding rendered", has("Object placement") && has("outside the U1"),
    (body.match(/Hangs [\d.]+ mm past the \w+ edge/) || ["no overhang line"])[0]);
  record("Preflight card rendered", has("Before you slice"), "");
  record("Preflight reports an honest unknown", has("Studio can’t tell") || has("Studio can't tell"),
    "");
  record("Not-detected is never called unsupported",
    !/not supported|unsupported/i.test(body), "");
  await shot(page, "02-project-open");
}

async function phasePrepared(page) {
  const body = await page.locator("body").innerText();
  const has = (s) => body.includes(s);
  record("Prepared copy reported", has("Saved as") || has("U1 profile copy"), "");
  record("Fidelity report rendered", has("What survived preparing this copy"), "");
  record("Fidelity lists what was not carried over",
    has("What Studio could not carry over"), "");
  record("Fix ledger rendered", has("Changes Studio made"), "");
  record("Return-to-original offered", has("Return to the original"), "");
  record("Original-untouched wording present",
    has("never modified") || has("was not changed"), "");
  record("Best-tool panel rendered", has("Best tool for this project"), "");
  record("No print-success promise in the prepared view",
    !/guaranteed|will print successfully|100% success/i.test(body), "");
  await shot(page, "03-prepared");
}

const browser = await chromium.connectOverCDP(cdpUrl);
try {
  const page = await appPage(browser);
  if (phase === "startup") await phaseStartup(page);
  else if (phase === "routes") await phaseRoutes(page);
  else if (phase === "ui") await phaseUi(page);
else if (phase === "post-slice") await phasePostSlice(page);
else if (phase === "cockpit") await phaseCockpit(page);
else if (phase === "provenance") await phaseProvenance(page);
else if (phase === "novice") await phaseNovice(page);
  else if (phase === "prepared") await phasePrepared(page);
  else if (phase === "launch-file") {
    // The app was started with the project as an argument; the shell reports it
    // through get_launch_file and the session opens it at startup. The native
    // picker is deliberately not used — see run.ps1 for why it is unreachable.
    const launched = await page.evaluate(() =>
      window.__TAURI_INTERNALS__.invoke("get_launch_file"));
    record("Shell reports the launch file", typeof launched === "string",
      String(launched).split(/[\/]/).pop());
    await page.waitForTimeout(2000);
    // Assert against a surface that names the *open* file, not the dashboard's
    // recent list — a recent list can be populated by an earlier run, so it was
    // proving the wrong thing on a machine that had one.
    await page.evaluate(() => {
      window.history.pushState({}, "", "/compatibility");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await page.waitForTimeout(3500);
    const body = await page.locator("body").innerText();
    record("Session opened the launch file",
      body.includes("demo_u1_showcase") && /using your open 3mf/i.test(body), "");
  } else if (phase === "colours") {
    await page.evaluate(() => {
      window.history.pushState({}, "", "/colors");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await page.waitForTimeout(4000);
    const body = await page.locator("body").innerText();
    record("Colour plan rendered", body.includes("Colours and toolheads"), "");
    const verdictLine = body
      .split(/\r?\n/)
      .find((line) => /\d+ colours?, \d+ toolheads?/.test(line));
    record("Colour verdict stated", Boolean(verdictLine), (verdictLine || "").slice(0, 70));
    record("Toolhead count says where it came from",
      body.includes("did not read this from a printer") || body.includes("your printer reported"),
      "");
    await shot(page, "04-colours");
  } else if (phase === "painted") {
    // The flagship of this release, in the installed build: a painted project is
    // open, and the colours card has to lead with a sentence a beginner can act
    // on and keep the measurements behind it.
    await page.evaluate(() => {
      window.history.pushState({}, "", "/colors");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await page.waitForTimeout(4000);
    const body = await page.locator("body").innerText();
    record("Painted colour is stated in one sentence",
      /painted with \d+ filament colours?/i.test(body),
      (body.split("\n").find((l) => /painted with \d+ filament/i.test(l)) || "").slice(0, 80));
    record("The painting's measurements are available, not shown by default",
      body.includes("What Studio read from the painting"), "");
    record("No raw paint data reaches the page",
      !/paint_color="|mmu_segmentation="/.test(body), "");
    // Bring the painting itself into the frame. The screenshot from this run is
    // what the README shows, and a picture of the claim has to contain it.
    const framed = await page.evaluate(() => {
      const wanted = /painted with \d+ filament/i;
      const leaf = Array.from(document.querySelectorAll("p, span, div"))
        .find((node) => node.children.length === 0 && wanted.test(node.textContent || ""));
      const card = leaf?.closest("div.rounded-md") || leaf;
      card?.scrollIntoView({ block: "center" });
      return Boolean(card);
    });
    record("The painted sentence is on screen, not below the fold", framed, "");
    await page.waitForTimeout(800);
    await shot(page, "09-painted");
  } else if (phase === "provider-default") {
    // A person upgrading from v0.7.2 had no way to configure a provider, so the
    // upgraded app must open with none — and must not quietly contact anything.
    await page.evaluate(() => {
      window.history.pushState({}, "", "/settings");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await page.waitForTimeout(1500);
    const stored = await page.evaluate(() => ({
      kind: localStorage.getItem("materialProviderKind"),
      url: localStorage.getItem("materialProviderUrl"),
    }));
    record("A fresh or upgraded install has no provider configured",
      stored.kind === null && stored.url === null,
      `kind=${stored.kind} url=${stored.url}`);
    const heading = await page.getByText(/Materials provider/i).count();
    record("The materials provider setting is on screen", heading > 0, `${heading} match(es)`);
    // With none chosen, the address box is not even offered.
    const boxes = await page.getByPlaceholder(/spoolman/i).count();
    record("No address is asked for until a provider is chosen", boxes === 0,
      `${boxes} address box(es)`);

  } else if (phase === "provider-configure") {
    // The whole user path, in the installed build: choose, type, test, map.
    await page.evaluate(() => {
      window.history.pushState({}, "", "/settings");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await page.waitForTimeout(1200);
    await page.getByRole("button", { name: /^Spoolman$/ }).first().click();
    await page.waitForTimeout(400);

    const box = page.getByPlaceholder(/spoolman/i).first();
    await box.fill(spoolmanUrl);
    await page.getByRole("button", { name: /Test connection/i }).first().click();
    await page.waitForTimeout(4000);

    const said = await page.getByText(/Spoolman answered with/i).count();
    record("Test connection reports what it found", said > 0, `${said} match(es)`);

    // Two numbers, not one: Spoolman reports a spool's declared size until
    // something prints from it, so "connected" and "useful" differ.
    const tracked = await page.getByText(/with a recent tracked weight Studio can use/i).count();
    record("The report separates spools from usable tracked weights", tracked > 0);

    const options = await page.locator("select option").count();
    record("The spools Spoolman holds are offered for mapping", options > 1,
      `${options} option(s)`);

    // Map the short spool into the slot the sample job actually prints from.
    const shortId = Number(process.env.SNAPSTUDIO_SPOOL_SHORT || 0);
    const mapped = await page.evaluate(([id]) => {
      const selects = [...document.querySelectorAll("select")];
      const target = selects[1] || selects[0];
      if (!target) return false;
      const option = [...target.options].find((o) => o.value === String(id));
      if (!option) return false;
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLSelectElement.prototype, "value").set;
      setter.call(target, String(id));
      target.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }, [shortId]);
    await page.waitForTimeout(800);
    const persisted = await page.evaluate(() => ({
      kind: localStorage.getItem("materialProviderKind"),
      url: localStorage.getItem("materialProviderUrl"),
      map: localStorage.getItem("materialProviderSlotMap"),
      base: localStorage.getItem("materialProviderSlotBase"),
      seen: localStorage.getItem("materialProviderLastSeen"),
    }));
    record("The configuration is written down where a restart can find it",
      mapped && persisted.kind === JSON.stringify("spoolman") && Boolean(persisted.url)
        && Boolean(persisted.seen) && (persisted.map ?? "{}") !== "{}",
      `map=${persisted.map} base=${persisted.base}`);

  } else if (phase === "provider-restored") {
    // After a restart: the settings came back, and they reach the send decision.
    const persisted = await page.evaluate(() => ({
      kind: localStorage.getItem("materialProviderKind"),
      url: localStorage.getItem("materialProviderUrl"),
      map: localStorage.getItem("materialProviderSlotMap"),
    }));
    record("The provider configuration survived a restart",
      persisted.kind === JSON.stringify("spoolman") && Boolean(persisted.url)
        && (persisted.map ?? "{}") !== "{}",
      `kind=${persisted.kind} map=${persisted.map}`);

    const address = JSON.parse(persisted.url);

    // Enough: a tracked, recent weight well above what the job needs.
    const enoughId = Number(process.env.SNAPSTUDIO_SPOOL_ENOUGH || 0);
    const enough = await callRoute(page, "/send_check", {
      path: gcodePath, host: "", port: 7125,
      spoolman: address, slot_map: { "2": enoughId }, slot_base: 1 });
    const enoughSlot = (enough.body?.materials?.slots ?? []).find((s) => s.needed);
    record("A tracked, recent weight above the job's need reads as enough",
      ["enough", "probably_enough"].includes(enoughSlot?.sufficiency?.verdict),
      `${enoughSlot?.label}: ${enoughSlot?.sufficiency?.verdict}`);

    // Short, but only just. The sample job needs a few tenths of a gram, and a
    // tracked weight drifts by more than that between corrections — so a
    // shortfall inside that margin warns and must not refuse. This is the check
    // that keeps Studio from stopping a print over rounding.
    const shortId = Number(process.env.SNAPSTUDIO_SPOOL_SHORT || 0);
    const marginal = await callRoute(page, "/send_check", {
      path: gcodePath, host: "", port: 7125,
      spoolman: address, slot_map: { "2": shortId }, slot_base: 1 });
    const marginalSlot = (marginal.body?.materials?.slots ?? []).find((s) => s.needed);
    record("A shortfall inside the drift of the tracking warns, never refuses",
      marginalSlot?.sufficiency?.verdict === "probably_short"
        && marginal.body?.counts?.blocker === 0,
      `${marginalSlot?.sufficiency?.verdict}, ${marginal.body?.counts?.blocker} blocker(s)`);

    // And a shortfall well outside it does refuse. A job that needs 87 g against
    // a spool with a tenth of a gram left is the sentence worth stopping for, so
    // it is proved here rather than assumed from the smaller case.
    const bigJob = gcodePath.replace(/\.gcode$/i, "_big.gcode");
    writeFileSync(bigJob, `; HEADER_BLOCK_START
; generated by Snapmaker Orca 2.3.4 on 2026-08-25 at 10:00:00
; total layer number: 12
; max_z_height: 2.40
; HEADER_BLOCK_END
; EXECUTABLE_BLOCK_START
PRINT_START
T1
;LAYER_CHANGE
;Z:0.2
G1 X10 Y10 Z0.2 F1200
PRINT_END
; EXECUTABLE_BLOCK_END

; filament used [mm] = 0.00, 29000.00, 0.00, 0.00
; filament used [g] = 0.00, 87.00, 0.00, 0.00
; total filament used [g] = 87.00
; total layers count = 12

; CONFIG_BLOCK_START
; filament_type = PLA;PLA;PLA;PLA
; layer_height = 0.2
; nozzle_diameter = 0.4,0.4,0.4,0.4
; printable_area = 0.5x1,270.5x1,270.5x271,0.5x271
; printer_model = Snapmaker U1
; CONFIG_BLOCK_END
`);
    const short = await callRoute(page, "/send_check", {
      path: bigJob, host: "", port: 7125,
      spoolman: address, slot_map: { "2": shortId }, slot_base: 1 });
    const shortSlot = (short.body?.materials?.slots ?? []).find((s) => s.needed);
    record("A tracked, recent shortfall blocks the send",
      shortSlot?.sufficiency?.verdict === "insufficient"
        && short.body?.counts?.blocker > 0,
      `${shortSlot?.sufficiency?.verdict}, ${short.body?.counts?.blocker} blocker(s)`);

    // Derived: Spoolman reports a spool's declared size until something prints
    // from it. That may warn; it may never refuse.
    const derivedId = Number(process.env.SNAPSTUDIO_SPOOL_DERIVED || 0);
    const derived = await callRoute(page, "/send_check", {
      path: gcodePath, host: "", port: 7125,
      spoolman: address, slot_map: { "2": derivedId }, slot_base: 1 });
    const derivedSlot = (derived.body?.materials?.slots ?? []).find((s) => s.needed);
    record("A weight derived from a spool's declared size never blocks",
      derivedSlot?.sufficiency?.trusted === false
        && derived.body?.counts?.blocker === 0,
      `trusted=${derivedSlot?.sufficiency?.trusted}, ${derived.body?.counts?.blocker} blocker(s)`);

    // Conflict: the mapping says PETG where the job was sliced for PLA. With no
    // printer to see the slot, that is the user's mapping and is said as such.
    const conflictId = Number(process.env.SNAPSTUDIO_SPOOL_CONFLICT || 0);
    const conflict = await callRoute(page, "/material_plan", {
      path: gcodePath, host: "", port: 7125,
      spoolman: address, slot_map: { "2": conflictId }, slot_base: 1 });
    const conflictSlot = (conflict.body?.slots ?? []).find((s) => s.needed);
    record("A material the mapping disagrees about is reported, not resolved",
      conflictSlot?.state === "wrong_material"
        && conflictSlot?.printer_confirmed === false,
      `${conflictSlot?.state}, printer_confirmed=${conflictSlot?.printer_confirmed}`);

    // And turning it off puts the honest unknown back. With nothing loaded and
    // nothing tracking a spool, the slot carries no sufficiency claim at all —
    // which is the honest answer rather than a verdict dressed as one.
    const off = await callRoute(page, "/send_check",
      { path: gcodePath, host: "", port: 7125 });
    const offSlot = (off.body?.materials?.slots ?? []).find((s) => s.needed);
    record("Choosing no provider restores the honest unknown",
      offSlot?.state === "unknown" && offSlot?.remaining_g == null
        && off.body?.counts?.blocker === 0,
      `state=${offSlot?.state} remaining=${offSlot?.remaining_g}`);

  } else if (phase === "provider-wire") {
    // The wire contract, against the frozen sidecar rather than the source tree.
    //
    // Two shapes have to work at once. `spoolman:` is what every client sent
    // before this release and what this harness itself still sends; `provider`
    // plus `provider_url` is what the app sends now. If the older one broke, an
    // upgrading client would silently lose its provider — so it is checked first
    // and on its own.
    const bb = process.env.SNAPSTUDIO_BAMBUDDY_URL || "";
    const spEnough = Number(process.env.SNAPSTUDIO_SPOOL_ENOUGH || 0);
    const bbEnough = Number(process.env.SNAPSTUDIO_BB_ENOUGH || 0);
    const map = { "2": spEnough };
    const usable = (b) => (b.slots ?? []).some(
      (s) => s.needed === true && s.remaining_g !== null
             && s.confirmed_by === "provider" && s.printer_confirmed === false);
    const pick = (b) => {
      const s = (b.slots ?? []).find((x) => x.needed);
      return s && JSON.stringify([s.remaining_g, s.remaining_quality,
                                  s.sufficiency?.verdict, s.confirmed_by]);
    };

    let legacyPlan = null;
    if (spoolmanUrl) {
      legacyPlan = await callRoute(page, "/material_plan", {
        path: gcodePath, host: "", port: 7125,
        spoolman: spoolmanUrl, slot_map: map, slot_base: 1 });
      record("Legacy `spoolman` field still reaches a remaining weight",
        legacyPlan.status === 200 && usable(legacyPlan.body),
        "HTTP " + legacyPlan.status);

      const legacySend = await callRoute(page, "/send_check", {
        path: gcodePath, host: "", port: 7125,
        spoolman: spoolmanUrl, slot_map: map, slot_base: 1 });
      record("Legacy `spoolman` field still reaches the send decision",
        legacySend.status === 200 && legacySend.body?.available === true
          && (legacySend.body?.materials?.slots ?? []).some((s) => s.remaining_g !== null),
        "HTTP " + legacySend.status);

      // The same facts through the new names must produce the same answer. Not
      // similar — the same verdict on the same slot.
      const namedPlan = await callRoute(page, "/material_plan", {
        path: gcodePath, host: "", port: 7125,
        provider: "spoolman", provider_url: spoolmanUrl, slot_map: map, slot_base: 1 });
      record("`provider`/`provider_url` decides exactly what `spoolman` decided",
        namedPlan.status === 200 && pick(namedPlan.body) === pick(legacyPlan.body),
        pick(legacyPlan.body) + " vs " + pick(namedPlan.body));

      const noKind = await callRoute(page, "/provider/test", { url: spoolmanUrl });
      record("`/provider/test` with no provider named still means Spoolman",
        noKind.status === 200 && noKind.body?.ok === true
          && noKind.body?.provider === "spoolman",
        "provider=" + noKind.body?.provider);
    }

    if (bb) {
      const bbPlan = await callRoute(page, "/material_plan", {
        path: gcodePath, host: "", port: 7125,
        provider: "bambuddy", provider_url: bb,
        slot_map: { "2": bbEnough }, slot_base: 1 });
      record("A second provider reaches a remaining weight through the same contract",
        bbPlan.status === 200 && usable(bbPlan.body), "HTTP " + bbPlan.status);

      // The legacy field names Spoolman and nothing else. Pointed at a Bambuddy
      // it must fail as Spoolman failing, never quietly succeed.
      const wrongReader = await callRoute(page, "/provider/test", { url: bb });
      record("The legacy field never silently reads a different provider",
        wrongReader.status === 200 && wrongReader.body?.ok === false
          && wrongReader.body?.provider === "spoolman",
        wrongReader.body?.provider + ": " + String(wrongReader.body?.reason).slice(0, 60));
    }

    const unknown = await callRoute(page, "/provider/test",
      { url: "127.0.0.1:1", provider: "filamentron-9000" });
    record("An unknown provider fails clearly rather than being guessed at",
      unknown.status === 200 && unknown.body?.ok === false
        && /does not know how to read/.test(unknown.body?.reason ?? ""),
      String(unknown.body?.reason).slice(0, 70));

  } else if (phase === "provider-zero-request") {
    // "No provider" as a measurement rather than a claim. The probe counts every
    // request it is sent, so configuring it must move the count and selecting
    // None must not.
    const probe = process.env.SNAPSTUDIO_PROBE_URL || "";
    // Read from this process, not from inside the app. The app's page runs on
    // the `tauri.localhost` origin and is not allowed to fetch an arbitrary
    // local port — and it should not be: the counter is this harness's
    // instrument, and reading it through the thing being measured would make
    // every count one too many.
    const hits = async () => {
      const r = await fetch("http://" + probe + "/__hits");
      return (await r.json()).hits;
    };

    const before = await hits();
    await callRoute(page, "/material_plan", {
      path: gcodePath, host: "", port: 7125,
      provider: "spoolman", provider_url: probe, slot_map: { "2": 1 }, slot_base: 1 });
    const configured = await hits();
    record("A configured provider is actually contacted",
      configured > before, before + " then " + configured);

    // Every shape of "none": no fields at all, an empty legacy field, and a
    // provider named with no address.
    const shapes = [
      ["no provider fields at all", { path: gcodePath, host: "", port: 7125 }],
      ["an empty legacy field", { path: gcodePath, host: "", port: 7125, spoolman: "" }],
      ["a provider named with no address",
        { path: gcodePath, host: "", port: 7125, provider: "spoolman", provider_url: "" }],
    ];
    for (const [label, body] of shapes) {
      const was = await hits();
      const out = await callRoute(page, "/material_plan", body);
      const now = await hits();
      const slot = (out.body?.slots ?? []).find((s) => s.needed);
      record("With " + label + ", no provider request is made and nothing is claimed",
        now === was && out.status === 200 && slot?.remaining_g == null
          && (slot?.sufficiency?.verdict ?? "unknown") === "unknown",
        "hits " + was + "->" + now + ", remaining=" + slot?.remaining_g);
    }

  } else if (phase === "provider-safety") {
    // Address safety through the frozen sidecar. Unit tests prove the function;
    // this proves the shipped binary carries it.
    const refusals = [
      ["a public hostname", "http://example.com", /your own network/],
      ["a public IP", "http://93.184.216.34", /your own network/],
      ["file://", "file:///c:/windows/win.ini", /http or https/],
      ["ftp://", "ftp://192.168.1.9", /http or https/],
      ["credentials in the address", "http://user:pass@192.168.1.9:7912", /username or password/],
      ["a path on the address", "http://192.168.1.9:7912/api/v1", /without a path/],
      ["a query on the address", "http://192.168.1.9:7912/?x=1", /without a path/],
      ["a port that is not a number", "http://192.168.1.9:notaport", /.+/],
      ["an empty address", "", /.+/],
    ];
    for (const [what, url, reason] of refusals) {
      for (const provider of ["spoolman", "bambuddy"]) {
        const out = await callRoute(page, "/provider/test", { url, provider });
        record("Refused for " + provider + ": " + what,
          out.status === 200 && out.body?.ok === false
            && reason.test(out.body?.reason ?? ""),
          String(out.body?.reason).slice(0, 60));
      }
    }
    // And a local address is not swept up with them.
    for (const ok of ["127.0.0.1:7912", "192.168.1.9:7912", "spoolman.local:7912"]) {
      const out = await callRoute(page, "/provider/test", { url: ok, provider: "spoolman" });
      const why = String(out.body?.reason ?? "reached");
      record("A local address is not refused: " + ok,
        out.status === 200
          && !/your own network|http or https|without a path/.test(why),
        why.slice(0, 60));
    }

  } else if (phase === "provider-redirect") {
    // The defect this exists for was real and lived in the shared transport: a
    // local address answering `302` to a public host was followed, and the
    // request left the machine. Both providers must inherit the refusal.
    const redirect = process.env.SNAPSTUDIO_REDIRECT_URL || "";
    for (const provider of ["spoolman", "bambuddy"]) {
      const out = await callRoute(page, "/provider/test", { url: redirect, provider });
      const reason = String(out.body?.reason ?? "");
      record("A redirect off the local network is refused for " + provider,
        out.status === 200 && out.body?.ok === false
          && /not on your own network/.test(reason),
        reason.slice(0, 80));
      // The public host's own answer must never appear. If it did, the request
      // was made and the refusal is cosmetic.
      record("No public response reaches Studio for " + provider,
        !/404|Not Found|<html/i.test(reason), reason.slice(0, 60));
    }
    // The rule is about leaving the network, not about redirects as such.
    const probe = process.env.SNAPSTUDIO_PROBE_URL || "";
    if (probe) {
      const out = await callRoute(page, "/provider/test", { url: probe, provider: "spoolman" });
      record("A provider on the local network is still read normally",
        out.status === 200 && out.body?.ok === true,
        String(out.body?.reason ?? "ok").slice(0, 60));
    }

  } else if (phase === "provider-adversarial") {
    // Values a provider can really hand over that cannot be true. Fail open to
    // unknown; never to "you have plenty". Read from the real Bambuddy, which
    // stores every one of them without complaint.
    const bb = process.env.SNAPSTUDIO_BAMBUDDY_URL || "";
    const cases = [
      ["a negative used weight", Number(process.env.SNAPSTUDIO_BB_NEGATIVE || 0)],
      ["a used weight above the label weight", Number(process.env.SNAPSTUDIO_BB_OVERUSED || 0)],
      ["a 99,000,000 g spool", Number(process.env.SNAPSTUDIO_BB_ABSURD || 0)],
      ["no label weight at all", Number(process.env.SNAPSTUDIO_BB_ZERO || 0)],
    ];
    for (const [what, id] of cases) {
      const out = await callRoute(page, "/material_plan", {
        path: gcodePath, host: "", port: 7125,
        provider: "bambuddy", provider_url: bb, slot_map: { "2": id }, slot_base: 1 });
      const slot = (out.body?.slots ?? []).find((s) => s.needed);
      record(what + " becomes unknown, never enough",
        out.status === 200 && slot?.remaining_g == null
          && (slot?.sufficiency?.verdict ?? "unknown") === "unknown",
        "remaining=" + slot?.remaining_g + " verdict=" + slot?.sufficiency?.verdict);
    }
    // The connection test must still report the inventory rather than falling
    // over on the spools it cannot use.
    const test = await callRoute(page, "/provider/test", { url: bb, provider: "bambuddy" });
    record("A provider full of impossible weights still answers a connection test",
      test.status === 200 && test.body?.ok === true && test.body?.spools > 0,
      test.body?.spools + " spool(s), " + test.body?.with_tracked_weight + " usable");

  } else if (phase === "provider-equivalence") {
    // The claim the second provider exists to test, in the installed build:
    // equivalent facts, equivalent decisions. Each pair below is the same
    // physical situation seeded into both providers through their own APIs.
    const bb = process.env.SNAPSTUDIO_BAMBUDDY_URL || "";
    const bigJob = gcodePath.replace(/\.gcode$/i, "_big.gcode");
    const pairs = [
      ["ENOUGH", gcodePath, Number(process.env.SNAPSTUDIO_SPOOL_ENOUGH || 0),
        Number(process.env.SNAPSTUDIO_BB_ENOUGH || 0), "no blocker"],
      ["TRACKED RECENT SHORT", bigJob, Number(process.env.SNAPSTUDIO_SPOOL_SHORT || 0),
        Number(process.env.SNAPSTUDIO_BB_SHORT || 0), "blocker"],
      ["DERIVED / UNDATED SHORT", bigJob, Number(process.env.SNAPSTUDIO_SPOOL_DERIVED || 0),
        Number(process.env.SNAPSTUDIO_BB_DERIVED || 0), "warning only"],
    ];
    const shape = (r) => {
      const s = (r.body?.materials?.slots ?? []).find((x) => x.needed);
      return { verdict: s?.sufficiency?.verdict, trusted: s?.sufficiency?.trusted,
               quality: s?.remaining_quality, blockers: r.body?.counts?.blocker,
               warnings: r.body?.counts?.warning };
    };
    for (const [label, job, spId, bbId, expected] of pairs) {
      const one = await callRoute(page, "/send_check", {
        path: job, host: "", port: 7125,
        provider: "spoolman", provider_url: spoolmanUrl,
        slot_map: { "2": spId }, slot_base: 1 });
      const two = await callRoute(page, "/send_check", {
        path: job, host: "", port: 7125,
        provider: "bambuddy", provider_url: bb,
        slot_map: { "2": bbId }, slot_base: 1 });
      const a = shape(one), b = shape(two);
      record(label + ": both providers decide the same",
        JSON.stringify(a) === JSON.stringify(b),
        "spoolman=" + JSON.stringify(a) + " bambuddy=" + JSON.stringify(b));
      const blocked = a.blockers > 0;
      const right = expected === "blocker" ? blocked && a.verdict === "insufficient"
        : expected === "warning only" ? !blocked && a.trusted === false
        : !blocked;
      record(label + ": the decision is " + expected, right,
        "verdict=" + a.verdict + " blockers=" + a.blockers + " trusted=" + a.trusted);
    }
    // Unknown, on the provider that can actually produce one.
    const unknown = await callRoute(page, "/send_check", {
      path: gcodePath, host: "", port: 7125, provider: "bambuddy", provider_url: bb,
      slot_map: { "2": Number(process.env.SNAPSTUDIO_BB_ZERO || 0) }, slot_base: 1 });
    const uSlot = (unknown.body?.materials?.slots ?? []).find((s) => s.needed);
    record("UNKNOWN: no false blocker and no invented figure",
      unknown.body?.counts?.blocker === 0 && uSlot?.remaining_g == null,
      "blockers=" + unknown.body?.counts?.blocker + " remaining=" + uSlot?.remaining_g);

    // Archived, on both. A slot mapped to an archived spool must read as
    // archived rather than as a spool that does not exist.
    const archived = [
      ["spoolman", spoolmanUrl, Number(process.env.SNAPSTUDIO_SPOOL_ARCHIVED || 0)],
      ["bambuddy", bb, Number(process.env.SNAPSTUDIO_BB_ARCHIVED || 0)],
    ];
    for (const [provider, url, id] of archived) {
      const out = await callRoute(page, "/material_plan", {
        path: gcodePath, host: "", port: 7125, provider, provider_url: url,
        slot_map: { "2": id }, slot_base: 1 });
      const slot = (out.body?.slots ?? []).find((s) => s.needed);
      const notes = (slot?.notes ?? []).join(" ");
      record("An archived spool is found and flagged on " + provider,
        /archived/i.test(notes) && !/no spool with id/i.test(notes), notes.slice(0, 80));
    }

    // And a mapping pointing at nothing, on both.
    for (const [provider, url] of [["spoolman", spoolmanUrl], ["bambuddy", bb]]) {
      const out = await callRoute(page, "/material_plan", {
        path: gcodePath, host: "", port: 7125, provider, provider_url: url,
        slot_map: { "2": 99999 }, slot_base: 1 });
      const slot = (out.body?.slots ?? []).find((s) => s.needed);
      record("A mapping pointing at nothing is reported on " + provider,
        (slot?.notes ?? []).some((n) => /no spool with id 99999/i.test(n)),
        (slot?.notes ?? []).join(" ").slice(0, 70));
    }

  } else if (phase === "provider-conflict") {
    // The printer is looking at the slot; the provider holds what someone wrote
    // down. When they disagree, both are shown and neither is silently dropped.
    const bb = process.env.SNAPSTUDIO_BAMBUDDY_URL || "";
    const both = [
      ["spoolman", spoolmanUrl, Number(process.env.SNAPSTUDIO_SPOOL_CONFLICT || 0)],
      ["bambuddy", bb, Number(process.env.SNAPSTUDIO_BB_CONFLICT || 0)],
    ];
    for (const [provider, url, id] of both) {
      const out = await callRoute(page, "/material_plan", {
        path: gcodePath, host: "", port: 7125, provider, provider_url: url,
        slot_map: { "2": id }, slot_base: 1 });
      const slot = (out.body?.slots ?? []).find((s) => s.needed);
      record("A material the mapping disagrees about is reported on " + provider,
        slot?.state === "wrong_material" && slot?.printer_confirmed === false,
        slot?.state + ", printer_confirmed=" + slot?.printer_confirmed);
      record("The disagreement does not throw away the weight on " + provider,
        slot?.remaining_g !== null && slot?.remaining_g !== undefined,
        "remaining=" + slot?.remaining_g);
    }

  } else if (phase === "provider-upload-contract") {
    // The upload route, as far as it can honestly be taken with no printer on
    // this network. It must accept both wire shapes and fail for want of a
    // printer, never for a validation reason. Nothing is started or heated.
    const bb = process.env.SNAPSTUDIO_BAMBUDDY_URL || "";
    const shapes = [
      ["the legacy field", { spoolman: spoolmanUrl }],
      ["the named pair", { provider: "spoolman", provider_url: spoolmanUrl }],
      ["a second provider", { provider: "bambuddy", provider_url: bb }],
    ];
    for (const [label, extra] of shapes) {
      const out = await callRoute(page, "/printer/upload_gcode", Object.assign({
        host: "127.0.0.1", port: 7125, path: gcodePath, confirm: true,
        slot_map: { "2": 1 }, slot_base: 1 }, extra));
      const body = JSON.stringify(out.body ?? {});
      record("Upload accepts " + label + " and fails only for want of a printer",
        out.status === 200
          && !/unexpected keyword|slot_base|provider_url.*invalid/i.test(body),
        "HTTP " + out.status + " " + body.slice(0, 90));
    }

  } else if (phase === "provider-spoolease") {
    await page.evaluate(() => {
      window.history.pushState({}, "", "/settings");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await page.waitForTimeout(1200);
    await page.getByRole("button", { name: /^SpoolEase$/ }).first().click();
    await page.waitForTimeout(300);
    const address = process.env.SNAPSTUDIO_SPOOLEASE_URL;
    await page.getByPlaceholder("192.168.1.50").fill(address);
    await page.getByLabel("Security key").fill(process.env.SNAPSTUDIO_SPOOLEASE_KEY);
    await page.getByRole("button", { name: /Test connection/i }).first().click();
    await page.waitForTimeout(1500);
    record("SpoolEase reports safe connection facts",
      await page.getByText(/Connected\. 3 spools\. 2 with usable remaining weight\./).count() > 0);
    const stored = await page.evaluate(() => ({
      kind: localStorage.getItem("materialProviderKind"),
      url: localStorage.getItem("materialProviderUrl"),
      key: localStorage.getItem("materialProviderKey"),
    }));
    record("The SpoolEase key is never persisted", stored.kind === JSON.stringify("spoolease")
      && stored.url === JSON.stringify(address) && stored.key === null);
    const out = await callRoute(page, "/send_check", {
      path: gcodePath, host: "", port: 7125, provider: "spoolease",
      provider_url: address, provider_key: process.env.SNAPSTUDIO_SPOOLEASE_KEY,
      slot_map: { "1": "1" }, slot_base: 1,
    });
    record("The installed send check carries SpoolEase provider status",
      out.status === 200 && out.body?.provider_status?.provider === "spoolease"
        && out.body.provider_status.spools === 3 && out.body.provider_status.with_weight === 2);

  } else if (phase === "provider-spoolease-restored") {
    const stored = await page.evaluate(() => ({
      kind: localStorage.getItem("materialProviderKind"),
      url: localStorage.getItem("materialProviderUrl"),
      key: localStorage.getItem("materialProviderKey"),
    }));
    record("SpoolEase address survives relaunch but its key does not",
      stored.kind === JSON.stringify("spoolease") && Boolean(stored.url) && stored.key === null);
    const out = await callRoute(page, "/provider/test", {
      url: JSON.parse(stored.url ?? '""'), provider: "spoolease",
    });
    record("A relaunched Studio does not send an old SpoolEase key",
      out.status === 200 && out.body?.ok === false && out.body?.error_code === "key_missing");

  } else if (phase === "provider-switch") {
    // Switching provider in the installed UI. A spool id means something only to
    // the provider that issued it, so carrying a mapping across would point at
    // whatever spool happened to share the number.
    await page.evaluate(() => {
      window.history.pushState({}, "", "/settings");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await page.waitForTimeout(1500);

    const names = await page.evaluate(() =>
      [...document.querySelectorAll("button")].map((b) => b.textContent.trim()));
    record("The installed settings offer None, Spoolman and Bambuddy",
      ["None", "Spoolman", "Bambuddy"].every((n) => names.includes(n)),
      names.filter((n) => ["None", "Spoolman", "Bambuddy"].includes(n)).join(", "));

    await page.getByRole("button", { name: /^Bambuddy$/ }).first().click();
    await page.waitForTimeout(700);
    const afterSwitch = await page.evaluate(() => ({
      kind: localStorage.getItem("materialProviderKind"),
      url: localStorage.getItem("materialProviderUrl"),
      map: localStorage.getItem("materialProviderSlotMap"),
    }));
    record("Switching provider drops the other one's address and mapping",
      afterSwitch.kind === JSON.stringify("bambuddy")
        && (afterSwitch.url ?? '""') === '""'
        && (afterSwitch.map ?? "{}") === "{}",
      "kind=" + afterSwitch.kind + " url=" + afterSwitch.url + " map=" + afterSwitch.map);

    const bb = process.env.SNAPSTUDIO_BAMBUDDY_URL || "";
    const box = page.getByPlaceholder(/bambuddy/i).first();
    record("The address box asks for the provider that is selected",
      (await box.count()) > 0);
    await box.fill(bb);
    await page.getByRole("button", { name: /Test connection/i }).first().click();
    await page.waitForTimeout(4000);
    const said = await page.getByText(/Bambuddy answered with/i).count();
    record("Test connection names the provider that answered", said > 0,
      said + " match(es)");

    const bbEnough = Number(process.env.SNAPSTUDIO_BB_ENOUGH || 0);
    const mapped = await page.evaluate(([id]) => {
      const selects = [...document.querySelectorAll("select")];
      const target = selects[1] || selects[0];
      if (!target) return false;
      if (![...target.options].some((o) => o.value === String(id))) return false;
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLSelectElement.prototype, "value").set;
      setter.call(target, String(id));
      target.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }, [bbEnough]);
    await page.waitForTimeout(900);
    const stored = await page.evaluate(() => ({
      kind: localStorage.getItem("materialProviderKind"),
      url: localStorage.getItem("materialProviderUrl"),
      map: localStorage.getItem("materialProviderSlotMap"),
    }));
    record("The second provider's configuration is written down for a restart",
      mapped && stored.kind === JSON.stringify("bambuddy")
        && Boolean(stored.url) && (stored.map ?? "{}") !== "{}",
      "map=" + stored.map);

  } else if (phase === "provider-switch-restored") {
    // After a restart, with Bambuddy configured rather than Spoolman.
    const stored = await page.evaluate(() => ({
      kind: localStorage.getItem("materialProviderKind"),
      url: localStorage.getItem("materialProviderUrl"),
      map: localStorage.getItem("materialProviderSlotMap"),
    }));
    record("The second provider's configuration survived a restart",
      stored.kind === JSON.stringify("bambuddy") && Boolean(stored.url)
        && (stored.map ?? "{}") !== "{}",
      "kind=" + stored.kind + " map=" + stored.map);

    const address = JSON.parse(stored.url ?? '""');
    const slotMap = JSON.parse(stored.map ?? "{}");
    const out = await callRoute(page, "/send_check", {
      path: gcodePath, host: "", port: 7125,
      provider: "bambuddy", provider_url: address, slot_map: slotMap, slot_base: 1 });
    const slot = (out.body?.materials?.slots ?? []).find((s) => s.needed);
    record("The restored second provider reaches the send decision",
      out.status === 200 && slot?.remaining_g !== null && slot?.remaining_g !== undefined,
      "remaining=" + slot?.remaining_g + " verdict=" + slot?.sufficiency?.verdict);

    // Then None, and back to the honest unknown with nothing configured.
    await page.evaluate(() => {
      window.history.pushState({}, "", "/settings");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await page.waitForTimeout(1200);
    await page.getByRole("button", { name: /^None$/ }).first().click();
    await page.waitForTimeout(700);
    const off = await page.evaluate(() => ({
      kind: localStorage.getItem("materialProviderKind"),
      url: localStorage.getItem("materialProviderUrl"),
      map: localStorage.getItem("materialProviderSlotMap"),
    }));
    record("Choosing None leaves no provider configured at all",
      off.kind === JSON.stringify("none") && (off.url ?? '""') === '""'
        && (off.map ?? "{}") === "{}",
      "kind=" + off.kind + " url=" + off.url + " map=" + off.map);

  } else if (phase === "spool-nozzle-empty") {
    // v1.2 W1 + W6a: the empty states for both new Settings cards, and the
    // negative half of W9 — "Record filament used" lives only inside the
    // spool editor, so it must not exist anywhere before one is open.
    await bounceRoute(page, "/settings");
    const quickBody = await page.locator("body").innerText();
    record("Spool notes empty state renders",
      /No notes yet\. Add one when you load a spool/i.test(quickBody), "");
    record("Record filament used is not reachable before any editor is open (W9)",
      !/Record filament used/i.test(quickBody), "");

    // The Nozzles card's own status fetch against an unreachable printer has
    // been observed taking 7-9s in a real run; assert only once it settles,
    // and with the printer offline the card now shows the "no size reported"
    // banner ABOVE 4 rows sourced from the U1 profile (D-6) — not instead of
    // rows, and not zero rows.
    const body = await waitForNozzleSettled(page);
    record("Nozzle empty-state banner renders above the profile-sourced rows (W1/W6)",
      /No nozzle size reported by this printer/i.test(body),
      `last seen: ${body.slice(0, 200)}`);
    const nozzleRowCount = await page
      .locator('select[aria-label^="Nozzle size for toolhead "]').count();
    record("Four rows render from the U1 profile while the printer is unreachable (W1/W6)",
      nozzleRowCount === 4, `${nozzleRowCount} row(s)`);

    await shotRedacted(page, "v12-spool-empty", "u1.local", "Your spool notes · for");
  } else if (phase === "spool-notes-create") {
    // v1.2 W2: two notes made through the real editor — Slot 2 first, so the
    // list reads like a real person's, then Slot 1, which is asserted.
    await bounceRoute(page, "/settings");

    async function setColour(value) {
      await page.evaluate((v) => {
        const input = document.querySelector('input[aria-label="Colour"]');
        const setter = Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype, "value").set;
        setter.call(input, v);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }, value);
    }

    async function addNote(nth, slotNumber, material, vendor, startingG, remainingG) {
      await page.getByRole("button", { name: "Add a note" }).nth(nth).click();
      const materialField = page.locator('input[aria-label="Material"]');
      await materialField.waitFor({ state: "visible", timeout: 5000 });
      await materialField.fill(material);
      await setColour("#1A2B3C");
      await page.locator('input[aria-label="Vendor"]').fill(vendor);
      await page.locator('input[aria-label="Starting weight in grams"]').fill(String(startingG));
      await page.locator('input[aria-label="Remaining weight in grams"]').fill(String(remainingG));
      // A3: wait for the editor to actually close — necessary, but not
      // sufficient (see waitForRowText's own comment: save() closes the
      // editor BEFORE refresh() lands).
      await clickSaveExpectClose(page);
      // Real-run fix: wait for THIS slot's own row to actually show the
      // saved material and label — the row list can still hold the pre-save
      // "Add a note" placeholder for a moment after the editor has already
      // closed.
      await waitForRowText(page, slotNumber,
        (text) => text.includes(material) && /entered by you/i.test(text));
    }

    // Both empty slots at this point, ascending order: index 1 is Slot 2.
    await addNote(1, 2, "PLA", "Acme Filaments", 1000, 750);
    // After that save, the remaining empty slots are 0, 2, 3 — index 0 is
    // Slot 1 again.
    await addNote(0, 1, "PLA", "Acme Filaments", 1000, 750);

    // A2: scoped to each slot's own row, not the whole page body — asserting
    // against the whole body let an unrelated row (or the editor's own
    // leftover copy of the same words) satisfy the check just as well.
    const slot1Text = await slotRowText(page, 1);
    const slot1Ok = /PLA/.test(slot1Text) && /entered by you/i.test(slot1Text);
    record("Slot 1's row shows the material and 'entered by you' (W2)",
      slot1Ok, slot1Text.replace(/\s+/g, " ").slice(0, 140));
    const slot2Text = await slotRowText(page, 2);
    const slot2Ok = /PLA/.test(slot2Text) && /entered by you/i.test(slot2Text);
    record("Slot 2's row shows the material and 'entered by you' (W2)",
      slot2Ok, slot2Text.replace(/\s+/g, " ").slice(0, 140));

    // A6: capture only once both rows actually show their saved text — not
    // merely once the Save clicks returned.
    if (slot1Ok && slot2Ok) {
      await shotRedacted(page, "v12-spool-notes", "u1.local", "Your spool notes · for");
    } else {
      record("Screenshot skipped: v12-spool-notes", false,
        "Slot 1 and/or Slot 2 did not yet show their saved text — see the checks above");
    }
  } else if (phase === "spool-edit-validate") {
    // v1.2 W3/W5/W9: editing an existing note, the tri-state clear rule
    // (A2.2/A3.3), and both invalid-input cases. Every assertion below reads
    // Slot 1's own row, not the whole page body (A2) — the desktop app's
    // buildSpoolSaveBody() only ever resends a weight the user actually
    // touched (startingGTouched/remainingGTouched), so W3a below leaves the
    // weight field completely untouched rather than clearing it: that is the
    // real "material only" edit, and it is what makes the backend's identity
    // -change reset (A2.2) the thing actually being proven, not a clear.
    await openEditorForSlot(page, 1);

    const usedButtons = await page.getByRole("button", { name: /Record filament used/i }).count();
    record("Record filament used is reachable only from the open editor, and only there (W9)",
      usedButtons === 1, `${usedButtons} button(s) while an editor is open`);

    // W3a: change MATERIAL ONLY — the weight fields are never touched at all.
    // Real-run fix: wait for Slot 1's own row, not just the editor closing —
    // save() calls setEditor(null) before refresh() lands, so the row list
    // can still hold the pre-save text for a moment after the editor's DOM
    // has already detached.
    await page.locator('input[aria-label="Material"]').fill("PETG");
    await clickSaveExpectClose(page);
    let slot1Text = await waitForRowText(page, 1, (text) => /no weight recorded/i.test(text));
    record("Changing the material only (weight field never touched) resets that weight (W3a/A2.2)",
      /no weight recorded/i.test(slot1Text), slot1Text);

    // W3b setup: give Slot 1 a real weight again, so the next step has one to
    // prove survives a clear.
    await openEditorForSlot(page, 1);
    await page.locator('input[aria-label="Remaining weight in grams"]').fill("500");
    await clickSaveExpectClose(page);
    slot1Text = await waitForRowText(page, 1,
      (text) => /500 g/.test(text) && /entered by you/i.test(text));
    record("A weight can be set again on the same row (W3b setup)",
      /500 g/.test(slot1Text) && /entered by you/i.test(slot1Text), slot1Text);

    // W3b: clear an unrelated field (vendor) — the weight field is untouched
    // this time too, so this proves clearing is never an identity change,
    // not merely that an untouched field survives its own no-op.
    await openEditorForSlot(page, 1);
    await page.locator('input[aria-label="Vendor"]').fill("");
    await clickSaveExpectClose(page);
    slot1Text = await waitForRowText(page, 1,
      (text) => !text.includes("Acme") && /500 g/.test(text) && /entered by you/i.test(text));
    record("Clearing an unrelated field leaves the already-set weight shown (W3b/A2.2)",
      !slot1Text.includes("Acme") && /500 g/.test(slot1Text) && /entered by you/i.test(slot1Text), slot1Text);

    // W5: an invalid colour. The editor's colour field is a native colour
    // picker, which cannot hold a malformed string, so this is asserted at
    // the very route the UI itself calls — still against the installed,
    // frozen sidecar. Labelled as an API-level check, per A2.
    const badColour = await callRoute(page, "/local_spools/save",
      { host: "u1.local", slot: 2, material: "PLA", color: "not-a-colour" });
    record("API-level check (native colour input cannot hold an invalid value): "
      + "an invalid colour is refused by the installed sidecar (W5)",
      badColour.status === 400 && badColour.body?.error === "invalid_color",
      `HTTP ${badColour.status} ${JSON.stringify(badColour.body)}`.slice(0, 90));
    const afterBadColour = await callRoute(page, "/local_spools", { host: "u1.local" });
    const afterBadColourRows = afterBadColour.body?.rows;
    // A7-5: fails on a missing/malformed rows array rather than defaulting to
    // "empty" (`?? []`) — a broken response with no rows key at all used to
    // read as "no row", exactly like a genuine empty list would.
    record("The refused colour created no row (W5)",
      Array.isArray(afterBadColourRows) && !afterBadColourRows.some((r) => r.slot === 2),
      Array.isArray(afterBadColourRows) ? `${afterBadColourRows.length} row(s)` : "rows array missing/malformed");

    // W5: an out-of-range weight, through the real form — an inline error,
    // and nothing is saved. F3 (fix-round-3, Sol 3 BLOCKING — supersedes the
    // round-2/A4 attempt): counts REQUESTS, not responses — the product's own
    // validateSpoolForm()/save() checks client-side before ever calling the
    // API, so the correct, stronger claim is that no request is issued AT
    // ALL, not merely that none of the requests that were issued happened to
    // succeed. The listener stays attached until the page is network-idle
    // (no in-flight requests) before detaching, so a request that fired but
    // had not yet resolved when the inline error appeared is still counted.
    await page.getByRole("button", { name: "Add a note" }).first().click();
    const newMaterialField = page.locator('input[aria-label="Material"]');
    await newMaterialField.waitFor({ state: "visible", timeout: 5000 });
    await newMaterialField.fill("PLA");
    await page.locator('input[aria-label="Remaining weight in grams"]').fill("20000");
    const inlineError = page.getByText(/Weight must be between 0 and 10000 grams/i);

    const saveRequests = [];
    const onSaveRequest = (req) => {
      if (req.method() === "POST" && req.url().includes("/local_spools/save")) {
        saveRequests.push(req.url());
      }
    };
    page.on("request", onSaveRequest);
    await page.getByRole("button", { name: "Save" }).first().click();
    await inlineError.waitFor({ state: "visible", timeout: 5000 });
    await page.waitForLoadState("networkidle").catch(() => {});
    page.off("request", onSaveRequest);
    record("Zero POSTs to /local_spools/save were issued during the invalid-weight attempt (F3)",
      saveRequests.length === 0, `${saveRequests.length} request(s) observed`);

    record("An out-of-range weight shows an inline error, not a silent failure (W5)",
      (await inlineError.count()) > 0, "");
    record("The editor is still open — the save did not silently succeed (W5)",
      (await newMaterialField.count()) > 0, "");
    const afterBadWeight = await callRoute(page, "/local_spools", { host: "u1.local" });
    const afterBadWeightRows = afterBadWeight.body?.rows;
    // A4/A7-5: same non-vacuous shape as the colour case above.
    record("The rejected weight created no row (W5)",
      Array.isArray(afterBadWeightRows) && !afterBadWeightRows.some((r) => r.slot === 2
        && r.material === "PLA" && r.remaining_g === 20000),
      Array.isArray(afterBadWeightRows) ? `${afterBadWeightRows.length} row(s)` : "rows array missing/malformed");
    await page.getByRole("button", { name: "Cancel" }).first().click();
  } else if (phase === "spool-record-used") {
    // v1.2 W4: the editor's secondary "Record filament used" action, through
    // its confirm step, on the slot that still carries a weight.
    await bounceRoute(page, "/settings");
    await openEditorForSlot(page, 2);
    await page.getByRole("button", { name: /^Record filament used$/i }).first().click();
    const gramsField = page.locator('input[aria-label="Grams used"]');
    await gramsField.waitFor({ state: "visible", timeout: 5000 });
    await gramsField.fill("50");
    await page.getByRole("button", { name: /Record 50 g used/i }).first().click();
    const confirmButton = page.getByRole("button", { name: "Confirm" }).first();
    await confirmButton.waitFor({ state: "visible", timeout: 5000 });
    await confirmButton.click();
    // A2 (W4): confirmMarkUsed() closes the editor on success (setEditor(null))
    // — necessary, but NOT the completion signal: confirmMarkUsed() calls
    // setEditor(null) BEFORE `await refresh()` lands (LocalSpoolSettings.tsx),
    // so the editor can finish closing while the row list still shows the
    // OLD weight. A real run confirmed exactly this: this check read Slot 2
    // right after the editor closed and saw the stale "750 g · entered by
    // you" instead of the new "700 g · estimated from what you recorded" —
    // it only read correctly after a relaunch (a full re-fetch), and W7/W8
    // then failed only because they compared against the stale snapshot this
    // phase wrote. Fixed: wait for the editor to close (still necessary —
    // confirms the request didn't fail), THEN poll Slot 2's own row (real
    // content, ≤15s) until it actually reads the new label, before asserting
    // or writing the snapshot.
    await page.locator('input[aria-label="Material"]').waitFor({ state: "detached", timeout: 15000 });
    const slot2Text = await waitForRowText(page, 2,
      (text) => /estimated from what you recorded/i.test(text));
    record("Slot 2's own row shows an estimate, never a claimed measurement (W4)",
      /estimated from what you recorded/i.test(slot2Text), slot2Text);
    // A5: this is the reference snapshot W7/W8 compare Slot 2's full row
    // against, byte-for-byte (normalised for whitespace only) — not a
    // substring/regex check, which could pass even if some other part of the
    // row silently changed.
    writeFileSync(join(outDir, "slot2-snapshot.json"), JSON.stringify({ text: slot2Text }));
  } else if (phase === "nozzle-confirm") {
    // v1.2 W6: confirming nozzle sizes with no printer present. Offline, 4
    // rows render from the U1 profile (D-6) once the status fetch settles —
    // drive the confirmation through the real selects and Save button, the
    // way a person actually would. A direct route call is kept only as a
    // fallback diagnostic if those rows somehow are not there.
    await bounceRoute(page, "/settings");
    let body = await waitForNozzleSettled(page);
    const selects = page.locator('select[aria-label^="Nozzle size for toolhead "]');
    const rowCount = await selects.count();
    record("Four profile-sourced rows are available to confirm against, offline (W6 setup)",
      rowCount === 4, `${rowCount} row(s) after settling; last seen: ${body.slice(0, 200)}`);

    if (rowCount === 4) {
      await selects.nth(0).selectOption("0.4");
      await selects.nth(1).selectOption("0.4");
      await selects.nth(2).selectOption("0.6");
      await selects.nth(3).selectOption("not_sure");
      await page.getByRole("button", { name: "Save" }).first().click();
      // Confirm currently re-probes the printer (7-9s observed offline); wait
      // for the Save button to re-enable and the loading text to clear rather
      // than assert while the save is still in flight.
      body = await waitForNozzleIdle(page);
    } else {
      // Fallback diagnostic only — not what W6 itself is asserting, but keeps
      // the rest of this phase (and W7/W8 downstream) informative rather than
      // silent when the offline row count did not come up as expected.
      const before = await callRoute(page, "/nozzles/status", { host: "u1.local", port: 7125 });
      const confirmedDiag = await callRoute(page, "/nozzles/confirm", {
        host: "u1.local", port: 7125, diameters: [0.4, 0.4, 0.6, null],
        expected_revision: before.body?.revision ?? 0,
      });
      record("Fallback diagnostic: the sidecar route still accepts a confirmation",
        confirmedDiag.status === 200,
        `HTTP ${confirmedDiag.status} — UI row count was ${rowCount}, not 4; see the check above`);
      body = await waitForNozzleSettled(page);
    }

    const confirmedCount = (body.match(/Confirmed by you/g) || []).length;
    record("Toolheads 1-3 render as confirmed by you (W6)", confirmedCount === 3,
      `${confirmedCount} row(s); last seen: ${body.slice(0, 200)}`);
    record("Toolhead 4 ('Not sure') renders as unknown, not guessed at (W6)",
      /Unknown — tell Studio/.test(body), "");

    // A6: shotRedacted's own heading-in-view check (below) supersedes the
    // separate scrollNozzleCardIntoView() call this used to make — same
    // scroll target, now also asserted, not just attempted.
    await shotRedacted(page, "v12-nozzle-confirmed", "u1.local", "Nozzles · for");
  } else if (phase === "spool-nozzle-restored") {
    // v1.2 W7: after the app was closed and relaunched (the existing
    // relaunch mechanism — see run.ps1's painted-project restart), each
    // slot's OWN row text must still be there (A2) — not just some mention of
    // the slot number anywhere on the page.
    await bounceRoute(page, "/settings");
    const slot1Text = await slotRowText(page, 1);
    record("Slot 1's own row text survives an app relaunch (W7)",
      /PETG/.test(slot1Text) && /500 g/.test(slot1Text) && /entered by you/i.test(slot1Text),
      slot1Text.replace(/\s+/g, " ").slice(0, 140));
    // A5: Slot 2's FULL row, compared byte-for-byte (whitespace-normalised)
    // against the snapshot taken right after W4 — not a substring check, so
    // a change to material/vendor/weight/label anywhere in the row is caught,
    // not only a change to the one phrase being pattern-matched.
    const slot2Text = await slotRowText(page, 2);
    const slot2Snapshot = readSlot2Snapshot(outDir);
    record("Slot 2's full row is identical before/after the relaunch (A5/W7)",
      slot2Snapshot != null && normalizeRowText(slot2Text) === normalizeRowText(slot2Snapshot),
      `before="${slot2Snapshot}" after="${normalizeRowText(slot2Text)}"`.slice(0, 220));

    const body = await waitForNozzleSettled(page);
    const confirmedCount = (body.match(/Confirmed by you/g) || []).length;
    record("Nozzle confirmations survive an app relaunch (W7)",
      confirmedCount === 3 && /Unknown — tell Studio/.test(body),
      `${confirmedCount} confirmed row(s); last seen: ${body.slice(0, 200)}`);
  } else if (phase === "spool-nozzle-remove") {
    // v1.2 W8: removing every nozzle note, deleting one spool note, and
    // switching provider kind twice — none of which may touch the other.
    await bounceRoute(page, "/settings");
    await waitForNozzleSettled(page); // "Remove all" only exists once the card has settled

    await page.getByRole("button", { name: "Remove all" }).first().click();
    // Same re-probe as Save (above) — wait for the button to re-enable and the
    // loading text to clear before reading the result.
    let body = await waitForNozzleIdle(page);
    // Offline, removing every confirmation returns to the same profile-sourced
    // shape as the very first load (D-6): the banner ABOVE 4 unknown rows —
    // not zero rows, since the U1 profile's toolhead count does not depend on
    // whether the user has confirmed anything.
    record("Removing every nozzle note returns to the profile-sourced empty state (W8)",
      /No nozzle size reported by this printer/i.test(body), `last seen: ${body.slice(0, 200)}`);
    const nozzleRowCountAfterRemove = await page
      .locator('select[aria-label^="Nozzle size for toolhead "]').count();
    record("The 4 profile-sourced rows are still there after removing every note (W8)",
      nozzleRowCountAfterRemove === 4, `${nozzleRowCountAfterRemove} row(s)`);
    // A2: the specific, non-vacuous claim — zero rows read as confirmed any
    // more, not just that the banner text happens to be present.
    const confirmedAfterRemoveAll = (body.match(/Confirmed by you/g) || []).length;
    record("Zero rows read as 'Confirmed by you' after Remove all (W8)",
      confirmedAfterRemoveAll === 0, `${confirmedAfterRemoveAll} row(s); last seen: ${body.slice(0, 200)}`);

    // A5: Slot 2's full row, compared against the same reference snapshot W7
    // uses, right before touching Slot 1 at all — establishes the baseline
    // this phase's own actions must not disturb.
    const slot2Snapshot = readSlot2Snapshot(outDir);
    let slot2Text = await slotRowText(page, 2);
    record("Slot 2's full row matches the reference snapshot, just before deleting Slot 1 (A5/W8 setup)",
      slot2Snapshot != null && normalizeRowText(slot2Text) === normalizeRowText(slot2Snapshot),
      `snapshot="${slot2Snapshot}" now="${normalizeRowText(slot2Text)}"`.slice(0, 220));

    // A2/A3: wait for Slot 1's own row to actually turn into its empty-state
    // "Add a note" li (the real signal the delete round-tripped), not a
    // fixed pause.
    const slot1Empty = page.locator("li").filter({ hasText: "Slot 1" }).filter({ hasText: "Add a note" });
    await slotRow(page, 1).getByRole("button", { name: "Remove" }).first().click();
    await slot1Empty.waitFor({ state: "visible", timeout: 10000 });
    record("Deleting Slot 1's note shows 'Add a note' for that slot, and only that slot (W8)",
      (await slot1Empty.count()) === 1, "");

    // A5: Slot 2's full row, again against the same snapshot, now AFTER
    // deleting Slot 1 — "identical before/after", not merely "still mentions
    // the estimate somewhere".
    slot2Text = await slotRowText(page, 2);
    record("Slot 2's full row is identical before/after deleting Slot 1's note (A5/W8)",
      slot2Snapshot != null && normalizeRowText(slot2Text) === normalizeRowText(slot2Snapshot),
      `snapshot="${slot2Snapshot}" after="${normalizeRowText(slot2Text)}"`.slice(0, 220));

    // Provider kind change never touches a local note (D-1/A1.3). A7-8: waits
    // on the address input's own appear/disappear — a real, synchronous
    // local-state signal (MaterialProviderSettings renders it only when
    // kind !== "none") — instead of a fixed pause.
    const providerAddressField = page.getByPlaceholder(/spoolman/i);
    await page.getByRole("button", { name: /^Spoolman$/ }).first().click();
    await providerAddressField.waitFor({ state: "visible", timeout: 5000 });
    slot2Text = await slotRowText(page, 2);
    record("Switching provider kind to Spoolman leaves Slot 2's note untouched (W8)",
      slot2Snapshot != null && normalizeRowText(slot2Text) === normalizeRowText(slot2Snapshot),
      normalizeRowText(slot2Text).slice(0, 140));
    await page.getByRole("button", { name: /^None$/ }).first().click();
    await providerAddressField.waitFor({ state: "detached", timeout: 5000 });
    slot2Text = await slotRowText(page, 2);
    record("Switching provider kind back to None leaves Slot 2's note untouched (W8)",
      slot2Snapshot != null && normalizeRowText(slot2Text) === normalizeRowText(slot2Snapshot),
      normalizeRowText(slot2Text).slice(0, 140));
  } else if (phase === "goto-compatibility") {
    await page.evaluate(() => {
      window.history.pushState({}, "", "/compatibility");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await page.waitForTimeout(2500);
    console.log("navigated");
  } else if (phase === "prepare") {
    await page.getByRole("button", { name: /Prepare U1 copy/i }).first().click();
    await page.waitForTimeout(6000);
    console.log("prepared");
  } else {
    throw new Error(`unknown phase ${phase}`);
  }
} finally {
  writeFileSync(join(outDir, `results-${phase}.json`), JSON.stringify(results, null, 2));
  await browser.close();
}

if (results.some((r) => !r.ok)) process.exit(1);
