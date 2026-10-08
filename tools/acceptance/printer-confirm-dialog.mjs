#!/usr/bin/env node
// Integrated check of the printer-action confirmation prompt in a real browser engine.
//
//   node tools/acceptance/printer-confirm-dialog.mjs [--shots <folder>]
//
// What it starts, all on this machine and all stopped again at the end:
//   - the real Studio engine (throwaway data folder)
//   - the real Studio web UI (vite dev server on :1420, unless one is already there)
//   - two LOOPBACK Moonraker look-alikes (127.0.0.1:7125 = "printer A", 127.0.0.2:7125 = "printer B") that only record the
//     requests they receive. Nothing reaches a real printer, and nothing leaves this computer.
//
// The browser is Microsoft Edge. On Windows its engine is the same Chromium that WebView2 uses (the script prints the Edge
// version and the installed WebView2 runtime version so the match can be checked). It is NOT the Tauri window itself:
// the Tauri host, WebKitGTK on Linux and screen readers are not covered here.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync } from "node:fs";
import http from "node:http";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");
const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");
const args = process.argv.slice(2);
const shotsDir = args.includes("--shots") ? args[args.indexOf("--shots") + 1] : null;
if (shotsDir) mkdirSync(shotsDir, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const children = [];
const servers = [];
const stopAll = () => {
  for (const c of children) { try { spawnSync("taskkill", ["/PID", String(c.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* gone */ } }
  for (const s of servers) { try { s.close(); } catch { /* gone */ } }
};
process.on("exit", stopAll);
async function waitHttp(url, ms = 90000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { try { const r = await fetch(url); if (r.status < 500) return; } catch { /* not yet */ } await sleep(400); }
  throw new Error("timed out waiting for " + url);
}

/* ---------- loopback printers: record what they are asked to do ---------- */
const calls = [];                                   // { printer, method, path }
const printers = { a: { state: "printing", up: true, delayMs: 400 }, b: { state: "printing", up: true, delayMs: 0 } };
function printerServer(key, host) {
  const srv = http.createServer((req, res) => {
    const p = printers[key];
    const send = (code, body) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
    if (!p.up) { res.destroy(); return; }
    const path = (req.url || "").split("?")[0];
    if (req.method === "POST") {
      calls.push({ printer: key, method: "POST", path: req.url });
      const finish = () => send(200, { result: "ok" });
      return p.delayMs ? setTimeout(finish, p.delayMs) : finish();
    }
    if (path === "/printer/objects/query") {
      return send(200, { result: { status: {
        print_stats: { state: p.state, filename: "example.gcode", print_duration: 100, total_duration: 120, info: { current_layer: 3, total_layer: 40 } },
        heater_bed: { temperature: 60, target: 60 }, virtual_sdcard: { progress: 0.2 }, display_status: {}, gcode_move: { speed_factor: 1, extrude_factor: 1 },
      } } });
    }
    if (path === "/server/info") return send(200, { result: { klippy_state: "ready", moonraker_version: "look-alike" } });
    return send(200, { result: {} });
  });
  srv.on("clientError", () => {});
  srv.listen(7125, host);
  servers.push(srv);
}
printerServer("a", "127.0.0.1");
printerServer("b", "127.0.0.2");
const callsTo = (key, needle) => calls.filter((c) => c.printer === key && c.path.includes(needle)).length;

/* ---------- engine + UI ---------- */
const work = mkdtempSync(join(tmpdir(), "confirm-dialog-"));
const py = process.env.PYTHON || (process.platform === "win32" ? "py" : "python3");
const backend = spawn(py, ["-m", "snapstudio_api"], {
  cwd: join(repo, "backend"), stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, SNAPSTUDIO_DATA_DIR: join(work, "data"), PYTHONUNBUFFERED: "1" },
});
children.push(backend);
const handshake = await new Promise((resolve, reject) => {
  let buf = "";
  backend.stdout.on("data", (d) => { buf += d; const m = buf.match(/\{.*\}/); if (m) resolve(JSON.parse(m[0])); });
  backend.on("exit", (c) => reject(new Error("engine exited early: " + c)));
  setTimeout(() => reject(new Error("engine did not report its port")), 60000);
});
backend.stderr.on("data", () => {});
let uiUp = false;
try { await waitHttp("http://localhost:1420/", 2500); uiUp = true; } catch { /* start our own */ }
if (!uiUp) {
  children.push(spawn("npx.cmd", ["vite"], { cwd: join(repo, "desktop"), stdio: "ignore", shell: true }));
  await waitHttp("http://localhost:1420/");
}

/* ---------- checks ---------- */
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`); };

const browser = await chromium.launch({ channel: "msedge", headless: true });
const webview = (() => {
  if (process.platform !== "win32") return "n/a";
  const base = "C:/Program Files (x86)/Microsoft/EdgeWebView/Application";
  try { return readdirSync(base).filter((d) => /^\d+\./.test(d)).join(", "); } catch { return "not found"; }
})();
console.log(`browser: Edge ${browser.version()}   installed WebView2 runtime: ${webview}`);

const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "dark" });
await ctx.addInitScript(() => { localStorage.setItem("theme", "dark"); });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR|Invalid DOM property/.test(m.text())) errors.push(m.text()); });

const snap = async (name) => { if (shotsDir) await page.screenshot({ path: join(shotsDir, `${name}.png`) }); };
const active = () => page.evaluate(() => { const a = document.activeElement; return a ? (a.textContent || a.tagName).trim().slice(0, 40) : null; });
const insideDialog = () => page.evaluate(() => !!document.activeElement?.closest("dialog"));
const dialog = page.getByRole("alertdialog");
const goPrinterHub = async () => {
  await page.goto(`http://localhost:1420/?api=${handshake.port}:${handshake.token}`, { waitUntil: "networkidle" });
  await page.evaluate(() => { window.history.pushState({}, "", "/printers"); window.dispatchEvent(new PopStateEvent("popstate")); });
  await page.waitForTimeout(800);
};
const connectTo = async (host) => {
  const input = page.locator("input").first();
  await input.fill(host);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
};
const cancelButton = page.getByRole("button", { name: /Cancel print/ });

try {
  await goPrinterHub();
  await connectTo("127.0.0.1");
  await cancelButton.waitFor({ state: "visible", timeout: 20000 });
  check("controls appear for printer A while it is printing", true);

  /* identity, focus, containment, Escape, restoration */
  await cancelButton.focus();
  await page.keyboard.press("Enter");
  await dialog.waitFor({ state: "visible", timeout: 5000 });
  check("opens as an alert dialog named by its title", (await page.getByRole("alertdialog", { name: "Cancel this print?" }).count()) === 1);
  const snapshot = await dialog.ariaSnapshot();
  check("the title, the warning and the printer are exposed to assistive technology", /Cancel this print\?/.test(snapshot) && /resume a cancelled print/.test(snapshot) && /Printer: 127\.0\.0\.1/.test(snapshot), snapshot.replace(/\n/g, " | ").slice(0, 140));
  check("initial focus is on Cancel", (await active()) === "Cancel");
  const box = await dialog.boundingBox();
  const vp = page.viewportSize();
  const css = await page.evaluate(() => { const d = document.querySelector("dialog"); const c = getComputedStyle(d); return { cls: d.className, margin: c.margin, position: c.position, top: c.top, bottom: c.bottom, insetBlock: c.insetBlock, height: c.height, maxHeight: c.maxHeight }; });
  check("the prompt is centered in the window", Math.abs(box.x + box.width / 2 - vp.width / 2) < 60 && Math.abs(box.y + box.height / 2 - vp.height / 2) < 60, JSON.stringify({ box, css }));
  await snap("confirm-dialog-open");

  const seen = new Set();
  let leftDialog = false;
  for (let i = 0; i < 12; i++) { await page.keyboard.press(i % 2 ? "Shift+Tab" : "Tab"); seen.add(await active()); if (!(await insideDialog())) { const a = await page.evaluate(() => document.activeElement === document.body || document.activeElement === document.documentElement); if (!a) leftDialog = true; } }
  check("Tab and Shift+Tab never reach the page behind the prompt", !leftDialog, [...seen].join(" | "));
  const behind = await page.evaluate(() => { const b = document.querySelector("input"); const r = b.getBoundingClientRect(); const el = document.elementFromPoint(r.x + 4, r.y + 4); return el === b; });
  check("the connect field behind the prompt cannot be clicked", !behind);

  await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
  check("Escape closes the prompt", (await dialog.count()) === 0);
  check("Escape sent nothing to the printer", callsTo("a", "cancel") === 0);
  check("focus returns to the Cancel print button", (await active()).startsWith("Cancel print"), await active());

  /* exactly once */
  await cancelButton.focus();
  await page.keyboard.press("Enter");
  await dialog.waitFor({ state: "visible" });
  await page.evaluate(() => { const b = [...document.querySelectorAll("dialog button")].find((x) => /Yes, do it/.test(x.textContent)); b.click(); b.click(); b.click(); });
  await page.waitForTimeout(900);
  check("three rapid confirms send exactly one cancel request, to printer A", callsTo("a", "cancel") === 1 && callsTo("b", "cancel") === 0, JSON.stringify(calls.filter((c) => /cancel/.test(c.path))));
  check("the prompt closes when the request finishes", (await dialog.count()) === 0);

  /* printer stops answering while the prompt is open */
  printers.a.state = "printing"; printers.a.up = true; calls.length = 0;
  await page.waitForTimeout(3500);
  await cancelButton.waitFor({ state: "visible", timeout: 15000 });
  await cancelButton.focus();
  await page.keyboard.press("Enter");
  await dialog.waitFor({ state: "visible" });
  printers.a.up = false;
  await dialog.waitFor({ state: "detached", timeout: 15000 });
  check("the prompt is withdrawn when the printer stops answering", true);
  check("nothing was sent to the printer that went away", calls.length === 0);

  /* the print finishes while the prompt is open */
  printers.a.up = true; printers.a.state = "printing";
  await cancelButton.waitFor({ state: "visible", timeout: 20000 });
  await cancelButton.focus();
  await page.keyboard.press("Enter");
  await dialog.waitFor({ state: "visible" });
  printers.a.state = "complete";
  await dialog.waitFor({ state: "detached", timeout: 15000 });
  check("the prompt is withdrawn when the print finishes (nothing left to cancel)", true);
  check("no cancel was sent for a print that had already ended", callsTo("a", "cancel") === 0);
  check("focus lands somewhere sensible after the Cancel button disappeared", /Printer controls|Start|Upload|Emergency/i.test(await active() || ""), await active());

  /* emergency stop asks first too */
  await page.getByRole("button", { name: /^Emergency stop$/ }).focus();
  await page.keyboard.press("Enter");
  await dialog.waitFor({ state: "visible" });
  check("emergency stop asks first and names the printer", (await dialog.innerText()).includes("Printer: 127.0.0.1") && callsTo("a", "M112") === 0);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
  check("dismissing emergency stop sends nothing", callsTo("a", "M112") === 0 && (await dialog.count()) === 0);
  await snap("confirm-dialog-closed");

  check("no unexpected console errors", errors.length === 0, errors.slice(0, 2).join(" | "));
} finally {
  await browser.close();
}
const failed = results.filter((r) => !r).length;
console.log(`${results.length - failed}/${results.length} integrated checks passed`);
process.exit(failed ? 1 : 0);
