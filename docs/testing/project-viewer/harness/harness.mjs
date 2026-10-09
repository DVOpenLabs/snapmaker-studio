// Shared harness for PR 3b browser checks: starts the local engine (own data dir) and Vite dev server on free ports,
// launches Edge headless through playwright-core, and cleans up only the PIDs it started.
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, copyFileSync, readFileSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import net from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";

// The repository root, found from this file (docs/testing/project-viewer/harness/).
export const REPO = fileURLToPath(new URL("../../../../", import.meta.url)).replace(/[\/]$/, "");
export const OUT_DIR = process.env.P3B_OUT ?? join(tmpdir(), "p3b-out");
export const FIXTURES = process.env.P3B_FIXTURES ?? join(tmpdir(), "p3b-fixtures");
mkdirSync(OUT_DIR, { recursive: true });
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

const freePort = () => new Promise((resolve, reject) => {
  const p = net.createServer(); p.once("error", reject);
  p.listen(0, "127.0.0.1", () => { const { port } = p.address(); p.close(() => resolve(port)); });
});

export async function start({ preview = false, noUi = false } = {}) {
  const work = mkdtempSync(join(tmpdir(), "p3b-"));
  const backend = spawn(process.env.P3B_PYTHON ?? "py", ["-m", "snapstudio_api"], {
    cwd: join(REPO, "backend"), stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, SNAPSTUDIO_DATA_DIR: join(work, "data"), PYTHONPATH: join(REPO, "backend"), PYTHONUNBUFFERED: "1" },
  });
  children.push(backend);
  const handshake = await new Promise((resolve, reject) => {
    let buf = "";
    backend.stdout.on("data", (d) => { buf += d; const m = buf.match(/\{[^{}]*\}/); if (m) { try { resolve(JSON.parse(m[0])); } catch {} } });
    setTimeout(() => reject(new Error("engine did not report its port")), 60000);
  });
  if (noUi) return { work, handshake };
  const uiPort = await freePort();
  const UI = `http://localhost:${uiPort}`;
  children.push(spawn("npx.cmd", ["vite", ...(preview ? ["preview"] : []), "--port", String(uiPort), "--strictPort", "--host", "localhost"], { cwd: join(REPO, "desktop"), stdio: "ignore", shell: true }));
  let up = false;
  for (let i = 0; i < 80 && !up; i++) { try { up = (await fetch(`${UI}/`)).ok; } catch {} if (!up) await sleep(500); }
  if (!up) throw new Error("UI not up");
  return { work, handshake, UI };
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
