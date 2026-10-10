#!/usr/bin/env node
// Browser check + screenshots of the "Print risk signals" card on Design Health (Windows).
//
//   node tools/acceptance/readiness-findings-ui.mjs --out <folder>
//
// Starts, on this machine and stopped again at the end: the real Studio engine (throwaway data folder) and this checkout's
// own Studio web UI (a vite dev server). Opens two anonymous models with no printer reachable, in light and dark: one that
// raises signals and one that raises none. Checks the card lists signals with what to do, says what was and was not checked,
// and never shows a percentage, band or "Likely to print" verdict (#92). Any engine request naming a host other than this machine, or discovery,
// is aborted and fails the run (the only printer address is this machine's own, where nothing listens).
//
// The browser is Microsoft Edge, not the Tauri window, WebKitGTK or a screen reader.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import http from "node:http";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

if (process.platform !== "win32") { console.error("This check is written for Windows (taskkill, npx.cmd)."); process.exit(2); }
const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");
const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");
const out = process.argv.includes("--out") ? process.argv[process.argv.indexOf("--out") + 1] : join(tmpdir(), "readiness-findings");
mkdirSync(out, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const children = [];
let cleaned = false;
function cleanup() {
  if (cleaned) return;
  cleaned = true;
  for (const c of children) { try { spawnSync("taskkill", ["/PID", String(c.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* gone */ } }
}
process.on("exit", cleanup);
for (const sig of ["SIGINT", "SIGTERM", "SIGBREAK"]) process.on(sig, () => { cleanup(); process.exit(130); });

/* ---------- two anonymous models in a throwaway folder ---------- */
const work = mkdtempSync(join(tmpdir(), "readiness-ui-"));
const flagged = join(work, "example-project.3mf");
const clean = join(work, "example-cube.stl");
copyFileSync(join(repo, "examples", "demo_offplate_foreign.3mf"), flagged);
// A 20 mm cube standing on the plate: nothing for the checks to flag.
{
  const v = [0, 1].flatMap((c) => [0, 1].flatMap((b) => [0, 1].map((a) => [100 + a * 20, 100 + b * 20, c * 20])));
  const quads = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]];
  const tris = quads.flatMap(([a, b, c, d]) => [[v[a], v[b], v[c]], [v[a], v[c], v[d]]]);
  const buf = Buffer.alloc(84 + 50 * tris.length);
  buf.writeUInt32LE(tris.length, 80);
  tris.forEach((t, i) => { const o = 84 + 50 * i; t.flat().forEach((n, j) => buf.writeFloatLE(n, o + 12 + 4 * j)); });
  writeFileSync(clean, buf);
}

/* ---------- engine + UI ---------- */
const backend = spawn(process.env.PYTHON || "py", ["-m", "snapstudio_api"], {
  cwd: join(repo, "backend"), stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, SNAPSTUDIO_DATA_DIR: join(work, "data"), PYTHONPATH: join(repo, "backend"), PYTHONUNBUFFERED: "1" },
});
children.push(backend);
const handshake = await new Promise((resolve, reject) => {
  let buf = "";
  backend.stdout.on("data", (d) => { buf += d; const m = buf.match(/\{[^{}]*\}/); if (m) { try { resolve(JSON.parse(m[0])); } catch { /* keep reading */ } } });
  setTimeout(() => reject(new Error("engine did not report its port")), 60000);
});
const ENGINE = `http://127.0.0.1:${handshake.port}`;
const uiPort = await new Promise((resolve, reject) => {
  const probe = net.createServer();
  probe.once("error", reject);
  probe.listen(0, "127.0.0.1", () => { const { port } = probe.address(); probe.close(() => resolve(port)); });
});
const UI = `http://localhost:${uiPort}`;
children.push(spawn("npx.cmd", ["vite", "--port", String(uiPort), "--strictPort", "--host", "localhost"], { cwd: join(repo, "desktop"), stdio: "ignore", shell: true }));
let uiReady = false;
for (let i = 0; i < 80 && !uiReady; i++) { try { uiReady = (await fetch(`${UI}/`)).ok; } catch { /* not yet */ } if (!uiReady) await sleep(500); }
if (!uiReady) { console.error(`This checkout's UI did not come up on ${UI}.`); process.exit(2); }
console.log(`UI: this checkout (${join(repo, "desktop")}) on ${UI}`);

/* ---------- a fake printer (Moonraker look-alike) on this machine, started only for one scenario ---------- */
const job = (filename, status) => ({ job_id: filename + status, filename, status, start_time: 1, end_time: 2, print_duration: 1, total_duration: 1, filament_used: 1, metadata: {} });
const fakeJobs = [job("example-project.gcode", "error"), job("other-a.gcode", "completed"), job("other-b.gcode", "completed"), job("other-c.gcode", "completed"), job("other-d.gcode", "completed")];
function startFakePrinter() {
  const srv = http.createServer((req, res) => {
    const url = req.url || "";
    const reply = (obj) => { res.writeHead(200, { "content-type": "application/json" }); res.end(JSON.stringify(obj)); };
    if (url.startsWith("/printer/info")) return reply({ result: { state: "ready", state_message: "Printer is ready", hostname: "example-printer" } });
    if (url.startsWith("/server/info")) return reply({ result: { klippy_state: "ready", warnings: ["example firmware warning"], failed_components: [] } });
    if (url.startsWith("/server/history/list")) return reply({ result: { jobs: fakeJobs } });
    if (url.startsWith("/server/history/totals")) return reply({ result: { job_totals: { total_jobs: 5 } } });
    res.writeHead(404); res.end("{}");
  });
  return new Promise((resolve) => srv.listen(7125, "127.0.0.1", () => resolve(srv)));
}

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  - " + detail : ""}`); };
const browser = await chromium.launch({ channel: "msedge", headless: true });
console.log(`browser: Edge ${browser.version()}`);
const violations = [];
const errors = [];

async function visit(label, file, theme, { expand = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1100, height: 2800 }, colorScheme: theme });
  await ctx.addInitScript((t) => { localStorage.setItem("theme", t); localStorage.setItem("mode", "simple"); localStorage.setItem("u1Host", "127.0.0.1"); }, theme);
  await ctx.route(`${ENGINE}/**`, async (route) => {
    const url = new URL(route.request().url());
    let body = {};
    try { body = JSON.parse(route.request().postData() || "{}") ?? {}; } catch { /* not JSON */ }
    const otherHost = body.host !== undefined && String(body.host).trim() !== "" && String(body.host).trim() !== "127.0.0.1";
    if (/discover/i.test(url.pathname) || otherHost) { violations.push(`${route.request().method()} ${url.pathname}`); await route.abort(); return; }
    await route.continue();
  });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR|Invalid DOM property/.test(m.text())) errors.push(m.text()); });
  await page.goto(`${UI}/?api=${handshake.port}:${handshake.token}&file=${encodeURIComponent(file)}`);
  await page.getByRole("button", { name: "Open a model" }).last().click();
  const heading = page.getByText("Print risk signals", { exact: true });
  await heading.waitFor({ timeout: 150000 });
  // The Intelligence Report loads on its own request; wait for it so the page check covers it.
  await page.getByText("Studio Intelligence Report", { exact: false }).first().waitFor({ timeout: 240000 });
  await page.getByText("Risks found", { exact: true }).waitFor({ timeout: 30000 });
  const card = heading.locator("xpath=ancestor::div[contains(@class,'space-y-3')][1]");
  await sleep(1000);
  const text = (await card.innerText()).replace(/\s+/g, " ");
  if (expand) {
    await page.getByRole("button", { name: /See risks, recommendations/ }).click();
    await page.getByText("Supporting Doctors", { exact: true }).waitFor({ timeout: 10000 });
    await sleep(500);
  }
  const pageText = (await page.locator("body").innerText()).replace(/\s+/g, " ");
  await card.screenshot({ path: join(out, `${label}-${theme}-card.png`) });
  await page.screenshot({ path: join(out, `${label}-${theme}-page.png`) });   // taken after the report loaded
  await ctx.close();
  return { text, pageText };
}

