// Local capture harness for the job screen: the real Studio engine (throwaway data folder) and this checkout's real
// web UI (vite dev server on a free port) driven in Microsoft Edge. Synthetic fixtures only. Nothing leaves this
// machine: requests to any other host are aborted and recorded, and any engine request naming a printer or
// network discovery is aborted and recorded. Not the Tauri window, WebKitGTK or a screen reader.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync } from "node:fs";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveTimeout, startEngine, stopChild } from "../acceptance/engine-startup.mjs";

const here = dirname(fileURLToPath(import.meta.url));
export const repo = join(here, "..", "..");
const require = createRequire(join(repo, "tools", "acceptance", "package.json"));
const { chromium } = require("playwright-core");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const KNOWN_FONT_HOSTS = ["fonts.googleapis.com", "fonts.gstatic.com"];

export async function launch() {
  const children = [];
  const violations = [];
  const errors = [];
  const work = mkdtempSync(join(tmpdir(), "job-journey-"));
  const cleanup = () => { for (const c of children) stopChild(c); };
  process.on("exit", cleanup);
  for (const sig of ["SIGINT", "SIGTERM", "SIGBREAK"]) process.on(sig, () => { cleanup(); process.exit(130); });

  const { handshake } = await startEngine({
    command: process.env.PYTHON || "py", args: ["-m", "snapstudio_api"], repoRoot: repo, cwd: join(repo, "backend"),
    env: { ...process.env, SNAPSTUDIO_DATA_DIR: join(work, "data"), PYTHONUNBUFFERED: "1" },
    timeoutMs: resolveTimeout(process.env.SNAPSTUDIO_ENGINE_TIMEOUT_MS), onSpawn: (c) => children.push(c),
  });
  const uiPort = await new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => { const { port } = probe.address(); probe.close(() => resolve(port)); });
  });
  const UI = `http://localhost:${uiPort}`;
  children.push(spawn("npx.cmd", ["vite", "--port", String(uiPort), "--strictPort", "--host", "localhost"], { cwd: join(repo, "desktop"), stdio: "ignore", shell: true }));
  let ready = false;
  for (let i = 0; i < 80 && !ready; i++) { try { ready = (await fetch(`${UI}/`, { signal: AbortSignal.timeout(2000) })).ok; } catch { /* not yet */ } if (!ready) await sleep(500); }
  if (!ready) { cleanup(); throw new Error(`UI did not come up on ${UI}`); }
  const browser = await chromium.launch({ channel: "msedge", headless: true });

  const isLocal = (u) => /^(data:|blob:|about:)/.test(u) || ["localhost", "127.0.0.1"].includes(new URL(u).hostname);
  async function newPage({ theme = "light", width = 1280, height = 800, reducedMotion = "no-preference" } = {}) {
    const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: theme, reducedMotion, serviceWorkers: "block" });
    await ctx.addInitScript((t) => { localStorage.setItem("theme", t); localStorage.setItem("u1Host", "127.0.0.1"); }, theme);
    await ctx.route((url) => !isLocal(url.href), async (route) => {
      const h = new URL(route.request().url()).hostname;
      if (!KNOWN_FONT_HOSTS.includes(h)) violations.push(`off-machine ${h}`);
      await route.abort();
    });
    await ctx.route(`http://127.0.0.1:${handshake.port}/**`, async (route) => {
      const url = new URL(route.request().url());
      let body = {};
      try { body = JSON.parse(route.request().postData() || "{}") ?? {}; } catch { /* not JSON */ }
      const other = (body.host !== undefined && String(body.host).trim() !== "127.0.0.1") || (Array.isArray(body.hosts) && body.hosts.some((h) => String(h).trim() !== "127.0.0.1"));
      if (url.pathname.startsWith("/printer/") || /discover/i.test(url.pathname) || other) { violations.push(`${route.request().method()} ${url.pathname}`); await route.abort(); return; }
      await route.continue();
    });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR|Invalid DOM property/.test(m.text())) errors.push(m.text()); });
    const go = async (route) => { await page.goto(`${UI}${route}${route.includes("?") ? "&" : "?"}api=${handshake.port}:${handshake.token ?? ""}`); await page.waitForLoadState("networkidle").catch(() => {}); };
    // Same store module instance the app uses (vite serves one module per URL).
    const openProject = async (path) => { await page.evaluate(async (p) => { const m = await import("/src/store/session.ts"); m.useSession.getState().setFile(p); }, path); };
    return { ctx, page, go, openProject };
  }
  const fixture = (name) => { const dst = join(work, name.split("/").pop()); copyFileSync(join(repo, "backend", "tests", "fixtures", name), dst); return dst; };
  const close = async () => { await browser.close().catch(() => {}); cleanup(); };
  return { newPage, fixture, work, violations, errors, close, handshake, UI };
}
