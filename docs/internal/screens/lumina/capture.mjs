#!/usr/bin/env node
// Captures the Lumina service screenshots (Windows). Real engine + this checkout's own UI (vite dev server) +
// headless Edge, against a SYNTHETIC loopback stand-in service (backend/tests/mocks/lumina_server.py).
//
//   PYTHON=<python 3.13+ with the backend importable> \
//   ACCEPTANCE_DIR=<folder with node_modules/playwright-core> node docs/internal/screens/lumina/capture.mjs
//
// Starts and stops, all on this machine: the engine (throwaway data folder; its working directory is the throwaway
// folder so the screenshots show a short relative file name, never a real path), the stand-in service on 127.0.0.1,
// and a vite dev server on a free port. The image is a few synthetic bytes. No real Lumina, no printer, no network host.
// The capture FAILS if the rendered page text contains the throwaway folder or a user-profile path.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..", "..", "..");
const acceptance = process.env.ACCEPTANCE_DIR || join(repo, "tools", "acceptance");
const { chromium } = createRequire(join(acceptance, "package.json"))("playwright-core");
const python = process.env.PYTHON || "py";
const out = here;
const work = mkdtempSync(join(tmpdir(), "lumina-shot-"));
const proj = join(work, "inputs");
mkdirSync(proj);
writeFileSync(join(proj, "synthetic.png"), Buffer.from("synthetic-image-bytes-not-a-real-picture"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const children = [];
const cleanup = () => { for (const c of children) { try { spawnSync("taskkill", ["/PID", String(c.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* gone */ } } };
process.on("exit", cleanup);

const firstJson = (child, label) => new Promise((ok, fail) => {
  let buf = "";
  child.stdout.on("data", (d) => { buf += d; const m = buf.match(/\{[^{}]*\}/); if (m) { try { ok(JSON.parse(m[0])); } catch { /* keep reading */ } } });
  setTimeout(() => fail(new Error(`${label} did not report in time`)), 60000);
});

// The synthetic stand-in service (a started child so it is stopped with the others).
const service = spawn(python, ["-I", "-c", `
import json, sys, time
sys.path.insert(0, ${JSON.stringify(join(repo, "backend"))})
from tests.mocks.lumina_server import LuminaHttpMock
with LuminaHttpMock() as mock:
    print(json.dumps({"url": mock.url}), flush=True)
    time.sleep(600)
`], { stdio: ["ignore", "pipe", "pipe"] });
children.push(service);
const svc = await firstJson(service, "stand-in service");

const backend = spawn(python, ["-m", "snapstudio_api"], {
  cwd: proj, stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, SNAPSTUDIO_DATA_DIR: join(work, "data"), SNAPSTUDIO_ORCA_DATA_DIR: join(work, "orca"),
         PYTHONPATH: join(repo, "backend"), PYTHONUNBUFFERED: "1" },
});
children.push(backend);
const hs = await firstJson(backend, "engine");
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
const ctx = await browser.newContext({ viewport: { width: 1280, height: 760 }, colorScheme: "dark" });
await ctx.addInitScript(() => { localStorage.setItem("theme", "dark"); localStorage.setItem("mode", "advanced"); });
const page = await ctx.newPage();
page.on("pageerror", (e) => console.log("PAGEERROR", e.message));
await page.goto(`${UI}/lumina?api=${hs.port}:${hs.token}`);
await page.getByLabel("Output format").locator("option", { hasText: "glb" }).waitFor({ state: "attached", timeout: 20000 });

const FORBIDDEN = [work, work.replace(/\\/g, "/"), "\\Users\\", "/Users/"];
const shot = async (name) => {
  await sleep(300);
  const text = await page.locator("body").innerText();
  for (const bad of FORBIDDEN) {
    if (text.includes(bad)) { console.error(`FAIL: ${name} page text contains a local path fragment`); process.exit(3); }
  }
  await page.screenshot({ path: join(out, name), fullPage: true });
  console.log(name, "->", text.split("\n").filter(Boolean).slice(0, 30).join(" | "));
};
const fill = async (url, format) => {
  await page.getByLabel("Service address").fill(url);
  await page.getByLabel("Image file path").fill("synthetic.png");
  await page.getByLabel("LUT name").fill("Default");
  await page.getByLabel("Output format").selectOption(format);
};

// 1. The form as first opened, then filled in with a format chosen.
await shot("form-empty.png");
await fill(svc.url, "png");
await page.getByRole("button", { name: "Check service" }).click();
await page.getByText("answered Studio's identity check").first().waitFor({ timeout: 20000 });
await shot("form-filled-service-checked.png");

// 2. A successful result.
await page.getByRole("button", { name: "Generate", exact: true }).click();
await page.getByText("A new png file was saved").first().waitFor({ timeout: 30000 });
await shot("result-success.png");

// 3. The service returned a different kind than the one chosen: refused, nothing saved, the list is named.
await page.getByLabel("Output format").selectOption("3mf");
await page.getByRole("button", { name: "Generate", exact: true }).click();
await page.getByText("Nothing was saved").first().waitFor({ timeout: 30000 });
await shot("refusal-format-not-produced.png");

// 4. A non-local service address is refused before anything is sent.
await fill("http://8.8.8.8:8000", "png");
await page.getByRole("button", { name: "Generate", exact: true }).click();
await page.getByText("not on your own network").first().waitFor({ timeout: 30000 });
await shot("refusal-non-local-address.png");

await browser.close();
cleanup();
process.exit(0);
