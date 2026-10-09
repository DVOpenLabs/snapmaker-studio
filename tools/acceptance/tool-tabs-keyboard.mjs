#!/usr/bin/env node
// Keyboard check of the Compatibility and Print Quality tab rows in a real browser engine (Windows).
//
//   node tools/acceptance/tool-tabs-keyboard.mjs --out <folder>
//
// Starts, all on this machine and all stopped again at the end: the real Studio engine (throwaway data folder) and the
// real Studio web UI (a vite dev server started from this checkout on a free port; an already-running server is never
// reused). Only the keyboard is used to operate the tabs. No file is opened.
//
// Browser network guard (fail-closed for what the browser does): requests to Google Fonts (fonts.googleapis.com,
// fonts.gstatic.com) are aborted and recorded in results.json but do not fail the run; the app asks for them today. Every
// other request or WebSocket to a host other than this machine is aborted and fails the run, and so does any engine request
// that names a printer or network discovery. Service workers are blocked. Not interceptable from here: WebRTC and
// browser-internal traffic.
//
// NOT covered: the spawned engine process (backend) makes its own network calls, and this run neither constrains nor
// observes them. This script does not claim that process stays on this machine.
//
// results.json records the base commit, whether the worktree was dirty, and a hash of the uncommitted change, because the
// run is made on uncommitted code on top of the base commit.
//
// The browser is Microsoft Edge (Chromium). It is not the Tauri window, WebKitGTK, or a screen reader.
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { startEngine, stopTree } from "./engine-startup.mjs";

