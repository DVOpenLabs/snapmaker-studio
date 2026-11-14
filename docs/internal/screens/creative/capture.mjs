#!/usr/bin/env node
// Captures the Creative import screenshots (Windows). Real engine + this checkout's own UI (vite dev server) + headless Edge.
//
//   ACCEPTANCE_DIR=<folder with node_modules/playwright-core> node docs/internal/screens/creative/capture.mjs
//
// Starts and stops, all on this machine: the engine (throwaway data folder, working directory is the throwaway
// folder so the screenshots show short relative file names, never a real path), a vite dev server on a free port.
// The three project files are synthetic archives written by the checked-in test helper. No printer, no network host.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync } from "node:fs";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..", "..", "..");
const acceptance = process.env.ACCEPTANCE_DIR || join(repo, "tools", "acceptance");
const { chromium } = createRequire(join(acceptance, "package.json"))("playwright-core");
const out = here;
const work = mkdtempSync(join(tmpdir(), "creative-shot-"));
const proj = join(work, "projects");
mkdirSync(proj);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const children = [];
const cleanup = () => { for (const c of children) { try { spawnSync("taskkill", ["/PID", String(c.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* gone */ } } };
process.on("exit", cleanup);

// Synthetic fixtures, built with the same helper the tests use.
const gen = spawnSync(process.env.PYTHON || "py", ["-I", "-c", `
import sys
sys.path.insert(0, ${JSON.stringify(join(repo, "backend", "tests", "fixtures", "creative"))})
from zip_factory import make_3mf
import pathlib
d = pathlib.Path(sys.argv[1])
(d / "sample-fullspectrum.3mf").write_bytes(make_3mf(
    settings={"mixed_filament_definitions": "1,2,1,0,50,0,u7;2,3,1,0,40,0,g12,u8", "layer_height": "0.2", "wall_loops": 3},
    members={"Metadata/plate_1.png": b"synthetic-preview", "Metadata/slice_info.config": b"synthetic"}))
(d / "sample-forca.3mf").write_bytes(make_3mf(
    settings={"fos_mms_unit_count": 2, "fos_future_key": 1, "nozzle_diameter": ["0.4", "0.4"], "layer_height": "0.16"},
    members={"Metadata/plate_1.png": b"synthetic-preview"}))
(d / "sample-other.3mf").write_bytes(make_3mf(
    settings={"layer_height": "0.2"}, members={"Metadata/custom.bin": b"synthetic-opaque"}))
`, proj], { encoding: "utf8" });
if (gen.status !== 0) { console.error(gen.stderr); process.exit(2); }

const backend = spawn(process.env.PYTHON || "py", ["-m", "snapstudio_api"], {
  cwd: proj, stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, SNAPSTUDIO_DATA_DIR: join(work, "data"), SNAPSTUDIO_ORCA_DATA_DIR: join(work, "orca"),
         PYTHONPATH: join(repo, "backend"), PYTHONUNBUFFERED: "1" },
});
children.push(backend);
const hs = await new Promise((ok, fail) => {
  let buf = "";
  backend.stdout.on("data", (d) => { buf += d; const m = buf.match(/\{[^{}]*\}/); if (m) { try { ok(JSON.parse(m[0])); } catch { /* keep reading */ } } });
  setTimeout(() => fail(new Error("engine did not report its port")), 60000);
});
const port = await new Promise((ok, fail) => {
  const p = net.createServer(); p.once("error", fail);
  p.listen(0, "127.0.0.1", () => { const { port } = p.address(); p.close(() => ok(port)); });
});
const UI = `http://localhost:${port}`;
children.push(spawn("npx.cmd", ["vite", "--port", String(port), "--strictPort", "--host", "localhost"], { cwd: join(repo, "desktop"), stdio: "ignore", shell: true }));
let ready = false;
for (let i = 0; i < 80 && !ready; i++) { try { ready = (await fetch(UI + "/")).ok; } catch { /* not yet */ } if (!ready) await sleep(500); }
if (!ready) { console.error("UI did not come up"); process.exit(2); }

const browser = await chromium.launch({ channel: "msedge", headless: true });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1100 }, colorScheme: "dark" });
await ctx.addInitScript(() => { localStorage.setItem("theme", "dark"); });
const page = await ctx.newPage();
page.on("pageerror", (e) => console.log("PAGEERROR", e.message));
await page.goto(`${UI}/creative?api=${hs.port}:${hs.token}`);

const inspect = async (file, shot, waitText) => {
  await page.getByLabel("Project file path").fill(file);
  await page.getByRole("button", { name: "Inspect project" }).click();
  await page.getByText(waitText).first().waitFor({ timeout: 15000 });
  await sleep(300);
  await page.screenshot({ path: join(out, shot), fullPage: true });
  console.log(shot, "->", (await page.locator("main, body").first().innerText()).split("\n").slice(0, 40).join(" | "));
};
await inspect("sample-fullspectrum.3mf", "fullspectrum-recipes.png", "Original unchanged");
await inspect("sample-forca.3mf", "forca-expected-and-unknown.png", "Original unchanged");
await inspect("sample-other.3mf", "unknown-origin.png", "Origin unknown");
await browser.close();
cleanup();
process.exit(0);
