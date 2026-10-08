#!/usr/bin/env node
// Keyboard check of the Project Materials "Choose another spool" picker in a real browser engine (Windows).
//
//   node tools/acceptance/inventory-picker-keyboard.mjs --out <folder>
//
// Starts, all on this machine and all stopped again at the end: the real Studio engine (throwaway data folder), the real
// Studio web UI (vite on :1420 unless one is already up; the script says which), and an anonymous Spoolman look-alike on
// 127.0.0.1:7912 that serves five made-up spools. Only the keyboard is used to operate the picker. Nothing here may reach a
// real printer or provider: the run is fail-closed, so any engine request that names another provider address, a printer,
// or network discovery is aborted and fails the run.
//
// The browser is Microsoft Edge (Chromium). It is not the Tauri window, WebKitGTK, or a screen reader.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import http from "node:http";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

if (process.platform !== "win32") { console.error("This check is written for Windows (taskkill, npx.cmd)."); process.exit(2); }
const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");
const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");
const out = process.argv.includes("--out") ? process.argv[process.argv.indexOf("--out") + 1] : join(tmpdir(), "picker-evidence");
mkdirSync(out, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const children = [];
const servers = [];
let cleaned = false;
function cleanup() {
  if (cleaned) return;
  cleaned = true;
  for (const c of children) { try { spawnSync("taskkill", ["/PID", String(c.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* gone */ } }
  for (const s of servers) { try { s.close(); } catch { /* gone */ } }
}
process.on("exit", cleanup);
for (const sig of ["SIGINT", "SIGTERM", "SIGBREAK"]) process.on(sig, () => { cleanup(); process.exit(130); });

/* ---------- an anonymous Spoolman look-alike ---------- */
const spool = (id, vendor, material, name, hex, remaining) => ({
  id, registered: "2026-01-01T00:00:00Z", remaining_weight: remaining, archived: false,
  filament: { name, material, color_hex: hex.replace("#", ""), weight: 1000, vendor: { name: vendor } },
});
const spools = [
  spool(1, "Acme Filament", "PLA", "Red", "#E0262A", 640),
  spool(2, "Acme Filament", "PLA", "Blue", "#1F5FD0", 910),
  spool(3, "Example Polymers", "PLA Matte", "Forest Green", "#2E7D4F", 420),
  spool(4, "Example Polymers", "PETG", "Clear Orange", "#F28C28", 780),
  spool(5, "Sample Co", "TPU", "Black", "#202020", 300),
];
const providerCalls = [];
const provider = http.createServer((req, res) => {
  providerCalls.push(`${req.method} ${req.url}`);
  res.writeHead(200, { "content-type": "application/json" });
  res.end(req.url.startsWith("/api/v1/spool") ? JSON.stringify(spools) : "{}");
});
provider.listen(7912, "127.0.0.1");
servers.push(provider);

/* ---------- two anonymous projects: one names a filament preset for its slots, one names none ---------- */
const work = mkdtempSync(join(tmpdir(), "picker-kbd-"));
function project(name, settingsIds) {
  const cfg = {
    version: "02.05.00.66", printer_model: "Generic Printer", printer_settings_id: "Generic Printer 0.4 nozzle",
    print_settings_id: "0.20mm Standard", filament_settings_id: settingsIds,
    filament_vendor: ["Generic", "Generic", "Generic"], filament_colour: ["#E0262A", "#FFFFFF", "#F28C28"],
    filament_type: ["PLA", "PLA", "PETG"], different_settings_to_system: ["", "", "", "", ""],
  };
  const cfgPath = join(work, name + ".json");
  writeFileSync(cfgPath, JSON.stringify(cfg));
  const path = join(work, name + ".3mf");
  const r = spawnSync(process.env.PYTHON || "py", ["-c", [
    "import zipfile,sys",
    "z=zipfile.ZipFile(sys.argv[1],'w')",
    "z.writestr('[Content_Types].xml','<?xml version=\"1.0\"?><Types/>')",
    "z.writestr('_rels/.rels','<?xml version=\"1.0\"?><Relationships/>')",
    "z.writestr('3D/3dmodel.model','<?xml version=\"1.0\"?><model/>')",
    "z.writestr('Metadata/project_settings.config',open(sys.argv[2]).read())",
    "z.close()"].join("\n"), path, cfgPath]);
  if (r.status !== 0) throw new Error(String(r.stderr));
  return path;
}
const withPreset = project("with-preset", ["Generic PLA", "Generic PLA", "Generic PETG"]);
const withoutPreset = project("without-preset", ["", "", ""]);

/* ---------- engine + UI ---------- */
const backend = spawn(process.env.PYTHON || "py", ["-m", "snapstudio_api"], {
  cwd: join(repo, "backend"), stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, SNAPSTUDIO_DATA_DIR: join(work, "data"), PYTHONUNBUFFERED: "1" },
});
children.push(backend);
const handshake = await new Promise((resolve, reject) => {
  let buf = "";
  backend.stdout.on("data", (d) => { buf += d; const m = buf.match(/\{[^{}]*\}/); if (m) { try { resolve(JSON.parse(m[0])); } catch { /* keep reading */ } } });
  setTimeout(() => reject(new Error("engine did not report its port")), 60000);
});
let uiUp = false;
try { const r = await fetch("http://localhost:1420/"); uiUp = r.ok; } catch { /* start our own */ }
if (uiUp && !process.argv.includes("--allow-existing-ui")) {
  console.error("A server is already answering on :1420, and it may be a different checkout. Stop it, or pass --allow-existing-ui to accept that (the result then records it).");
  process.exit(2);
}
console.log(uiUp ? "UI: using the dev server already running on :1420 (--allow-existing-ui)" : "UI: started a dev server from this checkout");
if (!uiUp) {
  children.push(spawn("npx.cmd", ["vite"], { cwd: join(repo, "desktop"), stdio: "ignore", shell: true }));
  for (let i = 0; i < 80; i++) { try { const r = await fetch("http://localhost:1420/"); if (r.ok) break; } catch { /* not yet */ } await sleep(500); }
}

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`); };

const browser = await chromium.launch({ channel: "msedge", headless: true });
console.log(`browser: Edge ${browser.version()}`);
const ctx = await browser.newContext({ viewport: { width: 1100, height: 1300 }, colorScheme: "dark" });
await ctx.addInitScript(() => {
  localStorage.setItem("theme", "dark");
  // The Compatibility page also asks the engine about a printer. Its default address is the stock name U1.local, which
  // would be looked up on the network; the saved address is therefore the loopback one before the app first reads it.
  localStorage.setItem("u1Host", "127.0.0.1");
  localStorage.setItem("materialProviderKind", JSON.stringify("spoolman"));
  localStorage.setItem("materialProviderUrl", JSON.stringify("127.0.0.1:7912"));
});
// Fail closed: the engine may be asked about this project, this provider and the loopback address, and nothing else.
const violations = [];
await ctx.route(`http://127.0.0.1:${handshake.port}/**`, async (route) => {
  const url = new URL(route.request().url());
  let body = {};
  try { body = JSON.parse(route.request().postData() || "{}") ?? {}; } catch { /* not JSON */ }
  const badProvider = body.provider_url !== undefined && String(body.provider_url).trim() !== "127.0.0.1:7912";
  const namesOtherHost = (body.host !== undefined && String(body.host).trim() !== "127.0.0.1")
    || (Array.isArray(body.hosts) && body.hosts.some((h) => String(h).trim() !== "127.0.0.1"));
  const printer = url.pathname.startsWith("/printer/") || /discover/i.test(url.pathname) || namesOtherHost;
  if (badProvider || printer) { violations.push(`${route.request().method()} ${url.pathname}`); await route.abort(); return; }
  await route.continue();
});
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR|Invalid DOM property/.test(m.text())) errors.push(m.text()); });
const shot = (name) => page.screenshot({ path: join(out, `${name}.png`), fullPage: true });
const active = () => page.evaluate(() => { const a = document.activeElement; return a ? (a.getAttribute("aria-label") || a.textContent || a.tagName).trim().replace(/\s+/g, " ").slice(0, 70) : null; });
const slot2 = () => page.locator('[data-slot="2"]');
const picker = () => page.getByTestId("inventory-picker");

