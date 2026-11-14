#!/usr/bin/env node
// Captures the Assemblies screenshots (Windows). Real engine + this checkout's own UI (vite dev server) + headless Edge.
//
//   ACCEPTANCE_DIR=<folder with node_modules/playwright-core> node docs/internal/screens/assemblies/capture.mjs
//
// Starts and stops, all on this machine: the engine (throwaway data folder), a vite dev server on a free port. No printer,
// no provider, no network host. Every figure on screen is the synthetic sample the page loads itself.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..", "..", "..");
const acceptance = process.env.ACCEPTANCE_DIR || join(repo, "tools", "acceptance");
const { chromium } = createRequire(join(acceptance, "package.json"))("playwright-core");
const out = here;
const work = mkdtempSync(join(tmpdir(), "assemblies-shot-"));
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
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1500 }, colorScheme: "dark" });
await ctx.addInitScript(() => { localStorage.setItem("theme", "dark"); });
const page = await ctx.newPage();
page.on("pageerror", (e) => console.log("PAGEERROR", e.message));
await page.goto(`${UI}/assemblies?api=${hs.port}:${hs.token}`);
await page.getByRole("button", { name: "Load sample assembly" }).click();

const check = async () => {
  await page.getByRole("button", { name: "Check spools" }).click();
  await page.getByTestId("assembly-report").waitFor({ timeout: 15000 });
  await sleep(300);
};
const verdict = async (label) => console.log(label, "->", await page.getByTestId("overall-verdict").innerText());

// 1. shortage: fresh readings, the road spool is short.
await check(); await verdict("shortage");
console.log(await page.getByTestId("spool-row").allInnerTexts());
await page.screenshot({ path: join(out, "shortage.png"), fullPage: true });

// 2. stale: the same readings, dated a day ago.
const supply = JSON.parse(await page.getByLabel("Spool readings JSON").inputValue());
await page.getByLabel("Spool readings JSON").fill(JSON.stringify(supply.map((s) => ({ ...s, observed_at: s.observed_at - 90000 })), null, 2));
await check(); await verdict("stale");
await page.screenshot({ path: join(out, "stale-supply.png"), fullPage: true });

// 3. unknown: no readings, and the water role has no spool chosen.
const asm = JSON.parse(await page.getByLabel("Assembly JSON").inputValue());
delete asm.bindings.water;
await page.getByLabel("Assembly JSON").fill(JSON.stringify(asm, null, 2));
await page.getByLabel("Spool readings JSON").fill("");
await check(); await verdict("unknown");
await page.screenshot({ path: join(out, "unknown-no-reading-unbound-role.png"), fullPage: true });

// 4. save, then the saved list offers it back.
await page.getByRole("button", { name: "Save assembly" }).click();
await page.getByRole("status").waitFor();
console.log("notice:", await page.getByRole("status").innerText());
console.log("saved list options:", await page.getByLabel("Saved assemblies").locator("option").allInnerTexts());
await browser.close();
cleanup();
process.exit(0);
