#!/usr/bin/env node
// Browser check + screenshots of the Project Materials "Forget saved mapping" control and its confirmation (Windows).
//
//   node tools/acceptance/forget-mapping-ui.mjs --out <folder>
//
// Starts, all on this machine and all stopped again at the end: the real Studio engine (throwaway data folder, made-up Orca
// preset folder), this checkout's own Studio web UI (a vite dev server on a free port), and an anonymous Spoolman look-alike on
// 127.0.0.1:7912 with five made-up spools. Two saved mappings are written through the engine's own route, then the control is
// operated in Microsoft Edge (Chromium): cancel, Escape, a failed removal, a refused (stale) removal, a real removal, and a
// choice that rested on the forgotten mapping. Nothing here may reach a real printer, provider or Orca install: any engine
// request that names another provider address, a printer or discovery is aborted and fails the run. The saved-mapping file the
// engine writes is read back to prove what was, and was not, removed.
//
// Also checks, when the build has it (the "Choose another spool" inventory picker), that a spool chosen through the picker
// loses its choice when the mapping it rested on is forgotten.
//
// The browser is Microsoft Edge, not the Tauri window, WebKitGTK or a screen reader.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
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
const out = process.argv.includes("--out") ? process.argv[process.argv.indexOf("--out") + 1] : join(tmpdir(), "forget-evidence");
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

