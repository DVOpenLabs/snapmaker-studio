// Shared harness for PR 3b browser checks: starts the local engine (own data dir) and Vite dev server on free ports,
// launches Edge headless through playwright-core, and cleans up only the PIDs it started.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, copyFileSync, readFileSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import net from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { FIXTURES, OUT_DIR, REPO } from "./paths.mjs";
export { FIXTURES, OUT_DIR, REPO };
// playwright-core comes from tools/acceptance (run `npm ci` there), or from PLAYWRIGHT_FROM: a folder that has node_modules/playwright-core.
const require = createRequire(join(process.env.PLAYWRIGHT_FROM ?? join(REPO, "tools", "acceptance"), "x.js"));
export const { chromium } = require("playwright-core");
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const sha = (p) => createHash("sha256").update(readFileSync(p)).digest("hex");

const children = [];
let cleaned = false;
export function cleanup() {
  if (cleaned) return;
  cleaned = true;
  for (const c of children) { try { spawnSync("taskkill", ["/PID", String(c.pid), "/T", "/F"], { stdio: "ignore" }); } catch {} }
}
process.on("exit", cleanup);
for (const s of ["SIGINT", "SIGTERM", "SIGBREAK"]) process.on(s, () => { cleanup(); process.exit(130); });

export const freePort = () => new Promise((resolve, reject) => {
  const p = net.createServer(); p.once("error", reject);
  p.listen(0, "127.0.0.1", () => { const { port } = p.address(); p.close(() => resolve(port)); });
});

/** Starts the local engine in its own data directory (optionally on a fixed port) and waits for its handshake line. */
export async function spawnEngine({ port, work = mkdtempSync(join(tmpdir(), "p3b-")) } = {}) {
  const backend = spawn(process.env.P3B_PYTHON ?? "py", ["-m", "snapstudio_api"], {
    cwd: join(REPO, "backend"), stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, SNAPSTUDIO_DATA_DIR: join(work, "data"), PYTHONPATH: join(REPO, "backend"), PYTHONUNBUFFERED: "1", ...(port ? { SNAPSTUDIO_API_PORT: String(port) } : {}) },
  });
  children.push(backend);
  const handshake = await new Promise((resolve, reject) => {
    let buf = "";
    backend.stdout.on("data", (d) => { buf += d; const m = buf.match(/\{[^{}]*\}/); if (m) { try { resolve(JSON.parse(m[0])); } catch {} } });
    setTimeout(() => reject(new Error("engine did not report its port")), 60000);
  });
  return { backend, handshake, work };
}

/** Stops one engine this script started (and its children). Never touches any other process. */
export function stopEngine(backend) {
  try { spawnSync("taskkill", ["/PID", String(backend.pid), "/T", "/F"], { stdio: "ignore" }); } catch {}
}

export async function start({ preview = false, noUi = false, enginePort } = {}) {
  const { handshake, work, backend } = await spawnEngine({ port: enginePort });
  if (noUi) return { work, handshake, backend };
  const uiPort = await freePort();
  const UI = `http://localhost:${uiPort}`;
  children.push(spawn("npx.cmd", ["vite", ...(preview ? ["preview"] : []), "--port", String(uiPort), "--strictPort", "--host", "localhost"], { cwd: join(REPO, "desktop"), stdio: "ignore", shell: true }));
  let up = false;
  for (let i = 0; i < 80 && !up; i++) { try { up = (await fetch(`${UI}/`)).ok; } catch {} if (!up) await sleep(500); }
  if (!up) throw new Error("UI not up");
  return { work, handshake, UI, backend };
}

/** Copies a repo example to a neutral folder so no username or temp path can appear in a screenshot. */
export function stage(name, dir) {
  mkdirSync(dir, { recursive: true });
  const dst = join(dir, name);
  copyFileSync(join(REPO, "examples", name), dst);
  return dst;
}

export function loopbackOnly(ctx, enginePort, violations) {
  const isLocal = (u) => /^(data:|blob:|about:)/.test(u) || ["localhost", "127.0.0.1"].includes(new URL(u).hostname);
  const FONTS = ["fonts.googleapis.com", "fonts.gstatic.com"];
  const blocked = new Set();
  ctx.route((url) => !isLocal(url.href), async (route) => {
    const h = new URL(route.request().url()).hostname;
    if (FONTS.includes(h)) blocked.add(h); else violations.push(`off-machine ${h}`);
    await route.abort();
  });
  ctx.route(`http://127.0.0.1:${enginePort}/**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith("/printer/") || /discover/i.test(url.pathname)) { violations.push(`${route.request().method()} ${url.pathname}`); await route.abort(); return; }
    await route.continue();
  });
  return blocked;
}

export async function launch() {
  return chromium.launch({ channel: "msedge", headless: true, args: ["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
}

export { statSync };
