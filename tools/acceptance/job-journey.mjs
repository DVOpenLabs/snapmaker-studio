// Installed-build acceptance for the v1.7.0 job screen, driven over CDP against the *installed* app.
//
// Usage: node job-journey.mjs <cdpUrl> <outDir> <workDir> <paintedCubeSource> <plainProject>
// Environment: SNAPSTUDIO_ACCEPT_APP_PID (the app's pid, for the native picker), SNAPSTUDIO_ACCEPT_NATIVE_OPEN (native-open.ps1).
//
// What it covers, with synthetic files and a loopback mock Spoolman only: the native Open picker, the job screen's one
// primary action, the painted preview modes (Original / Your choices / U1 copy), compact materials, the explicit
// review-then-confirm step, a separate U1 copy and its read-back, an unreadable and a moved-away project, valid 3MF and
// STL controls, and project switching without stale results. It never opens Snapmaker Orca and never contacts a printer.
//
// Known limitation, kept narrow and visible: opening an unreadable or missing project answers HTTP 500 on
// /compatibility_check and /project_materials where 422 would be correct. Exactly those responses, and the browser's own
// console line for them, are counted as "known" ONLY while a refusal step is running; every other HTTP error, console
// error, page error, crash or off-machine request fails the run.
import { chromium } from "playwright-core";
import http from "node:http";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFileSync, mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";

const [, , cdpUrl, outDir, workDir, cubeSource, plainProject] = process.argv;
const APP_PID = process.env.SNAPSTUDIO_ACCEPT_APP_PID;
const NATIVE_OPEN = process.env.SNAPSTUDIO_ACCEPT_NATIVE_OPEN;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sha = (p) => createHash("sha256").update(readFileSync(p)).digest("hex");
mkdirSync(outDir, { recursive: true });
mkdirSync(workDir, { recursive: true });

