#!/usr/bin/env node
// Integrated check of the printer-action confirmation prompt in a real browser engine (Windows).
//
//   node tools/acceptance/printer-confirm-dialog.mjs [--shots <folder>]
//
// What it starts, all on this machine and all stopped again at the end:
//   - the real Studio engine (throwaway data folder)
//   - the real Studio web UI (vite dev server on :1420, unless one is already there; the script says which)
//   - a LOOPBACK Moonraker look-alike on 127.0.0.1:7125 that only records the requests it receives.
//
// Nothing here may reach a real printer. The browser starts with the saved printer address set to 127.0.0.1 (the app's
// default is the stock name U1.local, which would otherwise be looked up on the network), and the run is fail-closed: any
// request the page sends to the engine that names another printer address is aborted and fails the run.
//
// The browser is Microsoft Edge. On Windows its engine is the same Chromium that WebView2 uses (the script prints the Edge
// version and the installed WebView2 runtime versions so the match can be checked). It is NOT the Tauri window itself:
// the Tauri host, WebKitGTK on Linux and screen readers are not covered here.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readdirSync } from "node:fs";
import http from "node:http";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

if (process.platform !== "win32") { console.error("This check is written for Windows (taskkill, npx.cmd). Linux/WebKitGTK needs its own run."); process.exit(2); }

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");
const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");
const args = process.argv.slice(2);
const shotsDir = args.includes("--shots") ? args[args.indexOf("--shots") + 1] : null;
if (shotsDir) mkdirSync(shotsDir, { recursive: true });

const ALLOWED_PRINTER_HOSTS = new Set(["127.0.0.1"]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const children = [];
const servers = [];
let cleaned = false;
function cleanup() {
  if (cleaned) return;
  cleaned = true;
  for (const c of children) { try { spawnSync("taskkill", ["/PID", String(c.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* already gone */ } }
  for (const s of servers) { try { s.close(); } catch { /* already gone */ } }
}
process.on("exit", cleanup);
for (const sig of ["SIGINT", "SIGTERM", "SIGBREAK"]) process.on(sig, () => { cleanup(); process.exit(130); });
async function waitHttp(url, ms = 90000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { try { const r = await fetch(url); if (r.status < 500) return; } catch { /* not yet */ } await sleep(400); }
  throw new Error("timed out waiting for " + url);
}

/* ---------- the loopback printer: records what it is asked to do ---------- */
const calls = [];                                   // { method, path }
const printer = { state: "printing", up: true, delayMs: 600 };
const printerServer = http.createServer((req, res) => {
  const send = (code, body) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
  if (!printer.up) { res.destroy(); return; }
  const path = (req.url || "").split("?")[0];
  if (req.method === "POST") {
    calls.push({ method: "POST", path: req.url });
    const finish = () => send(200, { result: "ok" });
    return printer.delayMs ? setTimeout(finish, printer.delayMs) : finish();
  }
  if (path === "/printer/objects/query") {
    return send(200, { result: { status: {
      print_stats: { state: printer.state, filename: "example.gcode", print_duration: 100, total_duration: 120, info: { current_layer: 3, total_layer: 40 } },
      heater_bed: { temperature: 60, target: 60 }, virtual_sdcard: { progress: 0.2 }, display_status: {}, gcode_move: { speed_factor: 1, extrude_factor: 1 },
    } } });
  }
  if (path === "/server/info") return send(200, { result: { klippy_state: "ready", moonraker_version: "look-alike" } });
  return send(200, { result: {} });
});
printerServer.on("clientError", () => {});
printerServer.listen(7125, "127.0.0.1");
servers.push(printerServer);
const callsMatching = (needle) => calls.filter((c) => c.path.includes(needle)).length;

/* ---------- engine + UI ---------- */
const work = mkdtempSync(join(tmpdir(), "confirm-dialog-"));
const py = process.env.PYTHON || "py";
const backend = spawn(py, ["-m", "snapstudio_api"], {
  cwd: join(repo, "backend"), stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, SNAPSTUDIO_DATA_DIR: join(work, "data"), PYTHONUNBUFFERED: "1" },
});
children.push(backend);
let engineErr = "";
backend.stderr.on("data", (d) => { engineErr = (engineErr + d).slice(-4000); });
const handshake = await new Promise((resolve, reject) => {
  let buf = "";
  backend.stdout.on("data", (d) => {
    buf += d;
    const m = buf.match(/\{[^{}]*\}/);
    if (m) { try { resolve(JSON.parse(m[0])); } catch { /* keep reading */ } }
  });
  backend.on("exit", (c) => reject(new Error(`engine exited early (${c}): ${engineErr}`)));
  setTimeout(() => reject(new Error("engine did not report its port: " + engineErr)), 60000);
});
let uiUp = false;
try { await waitHttp("http://localhost:1420/", 2500); uiUp = true; } catch { /* start our own */ }
console.log(uiUp ? "UI: using the dev server already running on :1420 (it may be a different checkout)" : "UI: started a dev server from this checkout");
if (!uiUp) {
  children.push(spawn("npx.cmd", ["vite"], { cwd: join(repo, "desktop"), stdio: "ignore", shell: true }));
  await waitHttp("http://localhost:1420/");
}

/* ---------- checks ---------- */
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`); };

const browser = await chromium.launch({ channel: "msedge", headless: true });
const webview = (() => {
  const base = "C:/Program Files (x86)/Microsoft/EdgeWebView/Application";
  try { return readdirSync(base).filter((d) => /^\d+\./.test(d)).join(", "); } catch { return "not found"; }
})();
console.log(`browser: Edge ${browser.version()}   installed WebView2 runtime: ${webview}`);

const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "dark" });
// The saved printer address must be the loopback one BEFORE the app starts (its default is U1.local).
await ctx.addInitScript(() => { localStorage.setItem("theme", "dark"); localStorage.setItem("u1Host", "127.0.0.1"); });
// Fail closed: nothing that names another printer address reaches the engine.
const violations = [];
await ctx.route(`http://127.0.0.1:${handshake.port}/**`, async (route) => {
  const req = route.request();
  const url = new URL(req.url());
  let body = {};
  try { body = JSON.parse(req.postData() || "{}") ?? {}; } catch { /* not JSON */ }
  // Every address the request could make the engine contact: the body host, each of the body hosts, the query host.
  // Each one is judged on its own, so a harmless one cannot hide a forbidden one.
  const named = [];
  if (body.host !== undefined) named.push(body.host);
  if (Array.isArray(body.hosts)) named.push(...body.hosts);
  if (url.searchParams.has("host")) named.push(url.searchParams.get("host"));
  const bad = named.filter((h) => !ALLOWED_PRINTER_HOSTS.has(String(h ?? "").trim()));
  // Discovery scans the network (and, with no hosts given, a default list), so it is never allowed here.
  const scans = /discover/i.test(url.pathname);
  // A printer request that names no address at all would fall back to the engine's default (U1.local).
  const unnamed = url.pathname.startsWith("/printer/") && named.length === 0;
  if (bad.length || scans || unnamed) {
    violations.push(`${req.method()} ${url.pathname} -> ${scans ? "network discovery" : unnamed ? "no printer address" : "host " + bad.join(",")}`);
    await route.abort();
    return;
  }
  await route.continue();
});
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR|Invalid DOM property/.test(m.text())) errors.push(m.text()); });

