#!/usr/bin/env node
// Captures the few screenshots that only the INSTALLED Snapmaker Studio can show (for example the "Open in Snapmaker
// Orca" button, which needs the desktop shell to look for Orca). It attaches to an installed copy of Studio that
// tools/capture-installed.ps1 started in an isolated harness, over the WebView2 remote-debugging port.
//
//   node tools/capture-installed.mjs <cdpUrl>
//
// Safety: this script never presses "Open in Snapmaker Orca", never connects to a printer and never writes outside
// the harness folders. It only reads positions and takes screenshots.
import { createRequire } from "node:module";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const require = createRequire(import.meta.url);
let playwright;
try { playwright = require("playwright-core"); } catch { playwright = createRequire(join(root, "../../tools/acceptance/package.json"))("playwright-core"); }
const { SHOTS } = await import("./spec.mjs");
const cdp = process.argv[2];
if (!cdp) throw new Error("usage: node tools/capture-installed.mjs <cdpUrl>");

const browser = await playwright.chromium.connectOverCDP(cdp);
const page = browser.contexts()[0].pages().find((p) => p.url().startsWith("http://tauri.localhost"));
if (!page) throw new Error("the installed app window was not found over CDP");
const geometryPath = join(root, "content/geometry.json");
const geometry = existsSync(geometryPath) ? JSON.parse(readFileSync(geometryPath, "utf8")) : {};
const imgDir = join(root, "public/assets/img");
mkdirSync(imgDir, { recursive: true });
let failures = 0;

for (const shot of SHOTS.filter((s) => s.installed)) {
  try {
    await page.setViewportSize(shot.size || { width: 1230, height: 960 });
    await page.evaluate(() => localStorage.setItem("theme", "dark"));
    await page.evaluate((r) => { window.history.pushState({}, "", r); window.dispatchEvent(new PopStateEvent("popstate")); }, shot.route || "/");
    await page.waitForTimeout(3000);
    await shot.setup?.(page);
    await page.waitForTimeout(shot.settle ?? 600);
    await page.evaluate(() => {
      const path = /[A-Za-z]:[\\/][^\s"')<]*/g;
      const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const nodes = [];
      while (w.nextNode()) nodes.push(w.currentNode);
      for (const n of nodes) { path.lastIndex = 0; if (path.test(n.nodeValue)) { path.lastIndex = 0; n.nodeValue = n.nodeValue.replace(path, "<folder>"); } }
    });
    if (shot.scroll) { await shot.scroll(page).first().evaluate((el) => el.scrollIntoView({ block: "start" })); await page.waitForTimeout(300); }
    const vp = page.viewportSize();
    const hot = {};
    for (const [key, make] of Object.entries(shot.targets || {})) {
      const loc = make(page).first();
      try { await loc.waitFor({ state: "visible", timeout: 8000 }); } catch { throw new Error(`target "${key}" was not found on the page`); }
      const b = await loc.boundingBox();
      const x0 = Math.max(0, b.x), y0 = Math.max(0, b.y), x1 = Math.min(vp.width, b.x + b.width), y1 = Math.min(vp.height, b.y + b.height);
      if (x1 - x0 < 4 || y1 - y0 < 4 || b.y + 6 > vp.height) throw new Error(`hotspot "${key}" is not inside the captured area`);
      const pct = (v, total) => Math.round((v / total) * 10000) / 100;
      hot[key] = { x: pct(x0, vp.width), y: pct(y0, vp.height), w: pct(x1 - x0, vp.width), h: pct(y1 - y0, vp.height) };
    }
    await page.screenshot({ path: join(imgDir, shot.file) });
    geometry[shot.id] = { width: vp.width, height: vp.height, hotspots: hot };
    console.log(`ok   ${shot.id}  (${Object.keys(hot).length} hotspots, installed app)`);
  } catch (e) {
    failures++;
    console.log(`FAIL ${shot.id}: ${String(e.message).split("\n")[0]}`);
  }
}
writeFileSync(geometryPath, JSON.stringify(geometry, null, 1) + "\n");
await browser.close();
process.exit(failures ? 1 : 0);