if (process.platform !== "win32") { console.error("This check is written for Windows (taskkill, npx.cmd)."); process.exit(2); }
const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");
const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");
const out = process.argv.includes("--out") ? process.argv[process.argv.indexOf("--out") + 1] : join(tmpdir(), "tool-tabs-evidence");
mkdirSync(out, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const children = [];
let cleaned = false;
function cleanup() {
  if (cleaned) return;
  cleaned = true;
  for (const c of children) stopTree(c.pid);
}
process.on("exit", cleanup);
for (const sig of ["SIGINT", "SIGTERM", "SIGBREAK"]) process.on(sig, () => { cleanup(); process.exit(130); });

/* ---------- engine + UI ---------- */
const work = mkdtempSync(join(tmpdir(), "tool-tabs-"));
// Engine start is bounded and reports its own failure: a missing Python, an early exit (with a bounded stderr tail) or a
// handshake timeout all stop here with a clear message and a nonzero exit; the child is stopped by its tracked PID.
let handshake;
try {
  ({ handshake } = await startEngine({
    command: process.env.PYTHON || "py", args: ["-m", "snapstudio_api"], repoRoot: repo,
    cwd: join(repo, "backend"),
    env: { ...process.env, SNAPSTUDIO_DATA_DIR: join(work, "data"), PYTHONUNBUFFERED: "1" },
    timeoutMs: Number(process.env.SNAPSTUDIO_ENGINE_TIMEOUT_MS) || undefined,
    onSpawn: (c) => children.push(c),
  }));
} catch (e) {
  console.error(`Engine start failed: ${e?.message ?? e}`);
  cleanup();
  process.exit(2);
}
// Always this checkout's own UI: a dev server started here, from desktop/, on a port nothing else holds.
const uiPort = await new Promise((resolve, reject) => {
  const probe = net.createServer();
  probe.once("error", reject);
  probe.listen(0, "127.0.0.1", () => { const { port } = probe.address(); probe.close(() => resolve(port)); });
});
const UI = `http://localhost:${uiPort}`;
const ui = spawn("npx.cmd", ["vite", "--port", String(uiPort), "--strictPort", "--host", "localhost"], { cwd: join(repo, "desktop"), stdio: "ignore", shell: true });
children.push(ui);
let uiReady = false;
for (let i = 0; i < 80 && !uiReady; i++) { try { const r = await fetch(`${UI}/`, { signal: AbortSignal.timeout(2000) }); uiReady = r.ok; } catch { /* not yet */ } if (!uiReady) await sleep(500); }
if (!uiReady) { console.error(`This checkout's UI did not come up on ${UI}.`); process.exit(2); }
console.log(`UI: started a dev server from this checkout (${join(repo, "desktop")}) on ${UI}`);

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  - " + detail : ""}`); };

const browser = await chromium.launch({ channel: "msedge", headless: true });
console.log(`browser: Edge ${browser.version()}`);

// Fail closed: only this machine may be reached, and the engine may not be asked about a printer or for discovery.
const violations = [];
// The app's stylesheet imports the Inter web font from Google Fonts (desktop/src/index.css, line 1). That is existing
// behavior outside this change. Here the request is always aborted (nothing leaves the machine) and recorded in
// results.json as a known finding; a request to any other off-machine host still fails the run.
const KNOWN_FONT_HOSTS = ["fonts.googleapis.com", "fonts.gstatic.com"];
const blockedFontRequests = new Set();
const ignoredConsole = new Set();
const isLocal = (u) => /^(data:|blob:|about:)/.test(u) || ["localhost", "127.0.0.1"].includes(new URL(u).hostname);
async function guard(ctx) {
  // WebSockets (the vite dev server's own socket is local and allowed).
  await ctx.routeWebSocket((url) => !isLocal(url.href), async (ws) => { violations.push(`off-machine websocket ${new URL(ws.url()).hostname}`); await ws.close(); });
  await ctx.route((url) => !isLocal(url.href), async (route) => { const h = new URL(route.request().url()).hostname; if (KNOWN_FONT_HOSTS.includes(h)) blockedFontRequests.add(h); else violations.push(`off-machine ${h}`); await route.abort(); });
  await ctx.route(`http://127.0.0.1:${handshake.port}/**`, async (route) => {
    const url = new URL(route.request().url());
    let body = {};
    try { body = JSON.parse(route.request().postData() || "{}") ?? {}; } catch { /* not JSON */ }
    const namesOtherHost = (body.host !== undefined && String(body.host).trim() !== "127.0.0.1")
      || (Array.isArray(body.hosts) && body.hosts.some((h) => String(h).trim() !== "127.0.0.1"));
    if (url.pathname.startsWith("/printer/") || /discover/i.test(url.pathname) || namesOtherHost) {
      violations.push(`${route.request().method()} ${url.pathname}`); await route.abort(); return;
    }
    await route.continue();
  });
}
const errors = [];
async function newPage(theme, width, height = 900) {
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: theme, serviceWorkers: "block" });
  await ctx.addInitScript((t) => {
    localStorage.setItem("theme", t);
    // The default printer address is a name that would be looked up on the network; the loopback one is seeded first.
    localStorage.setItem("u1Host", "127.0.0.1");
  }, theme);
  await guard(ctx);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    if (/Failed to load resource|net::ERR|Invalid DOM property/.test(m.text())) ignoredConsole.add(m.text().slice(0, 200));
    else errors.push(m.text());
  });
  return { ctx, page };
}

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
const routes = [
  { path: "/compatibility", list: "Compatibility tools", first: { name: "Compatibility", heading: "Compatibility Doctor" }, second: { name: "Source Check", heading: "Source Check" } },
  { path: "/print-quality", list: "Print quality tools", first: { name: "Print Quality", heading: "Print Quality Doctor" }, second: { name: "First Layer", heading: "First Layer Doctor" } },
];

