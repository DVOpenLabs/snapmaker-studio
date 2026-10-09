// Production build served with the app's real Tauri CSP; Tauri calls are stubbed so the built app can find the local engine.
import { start, stage, launch, cleanup, sleep, sha, OUT_DIR, FIXTURES, REPO } from "./harness.mjs";
import { readFileSync, writeFileSync } from "node:fs";
const conf = JSON.parse(readFileSync(pj(REPO, "desktop", "src-tauri", "tauri.conf.json"), "utf8"));
const CSP = conf.app.security.csp;
const { handshake } = await start({ noUi: true });
// A small static server for the production build, sending the app's real CSP as a header (route interception would make
// the page look like a non-local origin to the browser's loopback rules).
import http from "node:http";
import { readFileSync as rf, existsSync, statSync } from "node:fs";
import { extname, join as pj } from "node:path";
import { resolve as pres } from "node:path";
const DIST = pres(pj(REPO, "desktop", "dist"));
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json" };
const srv = http.createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  let f = pres(DIST, "." + p);
  if (!f.startsWith(DIST) || !existsSync(f) || statSync(f).isDirectory()) f = pres(DIST, "index.html");
  res.writeHead(200, { "content-type": TYPES[extname(f)] || "application/octet-stream", "content-security-policy": CSP });
  res.end(rf(f));
}).listen(0, "127.0.0.1");
await sleep(200);
const UI = `http://localhost:${srv.address().port}`;
const file = stage("demo_offplate_foreign.3mf", FIXTURES);
const before = sha(file);
const browser = await launch();
const out = { csp: CSP, violations: [], consoleErrors: [], offMachine: [] };
try {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 }, serviceWorkers: "block" });
  await ctx.addInitScript(([port, token, f]) => {
    localStorage.setItem("theme", "dark"); localStorage.setItem("mode", "advanced");
    window.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
    let cb = 0;
    window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener() {} };
    window.__TAURI_INTERNALS__ = {
      invoke: async (cmd) => (cmd === "get_api_info" ? { port, token } : cmd === "get_launch_file" || cmd === "plugin:dialog|open" ? f : null),
      transformCallback: () => ++cb, unregisterCallback() {}, convertFileSrc: (p) => p, metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main", windowLabel: "main" } },
    };
  }, [handshake.port, handshake.token, file]);
  await ctx.route((url) => !["localhost", "127.0.0.1"].includes(url.hostname) && !/^(data|blob|about):/.test(url.href), async (r) => { const h = new URL(r.request().url()).hostname; if (!/fonts\.(googleapis|gstatic)\.com/.test(h)) out.offMachine.push(h); await r.abort(); });
  await ctx.route(`http://127.0.0.1:${handshake.port}/**`, async (route) => {
    const u = new URL(route.request().url());
    if (u.pathname.startsWith("/printer/") || /discover/i.test(u.pathname)) { await route.abort(); return; }
    await route.continue();
  });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR/.test(m.text())) out.consoleErrors.push(m.text().slice(0, 240)); });
  page.on("pageerror", (e) => out.consoleErrors.push("pageerror " + String(e).slice(0, 240)));
  await page.goto(`${UI}/`);
  await page.locator("#brand-splash").waitFor({ state: "detached", timeout: 30000 });
  await page.getByRole("button", { name: /Open a model/ }).first().click();
  await page.getByTestId("project-scene").waitFor({ timeout: 90000 });
  await page.waitForFunction(() => ([...document.querySelectorAll('[data-testid="project-scene"] button')].find((b) => b.textContent === "Top") || {}).disabled === false, null, { timeout: 90000 });
  await sleep(2000);
  out.canvasCount = await page.evaluate(() => document.querySelectorAll("canvas").length);
  out.viewerWorking = true;
  out.violations = await page.evaluate(() => window.__csp);
  out.isProductionBuild = await page.evaluate(() => !document.querySelector('script[src*="/@vite/client"]'));
  await page.getByTestId("project-scene").screenshot({ path: pj(OUT_DIR, "csp-production.png") });
} catch (e) { out.harnessError = String(e?.stack ?? e).slice(0, 600); }
finally { await browser.close(); srv.close(); cleanup(); }
out.originalUnchanged = sha(file) === before;
writeFileSync(pj(OUT_DIR, "csp-results.json"), JSON.stringify(out, null, 2));
console.log(JSON.stringify(out, null, 1));
process.exit(0);