/* ---------- a made-up Orca preset folder, and one anonymous project ---------- */
const work = mkdtempSync(join(tmpdir(), "forget-ui-"));
const profiles = join(work, "orca", "Snapmaker");
mkdirSync(join(profiles, "filament"), { recursive: true });
mkdirSync(join(work, "orcadata", "user"), { recursive: true });
for (const [name, type, vendor] of [["Snapmaker PLA Matte @U1", "PLA", "Snapmaker"], ["Snapmaker PLA SnapSpeed @U1", "PLA", "Snapmaker"], ["Generic PETG @U1", "PETG", "Generic"]]) {
  writeFileSync(join(profiles, "filament", `${name}.json`), JSON.stringify({
    type: "filament", instantiation: "true", name, compatible_printers: ["Snapmaker U1 (0.4 nozzle)"], filament_vendor: [vendor], filament_type: [type] }));
}
function project(name) {
  const cfg = {
    version: "02.05.00.66", printer_model: "Generic Printer", printer_settings_id: "Generic Printer 0.4 nozzle",
    print_settings_id: "0.20mm Standard", filament_settings_id: ["", "", ""],
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
const projectPath = project("example-project");

/* ---------- engine + UI ---------- */
const dataDir = join(work, "data");
const backend = spawn(process.env.PYTHON || "py", ["-m", "snapstudio_api"], {
  cwd: join(repo, "backend"), stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, SNAPSTUDIO_DATA_DIR: dataDir, SNAPSTUDIO_ORCA_PROFILES_DIR: profiles, SNAPSTUDIO_ORCA_DATA_DIR: join(work, "orcadata"),
         PYTHONPATH: join(repo, "backend"), PYTHONUNBUFFERED: "1" },
});
children.push(backend);
const handshake = await new Promise((resolve, reject) => {
  let buf = "";
  backend.stdout.on("data", (d) => { buf += d; const m = buf.match(/\{[^{}]*\}/); if (m) { try { resolve(JSON.parse(m[0])); } catch { /* keep reading */ } } });
  setTimeout(() => reject(new Error("engine did not report its port")), 60000);
});
const ENGINE = `http://127.0.0.1:${handshake.port}`;
const post = async (path, body) => {
  const r = await fetch(ENGINE + path, { method: "POST", headers: { "content-type": "application/json", "x-auth-token": handshake.token }, body: JSON.stringify(body) });
  return { status: r.status, body: await r.json().catch(() => ({})) };
};
// Two saved mappings, written through the engine's own route: one for a spool, one for a kind of spool.
const savedSpool = await post("/material_mapping/confirm", { scope: "spool", provider: "spoolman", spool_id: "3", preset: "Snapmaker PLA Matte @U1", nozzle: "0.4" });
const savedKind = await post("/material_mapping/confirm", { scope: "signature", provider: "spoolman", vendor: "Acme Filament", material: "PLA", subtype: "", preset: "Snapmaker PLA SnapSpeed @U1", nozzle: "0.4" });
if (savedSpool.status !== 200 || savedKind.status !== 200) { console.error("could not seed the saved mappings", savedSpool, savedKind); process.exit(2); }
const mappingFile = () => JSON.parse(readFileSync(join(dataDir, "material-mappings.json"), "utf8")).mappings;

// Always this checkout's own UI, on a port nothing else holds.
const uiPort = await new Promise((resolve, reject) => {
  const probe = net.createServer();
  probe.once("error", reject);
  probe.listen(0, "127.0.0.1", () => { const { port } = probe.address(); probe.close(() => resolve(port)); });
});
const UI = `http://localhost:${uiPort}`;
children.push(spawn("npx.cmd", ["vite", "--port", String(uiPort), "--strictPort", "--host", "localhost"], { cwd: join(repo, "desktop"), stdio: "ignore", shell: true }));
let uiReady = false;
for (let i = 0; i < 80 && !uiReady; i++) { try { const r = await fetch(`${UI}/`); uiReady = r.ok; } catch { /* not yet */ } if (!uiReady) await sleep(500); }
if (!uiReady) { console.error(`This checkout's UI did not come up on ${UI}.`); process.exit(2); }
console.log(`UI: this checkout (${join(repo, "desktop")}) on ${UI}`);

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`); };

const browser = await chromium.launch({ channel: "msedge", headless: true });
console.log(`browser: Edge ${browser.version()}`);
const ctx = await browser.newContext({ viewport: { width: 1100, height: 1300 }, colorScheme: "dark" });
await ctx.addInitScript(() => {
  localStorage.setItem("theme", "dark");
  localStorage.setItem("u1Host", "127.0.0.1");
  localStorage.setItem("materialProviderKind", JSON.stringify("spoolman"));
  localStorage.setItem("materialProviderUrl", JSON.stringify("127.0.0.1:7912"));
});
// Fail closed, and inject the failures this check needs on the remove route.
const violations = [];
const removeRequests = [];
let injectNext = null;              // { status, body } for the next remove request only
await ctx.route(`${ENGINE}/**`, async (route) => {
  const url = new URL(route.request().url());
  let body = {};
  try { body = JSON.parse(route.request().postData() || "{}") ?? {}; } catch { /* not JSON */ }
  const badProvider = body.provider_url !== undefined && String(body.provider_url).trim() !== "127.0.0.1:7912";
  const namesOtherHost = (body.host !== undefined && String(body.host).trim() !== "127.0.0.1")
    || (Array.isArray(body.hosts) && body.hosts.some((h) => String(h).trim() !== "127.0.0.1"));
  const printer = url.pathname.startsWith("/printer/") || /discover/i.test(url.pathname) || namesOtherHost;
  if (badProvider || printer) { violations.push(`${route.request().method()} ${url.pathname}`); await route.abort(); return; }
  if (url.pathname === "/material_mapping/remove" && route.request().method() === "POST") {
    removeRequests.push({ body, injected: !!injectNext });
    if (injectNext) {
      const { status, body: reply } = injectNext; injectNext = null;
      await route.fulfill({ status, contentType: "application/json", headers: { "access-control-allow-origin": route.request().headers().origin ?? "*" }, body: JSON.stringify(reply) });
      return;
    }
  }
  await route.continue();
});
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR|Invalid DOM property/.test(m.text())) errors.push(m.text()); });
const shot = (name) => page.screenshot({ path: join(out, `${name}.png`), fullPage: true });
// The page scrolls inside its own shell, so bring the note into view and capture what the person would see.
const shotNote = async (name) => { await note().scrollIntoViewIfNeeded().catch(() => {}); await sleep(200); await page.screenshot({ path: join(out, `${name}.png`) }); };
const active = () => page.evaluate(() => { const a = document.activeElement; return a ? (a.getAttribute("aria-label") || a.textContent || a.tagName).trim().replace(/\s+/g, " ").slice(0, 90) : null; });
const slot1 = () => page.locator('[data-slot="1"]');   // slot 2 is also PLA and lists the same spools; one slot is enough
const forgetSpool = () => slot1().getByRole("button", { name: /^Forget saved mapping for / });
const forgetKind = () => slot1().getByRole("button", { name: /^Forget saved mapping \(similar spools\) for / });
const dialog = () => page.getByRole("alertdialog");
const note = () => page.getByTestId("forget-note");

