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

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  - " + detail : ""}`); };
const browser = await chromium.launch({ channel: "msedge", headless: true });
console.log(`browser: Edge ${browser.version()}`);
const violations = [];
const errors = [];

async function visit(label, file, theme) {
  const ctx = await browser.newContext({ viewport: { width: 1100, height: 1000 }, colorScheme: theme });
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
  const card = heading.locator("xpath=ancestor::div[contains(@class,'space-y-3')][1]");
  await card.scrollIntoViewIfNeeded();
  await sleep(500);
  const text = (await card.innerText()).replace(/\s+/g, " ");
  await card.screenshot({ path: join(out, `${label}-${theme}-card.png`) });
  await page.screenshot({ path: join(out, `${label}-${theme}-page.png`) });
  await ctx.close();
  return text;
}

try {
  for (const theme of ["light", "dark"]) {
    const t = await visit("01-signals-found", flagged, theme);
    check(`${theme}: card lists signals with what to do`, /What to do:/.test(t) && /(Risk|Heads up):/.test(t), t.slice(0, 200));
    check(`${theme}: card names its evidence kind`, /Studio's check|Estimate/.test(t));
    check(`${theme}: card says what was checked and not checked`, /Studio checked:/.test(t) && /Studio did not check:.*object spacing/.test(t) && /printer health/.test(t));
    check(`${theme}: card says what Studio cannot know and to verify in Snapmaker Orca`, /cannot know/.test(t) && /Verify in Snapmaker Orca/.test(t));
    check(`${theme}: no percentage, band or verdict`, !/\d\s*%/.test(t) && !/Likely to print|Risky|Few risks|readiness/i.test(t));
    const c = await visit("02-nothing-flagged", clean, theme);
    check(`${theme}: with no signals it says what was covered and not that the print will succeed`, /did not flag anything/.test(c) && /not a sign the print will succeed/.test(c) && /Studio did not check:/.test(c), c.slice(0, 200));
    check(`${theme}: the nothing-flagged result also has no percentage or verdict`, !/\d\s*%/.test(c) && !/Likely to print|Risky|Few risks|readiness|will print/i.test(c));
  }
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
