#!/usr/bin/env node
// Check of the Project Materials usage notes (issue 39) in a real browser engine (Windows), in dark and light.
//
//   node tools/acceptance/materials-usage.mjs --out <folder>
//
// Starts, all on this machine and all stopped again at the end: the real Studio engine (throwaway data folder), the real
// Studio web UI (a vite dev server started from this checkout on a free port; an already-running server is never reused), and an anonymous Spoolman look-alike on
// 127.0.0.1:7912 that serves five made-up spools. Nothing here may reach a
// real printer or provider: the run is fail-closed, so any engine request that names another provider address, a printer,
// or network discovery is aborted and fails the run.
//
// The browser is Microsoft Edge (Chromium). It is not the Tauri window, WebKitGTK, or a screen reader.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
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
const out = process.argv.includes("--out") ? process.argv[process.argv.indexOf("--out") + 1] : join(tmpdir(), "materials-usage-evidence");
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


/* ---------- two anonymous five-colour projects ---------- */
const work = mkdtempSync(join(tmpdir(), "usage-"));
const MODEL_OK = '<config><object id="1"><metadata key="extruder" value="1"/></object><object id="2"><metadata key="extruder" value="2"/></object>' +
  '<object id="3"><metadata key="extruder" value="3"/></object></config>';
const CUSTOM = '<?xml version="1.0"?><custom_gcodes_per_layer><plate><plate_info id="1"/><layer top_z="4.2" type="2" extruder="4" color="#FFFFFF"/></plate></custom_gcodes_per_layer>';
function project(name, modelSettings, settingsIds) {
  const cfg = {
    version: "02.05.00.66", printer_model: "Generic Printer", printer_settings_id: "Generic Printer 0.4 nozzle",
    print_settings_id: "0.20mm Standard", filament_settings_id: settingsIds,
    filament_vendor: ["Generic", "Generic", "Generic", "Generic", "Generic"],
    filament_colour: ["#E0262A", "#1F5FD0", "#2E7D4F", "#F28C28", "#FFFFFF"],
    filament_type: ["PLA", "PLA", "PLA", "PLA", "PLA"], different_settings_to_system: ["", "", "", "", "", "", ""],
  };
  const files = { cfg: join(work, name + ".json"), ms: join(work, name + ".ms.xml"), cg: join(work, name + ".cg.xml") };
  writeFileSync(files.cfg, JSON.stringify(cfg)); writeFileSync(files.ms, modelSettings); writeFileSync(files.cg, CUSTOM);
  const path = join(work, name + ".3mf");
  const r = spawnSync(process.env.PYTHON || "py", ["-c", [
    "import zipfile,sys",
    "z=zipfile.ZipFile(sys.argv[1],'w')",
    "z.writestr('[Content_Types].xml','<?xml version=\"1.0\"?><Types/>')",
    "z.writestr('_rels/.rels','<?xml version=\"1.0\"?><Relationships/>')",
    "z.writestr('3D/3dmodel.model','<?xml version=\"1.0\"?><model/>')",
    "z.writestr('Metadata/project_settings.config',open(sys.argv[2]).read())",
    "z.writestr('Metadata/model_settings.config',open(sys.argv[3]).read())",
    "z.writestr('Metadata/custom_gcode_per_layer.xml',open(sys.argv[4]).read())",
    "z.close()"].join("\n"), path, files.cfg, files.ms, files.cg]);
  if (r.status !== 0) throw new Error(String(r.stderr));
  return path;
}
const IDS = ["Generic PLA @BBL H2D", "Generic PLA @BBL H2D", "Generic PLA @BBL H2D", "Generic PLA @BBL H2D", "Generic PLA @BBL H2D"];
const readable = project("readable", MODEL_OK, IDS);
const unreadable = project("unreadable", "<config><object", IDS);

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
const uiPort = await new Promise((resolve, reject) => {
  const probe = net.createServer();
  probe.once("error", reject);
  probe.listen(0, "127.0.0.1", () => { const { port } = probe.address(); probe.close(() => resolve(port)); });
});
const UI = `http://localhost:${uiPort}`;
const ui = spawn("npx.cmd", ["vite", "--port", String(uiPort), "--strictPort", "--host", "localhost"], { cwd: join(repo, "desktop"), stdio: "ignore", shell: true });
children.push(ui);
let uiReady = false;
for (let i = 0; i < 80 && !uiReady; i++) { try { const r = await fetch(`${UI}/`); uiReady = r.ok; } catch { /* not yet */ } if (!uiReady) await sleep(500); }
if (!uiReady) { console.error(`This checkout's UI did not come up on ${UI}.`); process.exit(2); }
console.log(`UI: started a dev server from this checkout on ${UI}`);

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`); };
const browser = await chromium.launch({ channel: "msedge", headless: true });
console.log(`browser: Edge ${browser.version()}`);
const violations = [];
const errors = [];

async function session(theme, fn) {
  const ctx = await browser.newContext({ viewport: { width: 1100, height: 2700 }, colorScheme: theme });
  await ctx.addInitScript((t) => {
    localStorage.setItem("theme", t);
    localStorage.setItem("u1Host", "127.0.0.1");
    localStorage.setItem("materialProviderKind", JSON.stringify("spoolman"));
    localStorage.setItem("materialProviderUrl", JSON.stringify("127.0.0.1:7912"));
  }, theme);
  // Fail closed: the engine may be asked about this project, this provider and the loopback address, and nothing else.
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
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR|Invalid DOM property/.test(m.text())) errors.push(m.text()); });
  try { await fn(page); } finally { await ctx.close(); }
}
async function openProject(page, path) {
  await page.goto(`${UI}/compatibility?api=${handshake.port}:${handshake.token}&file=${encodeURIComponent(path)}`);
  await page.getByRole("button", { name: "Open a 3MF project" }).click();
  await page.getByText("Project materials").first().waitFor({ timeout: 30000 });
  await page.getByTestId("slot-usage").first().waitFor({ timeout: 30000 });
}
const verdicts = (page) => page.getByTestId("slot-usage").evaluateAll((els) => els.map((e) => e.getAttribute("data-verdict")));

try {
  for (const theme of ["dark", "light"]) {
    await session(theme, async (page) => {
      const shot = (name) => page.screenshot({ path: join(out, `${name}-${theme}.png`), fullPage: true });
      await openProject(page, readable);
      const v1 = await verdicts(page);
      check(`${theme}: five colours read as referenced x4 and no reference found x1`,
        JSON.stringify(v1) === JSON.stringify(["referenced", "referenced", "referenced", "referenced", "no_reference_found"]), JSON.stringify(v1));
      const note = await page.getByTestId("beyond-toolheads").innerText();
      check(`${theme}: the card says the project is beyond the U1's 4 toolheads`, /5 materials, 1 beyond the U1's 4 toolheads/.test(note), note);
      check(`${theme}: the no-reference note does not claim the colour is unused`, /does not prove it is unused/.test(await page.getByTestId("slot-usage").nth(4).innerText()));
      check(`${theme}: no remove or merge action is offered`, (await page.getByRole("button", { name: /remove|merge|delete/i }).count()) === 0);
      await shot("01-five-colours");
      await page.locator('[data-slot="5"]').screenshot({ path: join(out, `01b-slot-5-no-reference-${theme}.png`) });

      await page.locator('[data-slot="1"]').getByRole("button", { name: "Choose another spool" }).click();
      await page.getByTestId("inventory-picker").getByRole("button", { name: /Red/ }).first().click();
      const hint = await page.locator('[data-slot="1"]').getByTestId("spool-without-preset").innerText();
      check(`${theme}: a Bambu preset with a spool chosen says how to choose a Snapmaker preset`,
        hint.startsWith("Spool selected, but no Orca preset selected. The project's existing filament preset will remain.") && /choose one under Orca preset/.test(hint), hint);
      await shot("02-spool-without-preset-bambu");

      await openProject(page, unreadable);
      const v2 = await verdicts(page);
      check(`${theme}: an unreadable object list leaves unreferenced colours unknown, never unused`,
        v2[0] === "unknown" && v2[4] === "unknown" && v2[3] === "referenced" && !v2.includes("no_reference_found"), JSON.stringify(v2));
      check(`${theme}: the unknown note says Studio cannot tell`, /Studio cannot tell whether this colour is used/.test(await page.getByTestId("slot-usage").first().innerText()));
      await shot("03-unreadable-project");
      await page.locator('[data-slot="5"]').screenshot({ path: join(out, `03b-slot-5-unknown-${theme}.png`) });
    });
  }
  check("no request named another provider, a printer, or discovery", violations.length === 0, violations.join(" | "));
  check("the provider look-alike was read and never written", providerCalls.every((c) => c.startsWith("GET ")), [...new Set(providerCalls)].join(", "));
  check("no unexpected console errors", errors.length === 0, errors.slice(0, 2).join(" | "));
} catch (e) {
  check("the run completed without a harness error", false, String(e?.message ?? e));
} finally {
  await browser.close();
  cleanup();
}
const failed = results.filter((r) => !r.ok).length;
writeFileSync(join(out, "results.json"), JSON.stringify({ browser: "Microsoft Edge (Chromium), headless", uiStartedByThisRun: true,
  passed: results.length - failed, failed, results }, null, 2));
console.log(`\n${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