try {
  await page.goto(`${UI}/compatibility?api=${handshake.port}:${handshake.token}&file=${encodeURIComponent(projectPath)}`);
  await page.getByRole("button", { name: "Open a 3MF project" }).click();
  await page.getByText("Project materials").first().waitFor({ timeout: 30000 });
  await forgetSpool().first().waitFor({ timeout: 30000 });
  check("a spool with a saved mapping offers 'Forget saved mapping'", (await forgetSpool().count()) === 1);
  check("spools sharing a kind-wide saved mapping say so ('similar spools')", (await forgetKind().count()) === 2);
  await shot("01-saved-mappings-with-forget");

  /* ask first, and cancel */
  await forgetSpool().first().focus();
  await page.keyboard.press("Enter");
  await dialog().waitFor();
  const name = await dialog().getAttribute("aria-label").catch(() => null);
  const title = await page.locator("dialog[open] h2, dialog[open] [id]").first().textContent().catch(() => "");
  check("a named confirmation opens", await dialog().isVisible(), title);
  const text = (await dialog().innerText()).replace(/\s+/g, " ");
  check("it says exactly what is affected and what is not", /Snapmaker PLA Matte @U1/.test(text) && /not changed/.test(text) && /similar spools, if there is one, still applies/.test(text), text.slice(0, 160));
  check("initial focus is on Cancel", /^Cancel$/.test((await active()) || ""), await active());
  check("nothing was sent just by asking", removeRequests.length === 0);
  await shot("02-confirmation");
  await page.getByRole("button", { name: "Cancel" }).click();
  await sleep(300);
  check("Cancel closes it and removes nothing", !(await dialog().isVisible().catch(() => false)) && removeRequests.length === 0 && mappingFile().length === 2);
  check("focus returns to the Forget control that opened it", /^Forget saved mapping for /.test((await active()) || ""), await active());

  /* Escape does the same */
  await page.keyboard.press("Enter");
  await dialog().waitFor();
  await page.keyboard.press("Escape");
  await sleep(300);
  check("Escape closes it and removes nothing", !(await dialog().isVisible().catch(() => false)) && removeRequests.length === 0 && mappingFile().length === 2);
  check("focus returns to the Forget control after Escape", /^Forget saved mapping for /.test((await active()) || ""), await active());

  /* a failed removal that cannot be confirmed */
  injectNext = { status: 500, body: { error: "internal" } };
  await page.keyboard.press("Enter");
  await dialog().waitFor();
  await page.getByRole("button", { name: "Confirm" }).click();
  await note().waitFor();
  const failText = (await note().innerText()).replace(/\s+/g, " ");
  check("a failed removal is reported as unconfirmed, not as done", /Couldn.t confirm the saved mapping was forgotten/.test(failText), failText);
  check("the saved mappings are untouched and still listed", mappingFile().length === 2 && (await forgetSpool().count()) === 1);
  await shotNote("03-failed-removal");

  /* the engine refuses because the mapping changed since it was shown */
  injectNext = { status: 400, body: { error: "mapping_refused", message: "That saved mapping has changed since it was shown. Nothing was forgotten." } };
  await forgetSpool().first().focus();
  await page.keyboard.press("Enter");
  await dialog().waitFor();
  await page.getByRole("button", { name: "Confirm" }).click();
  await note().filter({ hasText: "changed since it was shown" }).waitFor();
  check("a refused removal says plainly that nothing was forgotten", /Nothing was forgotten\./.test(await note().innerText()));
  check("the saved mappings are still there", mappingFile().length === 2);

  /* the engine cannot read its saved mappings (another program holds the file): nothing may change, and the message is accurate */
  const beforeBytes = readFileSync(join(dataDir, "material-mappings.json"));
  const holder = spawn(process.env.PYTHON || "py", ["-c", [
    "import msvcrt, os, sys",
    "fd = os.open(sys.argv[1], os.O_RDWR)",
    "msvcrt.locking(fd, msvcrt.LK_NBLCK, 4096)",          // a byte-range lock: other readers get a lock violation
    "print('locked', flush=True)",
    "sys.stdin.read()"].join("\n"), join(dataDir, "material-mappings.json")], { stdio: ["pipe", "pipe", "ignore"] });
  children.push(holder);
  await new Promise((resolve, reject) => { holder.stdout.once("data", resolve); setTimeout(() => reject(new Error("could not hold the mapping file")), 15000); });
  await forgetSpool().first().focus();
  await page.keyboard.press("Enter");
  await dialog().waitFor();
  await page.getByRole("button", { name: "Confirm" }).click();
  await note().filter({ hasText: "could not read its saved mappings" }).waitFor({ timeout: 20000 });
  const lockedNote = (await note().innerText()).replace(/\s+/g, " ");
  check("a file the engine cannot read is reported accurately: nothing was changed, try again", /in use by another program/.test(lockedNote) && /Nothing was changed\./.test(lockedNote) && !/Couldn.t confirm/.test(lockedNote), lockedNote);
  await shotNote("03b-saved-mappings-unreadable");
  holder.stdin.end();
  await sleep(500);
  check("it was not treated as corruption: the file is byte-identical and no .damaged file exists", Buffer.compare(readFileSync(join(dataDir, "material-mappings.json")), beforeBytes) === 0 && !existsSync(join(dataDir, "material-mappings.json.damaged")));
  check("and nothing was lost: both mappings are still saved", mappingFile().length === 2);

  /* choose a spool that rests on the kind-wide mapping, so forgetting it should clear that choice */
  await slot1().getByRole("button", { name: /^(?!Forget).*Red/ }).first().click();
  check("a spool can be chosen", (await slot1().getByTestId("selected-spool").count()) === 1);

  /* a real removal of the spool-specific mapping: only that row goes */
  await forgetSpool().first().focus();
  await page.keyboard.press("Enter");
  await dialog().waitFor();
  await page.getByRole("button", { name: "Confirm" }).click();
  await note().filter({ hasText: "Saved mapping forgotten." }).waitFor();
  const sent = removeRequests[removeRequests.length - 1];
  check("the request names exactly one mapping and the preset shown", sent.body.scope === "spool" && String(sent.body.spool_id) === "3" && sent.body.expect_preset_base === "Snapmaker PLA Matte @U1", JSON.stringify(sent.body));
  const rows = mappingFile();
  check("only the forgotten mapping left the engine's file", rows.length === 1 && rows[0].scope === "signature", JSON.stringify(rows.map((r) => [r.scope, r.spool_id ?? r.signature])));
  check("the list was read again: no Forget control remains for that spool", (await forgetSpool().count()) === 0 && (await forgetKind().count()) === 2);
  check("the chosen spool (kind-wide mapping, not the forgotten one) kept its choice", (await slot1().getByTestId("selected-spool").count()) === 1);
  check("focus is not lost to the page body", (await active()) !== "BODY", await active());
  await shotNote("04-after-forgetting-one-spool");

  /* the kind-wide mapping: forgetting it clears the choice that rested on it */
  await forgetKind().first().focus();
  await page.keyboard.press("Enter");
  await dialog().waitFor();
  const kindText = (await dialog().innerText()).replace(/\s+/g, " ");
  check("the kind-wide confirmation says it reaches every such spool, and a spool's own mapping keeps it", /every Acme Filament PLA spool/.test(kindText) && /has a mapping of its own keeps it/.test(kindText), kindText.slice(0, 200));
  await shot("05-confirmation-similar-spools");
  await page.getByRole("button", { name: "Confirm" }).click();
  await note().filter({ hasText: "cleared" }).waitFor();
  check("the choice that rested on the forgotten mapping was cleared, and the note says so", (await slot1().getByTestId("selected-spool").count()) === 0 && /Your choice for slot 1 was cleared\./.test(await note().innerText()), (await note().innerText()).replace(/\s+/g, " "));
  check("no saved mappings remain, and no Forget control", mappingFile().length === 0 && (await forgetKind().count()) === 0);
  await shotNote("06-after-forgetting-similar-spools");

  /* the inventory picker, when this build has it: a spool chosen through it, then its saved mapping forgotten */
  if (await page.getByRole("button", { name: "Choose another spool" }).count()) {
    const reseed = await post("/material_mapping/confirm", { scope: "signature", provider: "spoolman", vendor: "Acme Filament", material: "PLA", subtype: "", preset: "Snapmaker PLA SnapSpeed @U1", nozzle: "0.4" });
    check("(picker build) a kind-wide mapping can be saved again", reseed.status === 200);
    await page.goto(`${UI}/compatibility?api=${handshake.port}:${handshake.token}&file=${encodeURIComponent(projectPath)}`);
    await page.getByRole("button", { name: "Open a 3MF project" }).click();
    await page.getByText("Project materials").first().waitFor({ timeout: 30000 });
    await forgetKind().first().waitFor({ timeout: 30000 });
    await page.getByRole("button", { name: "Choose another spool" }).first().click();
    await page.getByTestId("inventory-picker").waitFor();
    await page.getByTestId("inventory-picker").getByRole("button", { name: /Blue/ }).first().click();
    await slot1().getByTestId("selected-spool").waitFor();
    check("(picker build) a spool chosen through the inventory picker is selected", (await slot1().getByTestId("selected-spool").count()) === 1);
    await shot("07-picker-choice-selected");
    await forgetKind().first().focus();
    await page.keyboard.press("Enter");
    await dialog().waitFor();
    await page.getByRole("button", { name: "Confirm" }).click();
    await note().filter({ hasText: "cleared" }).waitFor();
    check("(picker build) forgetting the mapping it rested on clears that choice", (await slot1().getByTestId("selected-spool").count()) === 0 && mappingFile().length === 0);
    check("(picker build) focus is not lost to the page body", (await active()) !== "BODY", await active());
  } else {
    console.log("(this build has no inventory picker: that part is skipped; it runs on a build that has both changes)");
  }

  check("no request named another provider, a printer, or discovery", violations.length === 0, violations.join("; "));
  check("the provider look-alike was read and never written", providerCalls.every((c) => c.startsWith("GET ")), [...new Set(providerCalls)].join(" | "));
  check("no unexpected console errors", errors.length === 0, errors.join(" | ").slice(0, 300));
} catch (e) {
  check("the run completed without a harness error", false, String(e && e.message || e));
  await shot("failure").catch(() => {});
} finally {
  await browser.close().catch(() => {});
  cleanup();
}
const failed = results.filter((r) => !r.ok).length;
writeFileSync(join(out, "results.json"), JSON.stringify({ browser: "Microsoft Edge (Chromium), headless", ui: UI, results, removeRequests, providerCalls }, null, 2));
console.log(`${results.length - failed}/${results.length} browser checks passed`);
process.exit(failed ? 1 : 0);
