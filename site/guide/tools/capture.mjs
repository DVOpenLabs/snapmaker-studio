#!/usr/bin/env node
// Captures the guide's screenshots from the REAL Snapmaker Studio interface and records where each annotated control
// sits (as percentages of the image), so hotspots stay aligned at any size.
//
// What it starts (all on this machine, all disposable, all stopped again when it finishes):
//   - the real Studio engine, with a throwaway data folder, no printer and no provider
//   - the Studio web UI from desktop/ (vite dev server) unless one is already on port 1420
//   - a tiny Spoolman look-alike with made-up spools, on 127.0.0.1:7912, to show the spool suggestions
// It never contacts a printer, a slicer or the internet. Example files come from /examples plus tools/fixtures.py.
//
//   node tools/capture.mjs                 capture every shot in tools/spec.mjs
//   node tools/capture.mjs --only home,this-print
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import http from "node:http";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const repo = join(root, "..", "..");
const require = createRequire(import.meta.url);
let playwright;
try { playwright = require("playwright-core"); } catch { playwright = createRequire(join(repo, "tools/acceptance/package.json"))("playwright-core"); }
const { chromium } = playwright;
const { SHOTS, SIZE } = await import("./spec.mjs");

const args = process.argv.slice(2);
const only = args.includes("--only") ? new Set(args[args.indexOf("--only") + 1].split(",")) : null;
const children = [];
function track(proc) { children.push(proc); return proc; }
function stopAll() {
  for (const c of children) {
    try { if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(c.pid), "/T", "/F"], { stdio: "ignore" }); else c.kill("SIGTERM"); } catch { /* already gone */ }
  }
}
process.on("exit", stopAll);
process.on("SIGINT", () => { stopAll(); process.exit(130); });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitHttp(url, ms = 60000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { const r = await fetch(url); if (r.ok || r.status < 500) return; } catch { /* not up yet */ }
    await sleep(500);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

/* ---------- environment ---------- */
const work = mkdtempSync(join(tmpdir(), "guide-capture-"));
const inputs = join(work, "inputs");
mkdirSync(inputs, { recursive: true });
for (const f of ["sample_cube.stl", "demo_offplate_foreign.3mf", "demo_u1_showcase.3mf"]) copyFileSync(join(repo, "examples", f), join(inputs, f));
const py = process.env.PYTHON || (process.platform === "win32" ? "py" : "python3");
const fx = spawnSync(py, [join(here, "fixtures.py"), inputs], { encoding: "utf8" });
if (fx.status !== 0) throw new Error("fixtures.py failed: " + fx.stderr);
const orcaData = join(work, "orca-data");
mkdirSync(orcaData, { recursive: true });

const SPOOLS = [
  [11, "Acme Filaments", "PLA Matte", "D32F2F", 388], [12, "Acme Filaments", "PLA Matte", "D63232", 120],
  [21, "Northwind", "PLA", "1E88E5", 540], [22, "Northwind", "PLA", "1E8AE5", 310], [31, "Acme Filaments", "PETG", "43A047", 250],
];
const spoolman = http.createServer((req, res) => {
  const data = SPOOLS.map(([id, vendor, material, colour, used]) => ({
    id, registered: "2026-09-01T00:00:00Z", filament: { vendor: { name: vendor }, material, color_hex: colour, name: null },
    initial_weight: 1000, used_weight: used, remaining_weight: 1000 - used, archived: false,
  }));
  const body = JSON.stringify(req.url.startsWith("/api/v1/spool") ? data : { status: "healthy" });
  res.writeHead(200, { "content-type": "application/json", "content-length": Buffer.byteLength(body) });
  res.end(body);
}).listen(7912, "127.0.0.1");
process.on("exit", () => spoolman.close());

const backend = track(spawn(py, ["-m", "snapstudio_api"], {
  cwd: join(repo, "backend"), stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, SNAPSTUDIO_DATA_DIR: join(work, "data"), SNAPSTUDIO_ORCA_DATA_DIR: orcaData, PYTHONUNBUFFERED: "1" },
}));
const handshake = await new Promise((resolve, reject) => {
  let buf = "";
  backend.stdout.on("data", (d) => { buf += d; const m = buf.match(/\{.*\}/); if (m) resolve(JSON.parse(m[0])); });
  backend.on("exit", (c) => reject(new Error("engine exited early: " + c)));
  setTimeout(() => reject(new Error("engine did not report its port")), 60000);
});
backend.stdout.on("data", () => {}); backend.stderr.on("data", () => {});
let uiUp = false;
try { await waitHttp("http://localhost:1420/", 2500); uiUp = true; } catch { /* start our own */ }
if (!uiUp) {
  track(spawn(process.platform === "win32" ? "npx.cmd" : "npx", ["vite"], { cwd: join(repo, "desktop"), stdio: "ignore", shell: process.platform === "win32" }));
  await waitHttp("http://localhost:1420/", 90000);
}
console.log("environment ready:", work);