try {
  for (const theme of ["light", "dark"]) {
    const { text: t, pageText: tp } = await visit("01-signals-found", flagged, theme);
    check(`${theme}: card lists signals with what to do`, /What to do:/.test(t) && /(Risk|Heads up):/.test(t), t.slice(0, 200));
    check(`${theme}: card names its evidence kind`, /Studio's check|Estimate/.test(t));
    check(`${theme}: card says what was checked and not checked`, /Studio checked:/.test(t) && /Studio did not check:.*object spacing/.test(t) && /printer health/.test(t));
    check(`${theme}: card says what Studio cannot know and to verify in Snapmaker Orca`, /cannot know/.test(t) && /Verify in Snapmaker Orca/.test(t));
    check(`${theme}: no percentage, band or verdict`, !/\d\s*%/.test(t) && !/Likely to print|Risky|Few risks|readiness/i.test(t));
    const { text: c, pageText: cp } = await visit("02-nothing-flagged", clean, theme);
    check(`${theme}: with no signals it says what was covered and not that the print will succeed`, /did not flag anything/.test(c) && /not a sign the print will succeed/.test(c) && /Studio did not check:/.test(c), c.slice(0, 200));
    check(`${theme}: the nothing-flagged result also has no percentage or verdict`, !/\d\s*%/.test(c) && !/Likely to print|Risky|Few risks|readiness|will print/i.test(c));
    // Whole page, after the Intelligence Report has loaded: no score hero, "/ 100", percentage, readiness rating or success verdict.
    // Allowed on the page: measured geometry ("16.7% of surfaces", "steep overhangs"), the pricing margin, and the Project Doctor's own
    // step heading "Print-Readiness" (a verdict with stars, not a score). Everything else must not match.
    const allowed = /\d+(\.\d+)?\s*%\s*(of surfaces|margin|steep overhangs)|Print-Readiness/gi;
    for (const [name, raw] of [["flagged project", tp], ["nothing flagged", cp]]) {
      const pt = raw.replace(allowed, " ");
      const bad = [...pt.matchAll(/.{0,40}(\d\s*%|\/\s*100\b|Likely to print|Risky|Few risks|Some risks|Several risks|Readiness|Studio score|expected print success).{0,30}/gi)].map((m) => m[0]);
      check(`${theme}: whole page (${name}) has no score, percentage, readiness rating or success verdict`, bad.length === 0, bad.join(" | "));
      check(`${theme}: whole page (${name}) shows the Intelligence Report's "Risks found" count`, /Risks found\s*\d+/i.test(pt));
    }
  }
  // A reachable (fake) printer, with the Intelligence Report's evidence expanded: no health number, grade, "good to print" or "Compatible".
  const fake = await startFakePrinter();
  try {
    for (const theme of ["light", "dark"]) {
      const { text: t, pageText: pt } = await visit("03-printer-answered-evidence", flagged, theme, { expand: true });
      check(`${theme}: with a reachable printer, the card counts printer history as checked`, /Studio checked:.*printer history for the same file name/.test(t) && /Studio checked:.*printer health/.test(t), t.slice(0, 260));
      check(`${theme}: with a reachable printer, a failed print with the same file name is a signal`, /failed 1 time before/.test(t));
      const body = pt.replace(/Print-Readiness/g, "");
      const hits = [...body.matchAll(/.{0,40}(\d+\s*\/\s*100|good to print|Healthy \(|\bCompatible\b|Studio score|Readiness|Likely to print).{0,30}/gi)].map((m) => m[0]);
      check(`${theme}: expanded evidence shows the Printer line without a health number, grade, "good to print" or "Compatible"`,
        /Supporting Doctors/i.test(pt) && /Answered, \d+ concern/i.test(pt) && hits.length === 0, hits.join(" | ") || (/Answered, \d+ concern/i.test(pt) ? "" : "no 'Answered, N concern' line"));
    }
  } finally { fake.close(); }
  check("no engine request named a host other than this machine, or discovery", violations.length === 0, violations.join("; "));
  check("no page errors", errors.length === 0, errors.join(" | ").slice(0, 300));
} catch (e) {
  check("script ran to completion", false, String(e).slice(0, 300));
}
await browser.close();
const failed = results.filter((r) => !r.ok).length;
writeFileSync(join(out, "results.json"), JSON.stringify({ browser: "Microsoft Edge (Chromium, headless)", passed: results.length - failed, total: results.length, results }, null, 2));
console.log(`\n${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