async function openProject(path) {
  await page.goto(`http://localhost:1420/compatibility?api=${handshake.port}:${handshake.token}&file=${encodeURIComponent(path)}`);
  await page.getByRole("button", { name: "Open a 3MF project" }).click();
  await page.getByText("Project materials").first().waitFor({ timeout: 30000 });
  await slot2().getByRole("button", { name: "Choose another spool" }).waitFor();
}
/** Tab until the focused element's text matches, at most `limit` presses. */
async function tabTo(pattern, limit = 14) {
  for (let i = 0; i < limit; i++) { if (pattern.test((await active()) || "")) return true; await page.keyboard.press("Tab"); }
  return pattern.test((await active()) || "");
}

try {
  await openProject(withPreset);

  /* open it from the keyboard */
  await slot2().getByRole("button", { name: "Choose another spool" }).focus();
  await page.keyboard.press("Enter");
  await picker().waitFor();
  await page.getByLabel(/Find a spool for slot 2/).waitFor();
  check("Enter on 'Choose another spool' opens the list", await picker().isVisible());
  check("focus moves to the search box", /Find a spool|Type to find/.test((await active()) || ""), await active());
  await shot("01-picker-open-keyboard");

  /* choose a different material: nothing is selected until the person confirms */
  check("the search box narrows the list from the keyboard", await (async () => {
    await page.keyboard.type("petg");
    const rows = await picker().getByRole("button", { name: /PETG/ }).count();
    await page.keyboard.press("Control+A"); await page.keyboard.press("Backspace");
    return rows === 1;
  })());
  const reached = await tabTo(/Orange/);
  check("Tab reaches the PETG spool row", reached, await active());
  await page.keyboard.press("Enter");
  await page.getByTestId("family-confirm").waitFor();
  check("Enter on a different-material spool asks for confirmation and selects nothing", (await page.getByTestId("selected-spool").count()) === 0);
  check("the engine's warning is shown", /PETG; the model asks for PLA/.test(await page.getByTestId("family-confirm").innerText()));
  check("focus moves to Cancel, the safe answer", (await active()) === "Cancel", await active());
  await shot("02-material-warning-keyboard");

  /* Escape cancels and puts focus back on the row */
  await page.keyboard.press("Escape");
  check("Escape cancels the confirmation", (await page.getByTestId("family-confirm").count()) === 0 && (await picker().isVisible()));
  check("nothing was selected by cancelling", (await page.getByTestId("selected-spool").count()) === 0);
  check("focus returns to the spool row after Escape", /Orange/.test((await active()) || ""), await active());

  /* Cancel (Enter on the Cancel button) does the same */
  await page.keyboard.press("Enter");
  await page.getByTestId("family-confirm").waitFor();
  await page.keyboard.press("Enter");                                    // Cancel has focus
  check("Enter on Cancel closes the confirmation and keeps the list open", (await page.getByTestId("family-confirm").count()) === 0 && (await picker().isVisible()));
  check("focus returns to the spool row after Cancel", /Orange/.test((await active()) || ""), await active());

  /* confirm with the keyboard */
  await page.keyboard.press("Enter");
  await page.getByTestId("family-confirm").waitFor();
  await page.keyboard.press("Shift+Tab");
  check("Shift+Tab reaches 'Use this spool anyway'", /Use this spool anyway/.test((await active()) || ""), await active());
  await page.keyboard.press("Enter");
  await page.getByTestId("selected-spool").waitFor();
  check("only after confirming is the spool selected", /#4/.test(await page.getByTestId("selected-spool").innerText()));
  check("the list closes once a spool is chosen", (await picker().count()) === 0);
  check("focus returns to 'Choose another spool'", /Choose another spool/.test((await active()) || ""), await active());
  const notice = await slot2().getByTestId("spool-without-preset").innerText();
  check("the no-preset notice names the project's existing preset and what Studio did not check",
    notice === "Spool selected, but no Orca preset selected. The project's existing filament preset will remain. Studio leaves its name unchanged and does not check how Snapmaker Orca will treat it.", notice);
  await shot("03-selected-with-notice");

  /* a project that names no preset must not say one will remain */
  await openProject(withoutPreset);
  await slot2().getByRole("button", { name: "Choose another spool" }).focus();
  await page.keyboard.press("Enter");
  await picker().waitFor();
  await page.getByLabel(/Find a spool for slot 2/).waitFor();          // the list has loaded and the search box has focus
  await tabTo(/Blue/);
  await page.keyboard.press("Enter");
  await page.getByTestId("selected-spool").waitFor();
  const none = await slot2().getByTestId("spool-without-preset").innerText();
  check("with no existing preset the notice does not claim one will remain", /names no filament preset for this slot/.test(none) && !/will remain/.test(none), none);
  await shot("04-no-existing-preset");

  check("no request named another provider, a printer, or discovery", violations.length === 0, violations.join(" | "));
  check("the provider look-alike was read and never written", providerCalls.every((c) => c.startsWith("GET ")), [...new Set(providerCalls)].join(", "));
  check("no unexpected console errors", errors.length === 0, errors.slice(0, 2).join(" | "));
} catch (e) {
  check("the run completed without a harness error", false, String(e?.message ?? e));
  await shot("failure").catch(() => {});
} finally {
  await browser.close();
  cleanup();
}
const failed = results.filter((r) => !r.ok).length;
writeFileSync(join(out, "results.json"), JSON.stringify({ browser: "Microsoft Edge (Chromium), headless", uiStartedByThisRun: !uiUp,
  commit: spawnSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).stdout.trim(), results }, null, 2));
console.log(`${results.length - failed}/${results.length} keyboard checks passed`);
process.exit(failed ? 1 : 0);