/* ---------- capture ---------- */
const browser = await chromium.launch({ channel: "msedge", headless: true });
const geometryPath = join(root, "content/geometry.json");
const geometry = existsSync(geometryPath) ? JSON.parse(readFileSync(geometryPath, "utf8")) : {};
const imgDir = join(root, "public/assets/img");
mkdirSync(imgDir, { recursive: true });
const env = { inputs, handshake, work, orcaData };
let failures = 0;

async function scrub(page) {
  await page.evaluate(() => {
    const path = /[A-Za-z]:[\\/][^\s"')<]*/g;
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (w.nextNode()) nodes.push(w.currentNode);
    for (const n of nodes) { path.lastIndex = 0; if (path.test(n.nodeValue)) { path.lastIndex = 0; n.nodeValue = n.nodeValue.replace(path, "<folder>"); } }
    for (const el of document.querySelectorAll("input, textarea")) {
      if (/[A-Za-z]:[\\/]/.test(el.value || "") || /[A-Za-z]:[\\/]/.test(el.placeholder || "")) {
        el.placeholder = "Folder where Snapmaker Orca saves its exports"; el.value = "";
      }
    }
  });
}

for (const shot of SHOTS) {
  if (only && !only.has(shot.id)) continue;
  if (shot.installed) continue; // needs the installed app: tools/capture-installed.mjs
  const size = shot.size || SIZE;
  const ctx = await browser.newContext({ viewport: size, colorScheme: "dark", deviceScaleFactor: 1 });
  await ctx.addInitScript((p) => {
    localStorage.setItem("theme", "dark");
    if (p) {
      localStorage.setItem("materialProviderKind", JSON.stringify("spoolman"));
      localStorage.setItem("materialProviderUrl", JSON.stringify("127.0.0.1:7912"));
      localStorage.setItem("materialProviderSlotBase", JSON.stringify(1));
    }
  }, !!shot.provider);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  try {
    const q = shot.open ? `&file=${encodeURIComponent(join(inputs, shot.open))}` : "";
    await page.goto(`http://localhost:1420/?api=${handshake.port}:${handshake.token}${q}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1200);
    if (shot.open) {
      await page.locator("aside, nav").first().getByRole("button", { name: /^Open a model$/ }).first().click();
      await page.waitForTimeout(3500);
    }
    if (shot.route) {
      await page.evaluate((r) => { window.history.pushState({}, "", r); window.dispatchEvent(new PopStateEvent("popstate")); }, shot.route);
      await page.waitForTimeout(1500);
    }
    await shot.setup?.(page, env);
    await page.waitForTimeout(shot.settle ?? 500);
    await scrub(page);
    const target = shot.scroll ? shot.scroll(page) : null;
    if (target) { await target.first().evaluate((el) => el.scrollIntoView({ block: "start" })); await page.waitForTimeout(300); }
    await scrub(page);
    const vp = page.viewportSize();
    const hot = {};
    for (const [key, make] of Object.entries(shot.targets || {})) {
      const loc = make(page).first();
      try { await loc.waitFor({ state: "visible", timeout: 8000 }); } catch { throw new Error(`target "${key}" was not found on the page`); }
      const b = await loc.boundingBox();
      if (!b) throw new Error(`no box for ${key}`);
      const x0 = Math.max(0, b.x), y0 = Math.max(0, b.y), x1 = Math.min(vp.width, b.x + b.width), y1 = Math.min(vp.height, b.y + b.height);
      if (x1 - x0 < 4 || y1 - y0 < 4 || b.y + 6 > vp.height) throw new Error(`hotspot "${key}" is not inside the captured area (box ${JSON.stringify(b)})`);
      const pct = (v, total) => Math.round((v / total) * 10000) / 100;
      hot[key] = { x: pct(x0, vp.width), y: pct(y0, vp.height), w: pct(x1 - x0, vp.width), h: pct(y1 - y0, vp.height) };
    }
    await page.screenshot({ path: join(imgDir, shot.file) });
    geometry[shot.id] = { width: vp.width, height: vp.height, hotspots: hot };
    console.log(`ok   ${shot.id}  (${Object.keys(hot).length} hotspots)${errors.length ? "  page errors: " + errors.join(" | ") : ""}`);
  } catch (e) {
    failures++;
    console.log(`FAIL ${shot.id}: ${String(e.message).split("\n")[0]}`);
    try { await page.screenshot({ path: join(work, `FAIL-${shot.id}.png`) }); } catch { /* ignore */ }
  }
  await ctx.close();
}
writeFileSync(geometryPath, JSON.stringify(geometry, null, 1) + "\n");
await browser.close();
stopAll();
console.log(failures ? `${failures} shot(s) failed — see ${work}` : "all shots captured");
process.exit(failures ? 1 : 0);
