#!/usr/bin/env node
// Offline check that Studio's web UI asks nothing of the outside world for fonts (issue #94). Windows, Microsoft Edge.
//
//   node tools/acceptance/local-fonts-offline.mjs --out <folder> [--tag before|after] [--mode dev|preview]
//
// Starts the Studio web UI from this checkout (vite dev server, or `vite build` + `vite preview`) on a free loopback
// port, loads it in Edge with every request recorded, aborts any request that is not loopback / data: / blob:, and
// fails if one was attempted or if no text rendered. Screenshots are taken in dark and light themes. No engine is
// started, so the UI shows its "engine not reachable" state; that is enough to prove fonts and text, nothing more.
// It is not the packaged Tauri window and not WebKitGTK.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import net from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

if (process.platform !== "win32") { console.error("This check is written for Windows (taskkill, npx.cmd)."); process.exit(2); }
const here = dirname(fileURLToPath(import.meta.url));
const desktop = join(here, "..", "..", "desktop");
const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");
const arg = (n, d) => (process.argv.includes(n) ? process.argv[process.argv.indexOf(n) + 1] : d);
const out = resolve(arg("--out", join(here, "local-fonts-evidence")));
const tag = arg("--tag", "run");
const mode = arg("--mode", "dev");
mkdirSync(out, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const children = [];
const dist = mkdtempSync(join(tmpdir(), "local-fonts-dist-"));
const cleanup = () => { for (const c of children) { try { spawnSync("taskkill", ["/PID", String(c.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* gone */ } } try { rmSync(dist, { recursive: true, force: true }); } catch { /* gone */ } };
process.on("exit", cleanup);
for (const sig of ["SIGINT", "SIGTERM", "SIGBREAK"]) process.on(sig, () => { cleanup(); process.exit(130); });

const freePort = () => new Promise((res) => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); }); });
const port = await freePort();
const run = (args) => { const c = spawn("npx.cmd", ["vite", ...args], { cwd: desktop, stdio: "ignore", shell: true }); children.push(c); return c; };
if (mode === "preview") {
  const b = spawnSync("npx.cmd", ["vite", "build", "--outDir", dist], { cwd: desktop, stdio: "ignore", shell: true });
  if (b.status !== 0) { console.error("vite build failed"); process.exit(1); }
  run(["preview", "--outDir", dist, "--port", String(port), "--strictPort", "--host", "127.0.0.1"]);
} else {
  run(["--port", String(port), "--strictPort", "--host", "127.0.0.1"]);
}
const base = `http://127.0.0.1:${port}/`;
for (let i = 0; ; i++) {
  try { if ((await fetch(base)).ok) break; } catch { /* not up yet */ }
  if (i > 120) { console.error("web UI did not start"); process.exit(1); }
  await sleep(500);
}

const isLocal = (u) => {
  if (/^(data|blob|about):/.test(u)) return true;
  try { const h = new URL(u).hostname; return h === "127.0.0.1" || h === "localhost" || h === "[::1]" || h === "::1"; } catch { return false; }
};
const seen = [];
const blocked = [];
const browser = await chromium.launch({ channel: "msedge", headless: true });
const results = [];
for (const theme of ["dark", "light"]) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await ctx.addInitScript((t) => localStorage.setItem("theme", t), theme);
  await ctx.route("**/*", (route) => {
    const u = route.request().url();
    seen.push(u);
    if (isLocal(u)) return route.continue();
    blocked.push(u);
    return route.abort();
  });
  const page = await ctx.newPage();
  await page.goto(base, { waitUntil: "load" });
  await page.waitForTimeout(2500);
  const info = await page.evaluate(async () => {
    await document.fonts.ready;
    const cs = (el) => getComputedStyle(el).fontFamily;
    return {
      bodyFont: cs(document.body),
      monoFont: cs(Object.assign(document.body.appendChild(document.createElement("code")), { className: "font-mono", textContent: "x" })),
      textLength: document.body.innerText.trim().length,
      dark: document.documentElement.classList.contains("dark"),
      fontFacesLoaded: [...document.fonts].filter((f) => f.status === "loaded").length,
    };
  });
  await page.screenshot({ path: join(out, `${tag}-${theme}.png`) });
  results.push({ theme, ...info });
  await ctx.close();
}
await browser.close();
const checks = [
  ["no request left loopback", blocked.length === 0],
  ["text rendered in both themes", results.every((r) => r.textLength > 20)],
  ["theme applied as requested", results[0].dark === true && results[1].dark === false],
];
const report = { tag, mode, requestsSeen: seen.length, nonLoopbackAttempts: blocked, results, checks: checks.map(([n, ok]) => ({ check: n, pass: ok })) };
writeFileSync(join(out, `${tag}-${mode}.json`), JSON.stringify(report, null, 2));
for (const [n, ok] of checks) console.log(`${ok ? "PASS" : "FAIL"}  ${n}`);
console.log(`requests seen: ${seen.length}; non-loopback attempts: ${blocked.length}`);
for (const b of blocked) console.log(`  blocked: ${b}`);
console.log(JSON.stringify(results));
process.exit(checks.every(([, ok]) => ok) ? 0 : 1);