async function open(page, r) {
  await page.goto(`${UI}${r.path}?api=${handshake.port}:${handshake.token}`);
  await page.getByRole("tablist", { name: r.list }).waitFor({ timeout: 30000 });
  await page.getByRole("heading", { name: r.first.heading }).waitFor({ timeout: 30000 });
  // The start-up splash ("Powered by Studio Intelligence - starting...") fades out once the engine answers; wait for it so
  // the screenshots show the page and not the overlay.
  await page.getByText(/Powered by Studio Intelligence/).waitFor({ state: "detached", timeout: 30000 });
}
const tabsOf = (page, r) => page.getByRole("tablist", { name: r.list }).getByRole("tab");
/** What the keyboard is on, as the tab it is on (or null when it is not on a tab). */
const focusedTab = (page) => page.evaluate(() => {
  const a = document.activeElement;
  return a && a.getAttribute("role") === "tab" ? a.textContent.trim() : null;
});
const describeActive = (page) => page.evaluate(() => {
  const a = document.activeElement;
  return a ? (a.getAttribute("aria-label") || a.textContent || a.tagName).trim().replace(/\s+/g, " ").slice(0, 60) : null;
});
const headingShown = (page, text) => page.getByRole("heading", { name: text }).count().then((n) => n > 0);
const selectedTab = (page, r) => page.evaluate((list) => {
  const t = document.querySelector(`[role=tablist][aria-label="${list}"] [role=tab][aria-selected=true]`);
  return t ? t.textContent.trim() : null;
}, r.list);
const tabStop = (page, r) => page.evaluate((list) => {
  const t = [...document.querySelectorAll(`[role=tablist][aria-label="${list}"] [role=tab]`)].filter((b) => b.tabIndex === 0);
  return t.map((b) => b.textContent.trim());
}, r.list);

