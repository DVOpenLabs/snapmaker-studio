#!/usr/bin/env node
// Captures the Recovery screenshots (Windows). Real engine + this checkout's own UI (vite dev server) + headless Edge.
//
//   ACCEPTANCE_DIR=<folder with node_modules/playwright-core> node docs/internal/screens/recovery/capture.mjs
//
// Starts and stops, all on this machine: the engine (throwaway data folder), a vite dev server, and a tiny
// loopback mock that answers the two read-only monitoring GETs on 127.0.0.1:7125. No printer, no provider.
// Every name and value is synthetic.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import http from "node:http";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..", "..", "..");
const acceptance = process.env.ACCEPTANCE_DIR || join(repo, "tools", "acceptance");
const { chromium } = createRequire(join(acceptance, "package.json"))("playwright-core");
const out = here;
const work = mkdtempSync(join(tmpdir(), "recovery-shot-"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const children = [];
const cleanup = () => { for (const c of children) { try { spawnSync("taskkill", ["/PID", String(c.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* gone */ } } };
process.on("exit", cleanup);

const backend = spawn(process.env.PYTHON || "py", ["-m", "snapstudio_api"], {
  cwd: join(repo, "backend"), stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, SNAPSTUDIO_DATA_DIR: join(work, "data"), SNAPSTUDIO_ORCA_DATA_DIR: join(work, "orca"),
         PYTHONPATH: join(repo, "backend"), PYTHONUNBUFFERED: "1" },
});
children.push(backend);
const hs = await new Promise((ok, fail) => {
  let buf = "";
  backend.stdout.on("data", (d) => { buf += d; const m = buf.match(/\{[^{}]*\}/); if (m) { try { ok(JSON.parse(m[0])); } catch { /* keep reading */ } } });
  setTimeout(() => fail(new Error("engine did not report its port")), 60000);
});
const post = async (path, body) => {
  const res = await fetch(`http://127.0.0.1:${hs.port}${path}`, { method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": hs.token }, body: JSON.stringify(body) });
  return res.json();
};

// Synthetic tracked files: one stays, one is replaced, one is removed after the checkpoint.
const files = join(work, "files"); mkdirSync(files);
for (const n of ["bracket.3mf", "lid.3mf", "gear.3mf"]) writeFileSync(join(files, n), `synthetic ${n}`);
console.log("checkpoint", await post("/recovery/checkpoint", {
  workspace: { project: "Synthetic demo", stage: "review" }, observations: [],
  files: ["bracket.3mf", "lid.3mf", "gear.3mf"].map((n) => ({ name: n, path: join(files, n) })),
  jobs: [{ job_id: "job-demo-1", state: "running" }],
}));
writeFileSync(join(files, "lid.3mf"), "synthetic lid, edited after the checkpoint");
rmSync(join(files, "gear.3mf"));

const mock = http.createServer((req, res) => {
  res.setHeader("Content-Type", "application/json");
  if (req.url.startsWith("/printer/objects/query")) res.end(JSON.stringify({ result: { status: { print_stats: { filename: "bracket.gcode", state: "printing" } } } }));
  else res.writeHead(404).end("{}");
});
let mocked = true;
await new Promise((ok) => { mock.once("error", () => { mocked = false; ok(); }); mock.listen(7125, "127.0.0.1", ok); });
console.log("mock on 7125:", mocked);

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
await page.goto(`${UI}/recovery?api=${hs.port}:${hs.token}`);
await page.getByTestId("restore-preview").waitFor({ timeout: 20000 });
await sleep(300);
console.log(await page.getByTestId("restore-preview").innerText());
await page.screenshot({ path: join(out, "restore-preview.png"), fullPage: true });

await page.getByRole("button", { name: "Save sample checkpoint" }).click();
await page.getByText(/Checkpoint saved/).waitFor({ timeout: 15000 });
await sleep(400);
await page.screenshot({ path: join(out, "after-new-checkpoint.png"), fullPage: true });

if (mocked) {
  await page.getByLabel("Configured printer host").fill("127.0.0.1");
  await page.getByRole("button", { name: "Read status" }).click();
  await page.getByTestId("monitor-summary").waitFor({ timeout: 15000 });
  console.log(await page.getByTestId("monitor-summary").innerText());
  await page.screenshot({ path: join(out, "monitoring-unverified.png"), fullPage: true });
}
await browser.close();
mock.close();
process.exit(0);