const results = [];
// Result details carry basenames only: any drive path (either separator, escaped or not) is replaced before it is logged or saved.
// A path may contain spaces, so the redaction runs to the next quote, bracket or line end (privacy over diagnostic detail).
const scrub = (s) => String(s).replace(/[A-Za-z]:[\\/]+[^"'<>|\r\n]*/g, "<path>").replace(/[\\/]+Users[\\/]+[^"'<>|\r\n]*/gi, "<path>");
const record = (name, ok, detail = "") => {
  detail = scrub(detail);
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`);
  return !!ok;
};

// ---- synthetic fixtures (no real model data) ----------------------------------------------------------------------
const cube = join(workDir, "acceptance_painted_cube.3mf");
copyFileSync(cubeSource, cube);
const stl = join(workDir, "acceptance_shape.stl");
const facets = [[[0, 0, 0], [1, 0, 0], [1, 1, 0]], [[0, 0, 0], [1, 1, 0], [0, 1, 0]], [[0, 0, 1], [1, 1, 1], [1, 0, 1]], [[0, 0, 1], [0, 1, 1], [1, 1, 1]],
  [[0, 0, 0], [1, 0, 1], [1, 0, 0]], [[0, 0, 0], [0, 0, 1], [1, 0, 1]], [[1, 0, 0], [1, 1, 1], [1, 1, 0]], [[1, 0, 0], [1, 0, 1], [1, 1, 1]],
  [[1, 1, 0], [0, 1, 1], [0, 1, 0]], [[1, 1, 0], [1, 1, 1], [0, 1, 1]], [[0, 1, 0], [0, 0, 1], [0, 0, 0]], [[0, 1, 0], [0, 1, 1], [0, 0, 1]]];
writeFileSync(stl, "solid acceptance\n" + facets.map((f) => `facet normal 0 0 0\nouter loop\n${f.map((v) => `vertex ${v[0] * 20} ${v[1] * 20} ${v[2] * 20}`).join("\n")}\nendloop\nendfacet`).join("\n") + "\nendsolid acceptance\n");
const plain = join(workDir, "acceptance_plain.3mf");
copyFileSync(plainProject, plain);
const broken = join(workDir, "acceptance_broken.3mf");
writeFileSync(broken, "this is not a zip archive");
const files = { cube, stl, plain, broken };
const hashes = Object.fromEntries(Object.entries(files).map(([k, v]) => [k, sha(v)]));
const listing = () => readdirSync(workDir).sort();

// ---- loopback mock Spoolman (this script owns it) ---------------------------------------------------------------
const spools = [
  { id: 1, registered: "2026-01-01T00:00:00Z", remaining_weight: 800, filament: { name: "Invented Blue", material: "PLA", color_hex: "1E64F0", weight: 1000, vendor: { name: "Invented" } } },
  { id: 2, registered: "2026-01-01T00:00:00Z", remaining_weight: 700, filament: { name: "Invented Pink", material: "PLA", color_hex: "F04EA0", weight: 1000, vendor: { name: "Invented" } } },
];
const providerHits = [];
const server = http.createServer((req, res) => {
  providerHits.push(req.url);
  if (req.url?.startsWith("/api/v1/spool")) { res.writeHead(200, { "content-type": "application/json", "access-control-allow-origin": "*" }); res.end(JSON.stringify(spools)); }
  else { res.writeHead(404); res.end("{}"); }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const providerAddress = `127.0.0.1:${server.address().port}`;

// ---- page + fault capture ---------------------------------------------------------------------------------------
const browser = await chromium.connectOverCDP(cdpUrl);
const ctx = browser.contexts()[0];
const page = ctx.pages().find((p) => p.url().startsWith("http://tauri.localhost"));
if (!page) throw new Error("the app window was not found over CDP");
let inRefusal = false;
const faults = [], known = [], offMachine = [];
const KNOWN_PATHS = new Set(["/compatibility_check", "/project_materials"]);
// A request is "refusal-scoped" by the moment it is ISSUED (a late response keeps its originating request's scope).
const issuedInRefusal = new WeakMap();
const knownResp = {}, knownConsole = {};
const pathOf = (u) => { try { return new URL(u).pathname; } catch { return "?"; } };
page.on("request", (r) => issuedInRefusal.set(r, inRefusal));
page.on("response", (r) => {
  if (r.status() < 400) return;
  const p = pathOf(r.url());
  if (issuedInRefusal.get(r.request()) === true && r.status() === 500 && KNOWN_PATHS.has(p)) { known.push(`http 500 ${p}`); knownResp[p] = (knownResp[p] || 0) + 1; }
  else faults.push(`http ${r.status()} ${p}`);
});
page.on("crash", () => faults.push("PAGE CRASH event"));
page.on("pageerror", (e) => faults.push("pageerror: " + String(e).slice(0, 200)));
page.on("console", (m) => {
  if (!["error", "warning"].includes(m.type())) return;
  const t = m.text();
  const p = pathOf(m.location()?.url || "");
  // The browser's own line for a refused load is absorbed only for an allowed path; the count is reconciled at the end.
  if (/Failed to load resource: the server responded with a status of 500/.test(t) && KNOWN_PATHS.has(p)) { knownConsole[p] = (knownConsole[p] || 0) + 1; known.push(`console 500 ${p}`); }
  else faults.push(`${m.type()}: ${t.slice(0, 200)}`);
});
page.on("request", (r) => {
  try { const u = new URL(r.url()); if (!["localhost", "127.0.0.1", "tauri.localhost", "ipc.localhost", "asset.localhost"].includes(u.hostname) && !/^(data|blob|about):/.test(r.url())) offMachine.push(u.hostname); } catch { /* ignore */ }
});

// ---- helpers ----------------------------------------------------------------------------------------------------
const jobState = () => page.evaluate(() => {
  const txt = (s) => (document.querySelector(s)?.textContent || "").trim().replace(/\s+/g, " ");
  const p = document.querySelector("[data-primary]");
  return {
    route: location.pathname,
    primary: p ? { kind: p.getAttribute("data-primary"), disabled: p.disabled } : null,
    blocked: txt('[data-testid="job-blocked"]'), openAnother: !!document.querySelector('[data-testid="open-another"]'),
    createButtons: [...document.querySelectorAll("button")].filter((b) => /^Create U1 copy$/.test((b.textContent || "").trim())).map((b) => `disabled=${b.disabled}`),
    slots: document.querySelectorAll('[data-testid="slot-toggle"]').length,
    modes: [...document.querySelectorAll("button[aria-pressed]")].map((b) => `${(b.textContent || "").trim()}:${b.getAttribute("aria-pressed")}${b.disabled ? ":disabled" : ""}`),
    copyName: txt('[data-testid="copy-name"]'), copy: txt('[data-testid="copy-result"]').slice(0, 200),
    previewUnavailable: txt('[data-testid="preview-unavailable"]').slice(0, 160), nothingToShow: txt('[data-testid="nothing-to-show"]'),
    colourView: !!document.querySelector('[data-testid="colour-view"]'), canvas: !!document.querySelector("canvas"),
    legend: txt('[data-testid="legend"]').slice(0, 200),
    body: document.body.innerText.slice(0, 6000),
  };
});
const settle = async () => { await page.waitForSelector('[data-primary], [data-testid="job-blocked"]', { timeout: 30000 }).catch(() => {}); await sleep(2500); };

/** Press the header Open button and drive the app's own native Win32 Open dialog (plain window messages, no UI Automation). */
async function nativeOpen(path, selector = null) {
  const click = (selector ? page.locator(selector) : page.getByRole("button", { name: /^Open$/ }).first()).click({ timeout: 15000 }).then(() => "clicked").catch((e) => "click-failed " + String(e).slice(0, 80));
  const dlg = await new Promise((resolve) => {
    const c = spawn("pwsh", ["-NoProfile", "-File", NATIVE_OPEN, "-OwnerPid", String(APP_PID), "-Path", path, "-TimeoutSec", "25"], { stdio: ["ignore", "pipe", "pipe"] });
    let o = ""; c.stdout.on("data", (x) => (o += x)); c.stderr.on("data", (x) => (o += x));
    c.on("close", (code) => resolve({ ok: code === 0, out: o.replace(/\x1b\[[0-9;]*m/g, "").replace(/\r?\n/g, " / ").slice(0, 200) }));
  });
  await click;
  await sleep(1500);
  return dlg;
}

/** A screenshot is taken only when the page text carries no path, profile folder or private marker; otherwise it is skipped. */
async function safeShot(name) {
  const body = await page.locator("body").innerText();
  const values = await page.evaluate(() => [...document.querySelectorAll("input, textarea")].map((e) => e.value).join(" "));
  const unsafe = /(?<![A-Za-z])[A-Za-z]:[\\/]|[\\/]Users[\\/]|studioclean|[\\/]AppData[\\/]/i.test(body + " " + values);
  if (unsafe) { record(`Screenshot ${name} skipped (page text carried a path)`, true, "not captured"); return; }
  await page.screenshot({ path: join(outDir, `${name}.png`) });
}

let interceptionProven = false;
try {
  // ---- 1. start on a clean Home, native Open -> job screen --------------------------------------------------------
  await sleep(2500);
  // The printer address an earlier phase saved in this profile is cleared so nothing here probes a printer-shaped address.
  await page.evaluate(([addr]) => { localStorage.removeItem("u1Host"); localStorage.setItem("materialProviderKind", JSON.stringify("spoolman")); localStorage.setItem("materialProviderUrl", JSON.stringify(addr)); }, [providerAddress]);
  await page.reload(); await sleep(2500);
  // Fail-closed Orca hand-off guard: the app's open_in_orca command is swallowed (and counted) before any click can reach it.
  // If the interception cannot be installed AND proven, nothing is clicked at all.
  const installed = await page.evaluate(() => {
    try {
      const t = window.__TAURI_INTERNALS__;
      if (!t || typeof t.invoke !== "function") return "no-internals";
      const real = t.invoke.bind(t);
      window.__ipc = [];
      const wrapper = (cmd, args, opts) => {
        if (cmd === "__handoff_probe__") return Promise.resolve("stub-ok");
        if (cmd === "open_in_orca") { window.__ipc.push(cmd); return Promise.resolve(); }
        return real(cmd, args, opts);
      };
      try { t.invoke = wrapper; } catch { return "assign-threw"; }
      return t.invoke === wrapper ? "assigned" : "assign-ignored";
    } catch { return "error"; }
  });
  const proof = installed === "assigned" ? await page.evaluate(async () => { try { return String(await window.__TAURI_INTERNALS__.invoke("__handoff_probe__")); } catch { return "probe-rejected"; } }) : "not-installed";
  // In the shipped webview the IPC bridge's invoke is not writable, so interception is normally UNAVAILABLE. That is recorded as
  // such, never as proven. Protection then rests on the allow-list: this script clicks only named controls (never Open in Orca,
  // never a bare [data-primary]) and aborts on an unexpected primary action.
  interceptionProven = installed === "assigned" && proof === "stub-ok";
  record("Orca hand-off interception state (informational; the script never clicks Open in Orca either way)", true, interceptionProven ? "proven: open_in_orca is swallowed and counted" : `unavailable (${installed}/${proof}); allow-list clicking only`);
  const before = listing();
  let d = await nativeOpen(cube);
  record("Native Open picker takes a project path and opens it", d.ok, d.out);
  await page.waitForSelector("[data-primary]", { timeout: 30000 }).catch(() => {}); await sleep(2500);
  let st = await jobState();
  record("Job screen offers one primary action, Create U1 copy", /this-print/.test(st.route) && st.primary?.kind === "create" && !st.primary.disabled, JSON.stringify(st.primary));
  record("Painted preview draws on a real canvas", st.colourView && st.canvas && !st.previewUnavailable, st.previewUnavailable || "canvas present");
  record("Painted modes: Original on, Your choices disabled before any spool is chosen", st.modes.includes("Original:true") && st.modes.some((m) => /^Your choices:false:disabled/.test(m)), JSON.stringify(st.modes));
  await safeShot("job-01-original");

  // ---- 2. materials, review, explicit confirm, separate copy, read-back ---------------------------------------------
  await page.click('[data-pane-tab="materials"]'); await sleep(600);
  const toggles = page.locator('[data-testid="slot-toggle"]');
  record("Materials: one compact row per filament slot", (await toggles.count()) === 4, `rows=${await toggles.count()}`);
  for (const i of [0, 1]) {
    await toggles.nth(i).click(); await sleep(400);
    const cands = page.locator('[data-testid="slot-panel"] [data-candidate-key]');
    if (await cands.count()) { await cands.nth(i === 0 ? 1 : 0).click(); await sleep(400); }
    await toggles.nth(i).click(); await sleep(300);
  }
  st = await jobState();
  record("After choosing spools the single primary becomes Review materials", st.primary?.kind === "review-materials" && !st.primary.disabled, JSON.stringify(st.primary));
  record("Painted modes: Your choices becomes available", st.modes.some((m) => /^Your choices:(true|false)$/.test(m)), JSON.stringify(st.modes.filter((m) => /choices/.test(m))));
  await page.getByRole("button", { name: /^Your choices$/ }).click(); await sleep(1200);
  await safeShot("job-02-your-choices");
  const primaryKind = await page.locator("[data-primary]").first().getAttribute("data-primary");
  if (primaryKind !== "review-materials") throw new Error(`unexpected primary action "${primaryKind}": not clicked`);
  await page.locator('[data-primary="review-materials"]').click(); await sleep(1200);
  const focusId = await page.evaluate(() => document.activeElement?.id || document.activeElement?.textContent?.trim() || "");
  record("Review materials brings the review control into view and does not prepare by itself", /materials-review|Review/.test(focusId) && (await page.locator('[data-testid="copy-result"]').count()) === 0, "focus=" + focusId.slice(0, 40));
  await page.locator("#materials-review").click(); await sleep(1500);
  const review = await page.evaluate(() => (document.querySelector('[data-testid="review"]')?.innerText || "").length);
  record("The review step is shown before anything is written", review > 0, `${review} chars`);
  record("No copy exists before the explicit confirm", JSON.stringify(listing()) === JSON.stringify(before), listing().join(","));
  await page.getByRole("button", { name: /Prepare with these choices/ }).click();
  await page.waitForSelector('[data-testid="copy-result"]', { timeout: 60000 }).catch(() => {}); await sleep(2500);
  st = await jobState();
  record("A copy was created and the result card names it", !!st.copyName, st.copyName);
  const after = listing();
  const created = after.filter((n) => !before.includes(n));
  record("The copy is a NEW separate file; the original is untouched", created.length >= 1 && created.every((n) => n !== basename(cube)) && sha(cube) === hashes.cube, `${created.length} new file(s)`);
  await safeShot("job-03-copy-result");
  await page.evaluate(() => { window.scrollTo(0, 0); document.querySelectorAll("main, [class*=overflow]").forEach((e) => { try { e.scrollTop = 0; } catch { /* ignore */ } }); }); await sleep(400);
  const u1 = page.getByRole("button", { name: /^U1 copy$/ }).first();
  const stage = page.getByRole("button", { name: /^Open project/ }).first();
  if (!(await u1.isEnabled().catch(() => false)) && (await stage.count())) { await stage.click(); await sleep(1200); }
  const u1On = await u1.isEnabled().catch(() => false);
  record("Painted modes: the U1 copy read-back mode is available once the copy exists", u1On, "");
  if (u1On) {
    await u1.click(); await sleep(1500);
    const s2 = await jobState();
    record("Read-back: the U1 copy view draws and lists the colours read from the copy file", s2.colourView && s2.canvas && /1E64F0|F04EA0/i.test(s2.legend), s2.legend.slice(0, 120));
    await safeShot("job-04-u1-copy-readback");
  }
  record("The original project is still byte-identical", sha(cube) === hashes.cube);

  // ---- 3. refusals (known 500-vs-422 limitation counted separately) -------------------------------------------------
  inRefusal = true;
  d = await nativeOpen(broken); record("Native Open: unreadable project selected", d.ok, d.out);
  await settle(); st = await jobState();
  record("Unreadable: refusal shown once, with its recovery action", !!st.blocked && st.openAnother, st.blocked.slice(0, 120));
  record("Unreadable: no working preparation action", (!st.primary || st.primary.disabled) && st.createButtons.every((c) => /disabled=true/.test(c)), JSON.stringify({ primary: st.primary, create: st.createButtons }));
  record("Unreadable: the model area says only that there is nothing to show", /Nothing to show/.test(st.nothingToShow) && !st.previewUnavailable, st.nothingToShow);
  record("Unreadable: Materials offers nothing", st.slots === 0, `rows=${st.slots}`);
  await safeShot("job-05-unreadable");
  inRefusal = false;                      // the refusal exemption ends before the valid control is opened
  d = await nativeOpen(stl, '[data-testid="open-another"]');
  record("Recovery: Open another project opens the native picker and loads the file", d.ok, d.out);
  await settle(); st = await jobState();
  record("Valid STL control: Create U1 copy is the enabled primary and nothing is refused", st.primary?.kind === "create" && !st.primary.disabled && !st.blocked, JSON.stringify(st.primary));
  record("Valid STL: no stale refusal from the previous file", !st.blocked && !st.openAnother);
  d = await nativeOpen(plain); record("Native Open: valid readable 3MF selected", d.ok, d.out);
  await settle(); st = await jobState();
  record("Valid 3MF control: Create U1 copy enabled, no refusal", st.primary?.kind === "create" && !st.primary.disabled && !st.blocked, JSON.stringify(st.primary));

  // ---- 4. project switching without stale results -------------------------------------------------------------------
  d = await nativeOpen(cube); await settle();
  await page.click('[data-pane-tab="materials"]'); await sleep(500);
  await page.locator('[data-testid="slot-toggle"]').nth(0).click(); await sleep(300);
  await page.locator('[data-testid="slot-panel"] [data-candidate-key]').first().click(); await sleep(500);
  st = await jobState();
  record("Switching: project A has a spool choice and Review materials", st.primary?.kind === "review-materials", JSON.stringify(st.primary));
  d = await nativeOpen(stl); await settle(); st = await jobState();
  record("Switching: project B shows its own title and a fresh Create, none of A's choices", /acceptance_shape/.test(st.body) && st.primary?.kind === "create" && st.slots === 0, JSON.stringify({ primary: st.primary, slots: st.slots }));
  d = await nativeOpen(cube); await settle(); st = await jobState();
  record("Reopening A: earlier choices are not silently reapplied; Create offered fresh", st.primary?.kind === "create" && st.modes.some((m) => /^Your choices:false:disabled/.test(m)), JSON.stringify(st.modes.filter((m) => /choices/.test(m))));

  // ---- 5. a project moved away after opening, reopened from Recent --------------------------------------------------
  d = await nativeOpen(plain); await settle();
  const moved = plain + ".moved";
  renameSync(plain, moved);
  try {
    await page.getByRole("link", { name: /^Home$/ }).first().click().catch(() => page.locator('nav a[href="/"]').first().click()); await sleep(2500);
    const row = page.getByText(basename(plain), { exact: false }).first();
    const listed = (await row.count()) > 0;
    record("The moved project is still listed under Recent projects", listed);
    if (listed) {
      inRefusal = true;
      await row.click(); await settle(); st = await jobState();
      inRefusal = false;
      record("Missing: refusal shown with its recovery action, Create closed", !!st.blocked && st.openAnother && (!st.primary || st.primary.disabled) && st.createButtons.every((c) => /disabled=true/.test(c)), st.blocked.slice(0, 120));
      await safeShot("job-06-missing");
    }
  } finally { renameSync(moved, plain); inRefusal = false; }
  for (const [k, v] of Object.entries(files)) record(`Original fixture unchanged: ${k}`, sha(v) === hashes[k]);
} catch (e) {
  record("The job journey completed without an unexpected error", false, String(e).slice(0, 300));
  try { await safeShot("job-error"); } catch { /* ignore */ }
} finally {
  record("No unexpected console error, page error, crash or HTTP error", faults.length === 0, JSON.stringify(faults.slice(0, 6)));
  const orcaCalls = await page.evaluate(() => (window.__ipc || []).length).catch(() => -1);
  // Informational only: with interception unavailable this is NOT a measurement. The measured check is run.ps1's before/after
  // snapshot of Snapmaker Orca processes around this journey.
  record("Open in Orca invocation count (measured only when interception is proven; otherwise informational)", interceptionProven ? orcaCalls === 0 : true, interceptionProven ? `${orcaCalls} attempt(s) intercepted` : "not measured here; see the process snapshot check");
  const surplus = Object.keys(knownConsole).filter((p) => knownConsole[p] > (knownResp[p] || 0));
  record("Known-limitation console lines are matched by refused responses", surplus.length === 0, surplus.join(", "));
  record("Known limitation observed only in refusal-step requests (HTTP 500 where 422 is correct)", Object.keys(knownResp).every((p) => KNOWN_PATHS.has(p)), `${known.length} known entr(ies): ${[...new Set(known)].join("; ").slice(0, 200)}`);
  record("No off-machine request from the window", offMachine.length === 0, JSON.stringify(offMachine.slice(0, 4)));
  record("The mock provider was reached only from this machine", providerHits.every((u) => u.startsWith("/api/v1/")), `${providerHits.length} request(s)`);
  server.close();
  writeFileSync(join(outDir, "results-job-journey.json"), JSON.stringify({ results, known: known.map(scrub), faults: faults.map(scrub) }, null, 2));
  await browser.close();
}
if (results.some((r) => !r.ok)) process.exit(1);