try {
  for (const r of routes) {
    const tag = r.path.slice(1);
    const { ctx, page } = await newPage("dark", 1100);
    await open(page, r);

    /* Tab lands on the selected tab only */
    check(`${tag}: the tab row is named "${r.list}"`, (await page.getByRole("tablist", { name: r.list }).count()) === 1);
    check(`${tag}: exactly one tab is in the Tab order and it is the selected one`,
      JSON.stringify(await tabStop(page, r)) === JSON.stringify([r.first.name]) && (await selectedTab(page, r)) === r.first.name,
      JSON.stringify(await tabStop(page, r)));
    await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
    const visited = [];
    for (let i = 0; i < 120; i++) {
      await page.keyboard.press("Tab");
      const t = await focusedTab(page);
      if (t) visited.push(t);
    }
    check(`${tag}: Tab, pressed 120 times through the page, lands on the selected tab and never on the other`,
      visited.length > 0 && visited.every((t) => t === r.first.name), `tabs reached: ${[...new Set(visited)].join(", ") || "none"}`);

    /* ArrowRight / ArrowLeft / Home / End move focus without switching the panel */
    await tabsOf(page, r).filter({ hasText: r.first.name }).focus();
    await page.keyboard.press("ArrowRight");
    check(`${tag}: ArrowRight moves focus to "${r.second.name}"`, (await focusedTab(page)) === r.second.name, String(await focusedTab(page)));
    check(`${tag}: ArrowRight did not switch the panel`,
      (await selectedTab(page, r)) === r.first.name && (await headingShown(page, r.first.heading)) && !(await headingShown(page, r.second.heading)));
    check(`${tag}: the tab stop moved with focus`, JSON.stringify(await tabStop(page, r)) === JSON.stringify([r.second.name]), JSON.stringify(await tabStop(page, r)));

    /* Shift+Tab from the first focusable descendant of the panel lands on the selected tab (the tab stop resets when focus leaves the row) */
    const firstInPanel = await page.evaluate((sel) => {
      const el = document.querySelector("[role=tabpanel]").querySelector(sel);
      if (!el) return null;
      el.focus();
      return (el.getAttribute("aria-label") || el.textContent || el.tagName).trim().replace(/\s+/g, " ").slice(0, 60);
    }, FOCUSABLE);
    check(`${tag}: the panel has a first focusable control`, !!firstInPanel, String(firstInPanel));
    await page.keyboard.press("Shift+Tab");
    check(`${tag}: after arrowing to "${r.second.name}" and leaving the row, the tab stop is back on the selected tab "${r.first.name}"`,
      JSON.stringify(await tabStop(page, r)) === JSON.stringify([r.first.name]), JSON.stringify(await tabStop(page, r)));
    check(`${tag}: Shift+Tab from the first focusable control in the panel ("${firstInPanel}") lands on the selected tab ("${r.first.name}"), not the one that was arrowed to`,
      (await focusedTab(page)) === r.first.name, String(await describeActive(page)));

    await page.keyboard.press("ArrowLeft");      // wraps from the first tab to the last
    check(`${tag}: ArrowLeft wraps from the first tab to the last`, (await focusedTab(page)) === r.second.name, String(await focusedTab(page)));
    await page.keyboard.press("ArrowRight");     // wraps from the last tab to the first
    check(`${tag}: ArrowRight wraps from the last tab to the first`, (await focusedTab(page)) === r.first.name, String(await focusedTab(page)));
    await page.keyboard.press("Home");
    check(`${tag}: Home moves focus to the first tab`, (await focusedTab(page)) === r.first.name, String(await focusedTab(page)));
    await page.keyboard.press("End");
    check(`${tag}: End moves focus to the last tab`, (await focusedTab(page)) === r.second.name, String(await focusedTab(page)));
    check(`${tag}: Home, End and the arrow keys never switched the panel`,
      (await selectedTab(page, r)) === r.first.name && (await headingShown(page, r.first.heading)) && !(await headingShown(page, r.second.heading)));

    /* Enter switches and the panel heading appears */
    await page.keyboard.press("Enter");
    await page.getByRole("heading", { name: r.second.heading }).waitFor({ timeout: 30000 });
    check(`${tag}: Enter on "${r.second.name}" switches the panel and its heading "${r.second.heading}" appears`,
      (await selectedTab(page, r)) === r.second.name && !(await headingShown(page, r.first.heading)));
    check(`${tag}: focus stays on the tab after Enter`, (await focusedTab(page)) === r.second.name, String(await describeActive(page)));
    check(`${tag}: the panel is labeled by the selected tab`, await page.evaluate(() => {
      const p = document.querySelector("[role=tabpanel]");
      const t = document.getElementById(p.getAttribute("aria-labelledby"));
      return !!t && t.getAttribute("aria-selected") === "true" && t.getAttribute("aria-controls") === p.id;
    }));

    /* Space switches back */
    await page.keyboard.press("Home");
    await page.keyboard.press("Space");
    await page.getByRole("heading", { name: r.first.heading }).waitFor({ timeout: 30000 });
    check(`${tag}: Space on "${r.first.name}" switches back and its heading "${r.first.heading}" appears`,
      (await selectedTab(page, r)) === r.first.name && !(await headingShown(page, r.second.heading)));
    await ctx.close();
  }

  /* focus ring, dark and light, keyboard-focused tab */
  for (const theme of ["dark", "light"]) {
    const { ctx, page } = await newPage(theme, 1100, 760);
    await open(page, routes[0]);
    await page.evaluate(() => document.activeElement?.blur());
    for (let i = 0; i < 120 && !(await focusedTab(page)); i++) await page.keyboard.press("Tab");
    const ring = await page.evaluate(() => {
      const a = document.activeElement;
      const cs = getComputedStyle(a);
      return { box: cs.boxShadow, outline: cs.outlineStyle, focusVisible: a.matches(":focus-visible") };
    });
    check(`focus ring (${theme}): the keyboard-focused tab shows a visible ring`,
      ring.focusVisible && ring.box !== "none" && /rgb/.test(ring.box), JSON.stringify(ring));
    const box = await page.getByRole("tablist", { name: routes[0].list }).boundingBox();
    await page.screenshot({ path: join(out, `01-focus-ring-${theme}.png`), clip: { x: Math.max(0, box.x - 24), y: Math.max(0, box.y - 24), width: Math.min(560, 1100 - box.x), height: box.height + 48 } });
    await page.screenshot({ path: join(out, `02-compatibility-${theme}.png`) });
    await ctx.close();
  }

  /* 600 px viewport */
  for (const r of routes) {
    const { ctx, page } = await newPage("dark", 600, 800);
    await open(page, r);
    const m = await page.evaluate((list) => {
      const de = document.documentElement;
      const tabs = [...document.querySelectorAll(`[role=tablist][aria-label="${list}"] [role=tab]`)];
      const bar = document.querySelector(`[role=tablist][aria-label="${list}"]`).getBoundingClientRect();
      return {
        pageOverflow: de.scrollWidth - de.clientWidth, bodyOverflow: document.body.scrollWidth - de.clientWidth,
        truncated: tabs.filter((t) => t.scrollWidth > t.clientWidth).map((t) => t.textContent.trim()),
        outside: tabs.filter((t) => { const b = t.getBoundingClientRect(); return b.left < 0 || b.right > de.clientWidth; }).map((t) => t.textContent.trim()),
        heights: tabs.map((t) => Math.round(t.getBoundingClientRect().height)), barRight: Math.round(bar.right), width: de.clientWidth,
      };
    }, r.list);
    check(`${r.path.slice(1)} at 600 px: no horizontal page scroll`, m.pageOverflow <= 0 && m.bodyOverflow <= 0, JSON.stringify({ page: m.pageOverflow, body: m.bodyOverflow }));
    check(`${r.path.slice(1)} at 600 px: tab labels are not truncated and sit inside the viewport`, m.truncated.length === 0 && m.outside.length === 0, JSON.stringify(m));
    const names = await tabsOf(page, r).allInnerTexts();
    check(`${r.path.slice(1)} at 600 px: both labels are present in full`, JSON.stringify(names.map((n) => n.trim())) === JSON.stringify([r.first.name, r.second.name]), names.join(" | "));
    await page.screenshot({ path: join(out, `03-${r.path.slice(1)}-600px.png`) });
    await ctx.close();
  }

  check("no request reached another host, a printer, or discovery", violations.length === 0, violations.join(" | "));
  check("no unexpected console errors", errors.length === 0, errors.slice(0, 2).join(" | "));
} catch (e) {
  check("the run completed without a harness error", false, String(e?.message ?? e));
} finally {
  await browser.close();
  cleanup();
}
const git = (args) => spawnSync("git", args, { cwd: repo, encoding: "utf8" }).stdout;
const baseCommit = git(["rev-parse", "HEAD"]).trim();
const worktreeDirty = git(["status", "--porcelain"]).trim() !== "";
// Hash of the uncommitted change: `git diff HEAD` plus every untracked file (path and bytes, sorted), except this run's own output.
const hash = createHash("sha256").update(git(["diff", "HEAD"]));
for (const f of git(["ls-files", "--others", "--exclude-standard"]).split(String.fromCharCode(10)).filter((x) => x && !x.startsWith("docs/testing/tool-tabs/")).sort()) {
  hash.update(String.fromCharCode(0) + f + String.fromCharCode(0)).update(readFileSync(join(repo, f)));
}
writeFileSync(join(out, "results.json"), JSON.stringify({ browser: "Microsoft Edge (Chromium), headless", uiStartedByThisRun: true, uiUrl: UI,
  baseCommit, worktreeDirty, diffHash: hash.digest("hex"),
  note: "Run on the uncommitted change on top of baseCommit; diffHash covers git diff HEAD plus untracked files (excluding this folder).",
  backendNetworkNotObserved: true,
  knownBlockedFontHosts: [...blockedFontRequests], ignoredConsoleMessages: [...ignoredConsole], results }, null, 2));
const failed = results.filter((r) => !r.ok).length;
console.log(`${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