const snap = async (name) => { if (shotsDir) await page.screenshot({ path: join(shotsDir, `${name}.png`) }); };
const active = () => page.evaluate(() => { const a = document.activeElement; return a ? (a.textContent || a.tagName).trim().slice(0, 40) : null; });
const focusState = () => page.evaluate(() => {
  const a = document.activeElement;
  return { inside: !!a?.closest("dialog"), onPage: a === document.body || a === document.documentElement, text: a === document.body || a === document.documentElement ? "BODY" : (a?.textContent || a?.tagName || "").trim().slice(0, 30) };
});
const dialog = page.getByRole("alertdialog");
const cancelButton = page.getByRole("button", { name: /Cancel print/ });
const openCancelPrompt = async () => {
  await cancelButton.waitFor({ state: "visible", timeout: 20000 });
  await cancelButton.focus();
  await page.keyboard.press("Enter");
  await dialog.waitFor({ state: "visible", timeout: 5000 });
};

try {
  await page.goto(`http://localhost:1420/?api=${handshake.port}:${handshake.token}`, { waitUntil: "networkidle" });
  await page.evaluate(() => { window.history.pushState({}, "", "/printers"); window.dispatchEvent(new PopStateEvent("popstate")); });
  await page.waitForTimeout(800);
  // The saved address (127.0.0.1) auto-connects; no typing needed.
  await cancelButton.waitFor({ state: "visible", timeout: 20000 });
  check("controls appear for the loopback printer while it is printing", true);

  /* identity, focus, containment, Escape, restoration */
  await openCancelPrompt();
  check("opens as an alert dialog named by its title", (await page.getByRole("alertdialog", { name: "Cancel this print?" }).count()) === 1);
  const snapshot = await dialog.ariaSnapshot();
  check("the title, the warning and the printer are exposed to assistive technology", /Cancel this print\?/.test(snapshot) && /resume a cancelled print/.test(snapshot) && /Printer: 127\.0\.0\.1/.test(snapshot), snapshot.replace(/\n/g, " | ").slice(0, 140));
  check("initial focus is on Cancel", (await active()) === "Cancel");
  const box = await dialog.boundingBox();
  const vp = page.viewportSize();
  check("the prompt is centered in the window", Math.abs(box.x + box.width / 2 - vp.width / 2) < 60 && Math.abs(box.y + box.height / 2 - vp.height / 2) < 60, JSON.stringify(box));
  await snap("confirm-dialog-open");

  // Consecutive Tabs forward past the last control, then consecutive Shift+Tabs backward past the first.
  const trail = [];
  let reachedBackground = false;
  for (let i = 0; i < 6; i++) { await page.keyboard.press("Tab"); const s = await focusState(); trail.push(s.text); if (!s.inside && !s.onPage) reachedBackground = true; }
  for (let i = 0; i < 6; i++) { await page.keyboard.press("Shift+Tab"); const s = await focusState(); trail.push(s.text); if (!s.inside && !s.onPage) reachedBackground = true; }
  check("six Tabs forward and six Shift+Tabs backward never focus a control on the page behind the prompt", !reachedBackground, trail.join(" | "));
  check("the prompt's own buttons are the only controls focus visited", trail.every((t) => ["Cancel", "Yes, do it", "BODY", "HTML"].includes(t)), [...new Set(trail)].join(", "));
  const behind = await page.evaluate(() => { const b = document.querySelector("input"); const r = b.getBoundingClientRect(); return document.elementFromPoint(r.x + 4, r.y + 4) === b; });
  check("the connect field behind the prompt cannot be clicked", !behind);

  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "detached", timeout: 3000 });
  check("Escape closes the prompt", true);
  check("Escape sent nothing to the printer", callsMatching("cancel") === 0);
  check("focus returns to the Cancel print button", (await active()).startsWith("Cancel print"), await active());

  /* exactly once, even with Escape pressed twice while the request is running */
  await openCancelPrompt();
  await page.evaluate(() => { const b = [...document.querySelectorAll("dialog button")].find((x) => /Yes, do it/.test(x.textContent)); b.click(); b.click(); b.click(); });
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  check("Escape pressed twice while the request is running leaves the prompt on screen", (await dialog.count()) === 1 && (await page.evaluate(() => document.querySelector("dialog")?.hasAttribute("open"))));
  await dialog.waitFor({ state: "detached", timeout: 8000 });
  check("three rapid confirms send exactly one cancel request", callsMatching("cancel") === 1, JSON.stringify(calls.filter((c) => /cancel/.test(c.path))));
  check("the prompt closes when the request finishes", true);

  /* the printer stops answering while the prompt is open */
  printer.state = "printing"; calls.length = 0;
  await openCancelPrompt();
  printer.up = false;
  await dialog.waitFor({ state: "detached", timeout: 20000 });
  check("the prompt is withdrawn when the printer stops answering", true);
  check("nothing was sent to the printer that went away", calls.length === 0);

  /* the print finishes while the prompt is open */
  printer.up = true; printer.state = "printing";
  await openCancelPrompt();
  printer.state = "complete";
  await dialog.waitFor({ state: "detached", timeout: 20000 });
  check("the prompt is withdrawn when the print finishes (nothing left to cancel)", true);
  check("no cancel was sent for a print that had already ended", callsMatching("cancel") === 0);
  await page.waitForTimeout(300);
  check("focus lands on the card heading after the Cancel button disappeared", /Printer controls/i.test(await active() || ""), await active());

  /* emergency stop asks first too */
  await page.getByRole("button", { name: /^Emergency stop$/ }).focus();
  await page.keyboard.press("Enter");
  await dialog.waitFor({ state: "visible" });
  check("emergency stop asks first and names the printer", (await dialog.innerText()).includes("Printer: 127.0.0.1") && callsMatching("M112") === 0);
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "detached", timeout: 3000 });
  check("dismissing emergency stop sends nothing", callsMatching("M112") === 0);
  await snap("confirm-dialog-closed");

  check("no request named a printer other than the loopback look-alike", violations.length === 0, violations.join(" | "));
  check("no unexpected console errors", errors.length === 0, errors.slice(0, 2).join(" | "));
} finally {
  await browser.close();
  cleanup();
}
const failed = results.filter((r) => !r).length;
console.log(`${results.length - failed}/${results.length} integrated checks passed`);
process.exit(failed ? 1 : 0);
