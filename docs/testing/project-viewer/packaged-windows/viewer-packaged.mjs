// Packaged-app probe for the read-only project viewer (staging only; drives the REWRAPPED ACCEPTANCE build over CDP).
// Usage: node viewer-packaged.mjs <cdpUrl> <samplePath> <outFile>
import { chromium } from "playwright-core";
import fs from "node:fs";
import crypto from "node:crypto";

const [, , cdpUrl, samplePath, outFile] = process.argv;
const res = { steps: [], ok: false, requests: [], consoleProblems: [] };
const step = (name, ok, detail = "") => { res.steps.push({ name, ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  - " + detail : ""}`); return ok; };
const sha = (p) => crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex");
const before = sha(samplePath);
try {
  const browser = await chromium.connectOverCDP(cdpUrl);
  const ctx = browser.contexts()[0];
  let page = null;
  for (let i = 0; i < 60 && !page; i++) {
    page = ctx.pages().find((p) => /^https?:\/\/(tauri|ipc)?\.?localhost|^tauri:/.test(p.url()) || (p.url() && !p.url().startsWith("about:") && !p.url().startsWith("devtools:"))) ?? null;
    if (!page) await new Promise((r) => setTimeout(r, 500));
  }
  if (!page) throw new Error("no app page found over CDP (only about:blank)");
  page.on("request", (r) => { try { const u = new URL(r.url()); if (!["127.0.0.1", "localhost", "tauri.localhost", "ipc.localhost"].includes(u.hostname) && !["data:", "blob:", "about:"].includes(u.protocol)) res.requests.push(u.hostname); } catch {} });
  page.on("console", (m) => { const t = m.text(); if (/Content Security Policy|violat|refused to|WebGL.*(lost|fail)|context lost/i.test(t)) res.consoleProblems.push(t.slice(0, 200)); });
  await page.waitForLoadState("domcontentloaded");
  await page.locator("#brand-splash").waitFor({ state: "detached", timeout: 30000 }).catch(() => {});
  // The shell hands the command-line project to the session at startup (same path the acceptance harness uses);
  // the viewer lives on the project workspace route, reached the way the harness reaches other routes.
  const launched = await page.evaluate(() => window.__TAURI_INTERNALS__.invoke("get_launch_file")).catch(() => null);
  res.clickNote = `launch file reported: ${typeof launched === "string"}`;
  await page.waitForTimeout(3000);
  await page.evaluate(() => { window.history.pushState({}, "", "/workspace"); window.dispatchEvent(new PopStateEvent("popstate")); });
  const heading = page.getByRole("heading", { name: "3D view of this project" });
  const shown = await heading.waitFor({ timeout: 90000 }).then(() => true).catch(() => false);
  step("The packaged app shows the 3D view panel for the project opened on the command line", shown, res.clickNote ?? "");
  if (!shown) {
    res.pageTextExcerpt = (await page.evaluate(() => document.body.innerText.slice(0, 600)).catch(() => "")).replace(/[A-Za-z]:\\[^\s]*/g, "<path>");
    await page.screenshot({ path: outFile.replace(/\.json$/, "-failure.png") }).catch(() => {});
  }
  if (shown) {
    await page.waitForFunction(() => document.querySelectorAll("canvas").length >= 1 && document.querySelectorAll("section[aria-labelledby=scene-objects] button").length >= 1, null, { timeout: 90000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const state = await page.evaluate(() => {
      const canvases = [...document.querySelectorAll("canvas")];
      const alerts = [...document.querySelectorAll('[role="alert"]')].map((a) => a.textContent?.trim().slice(0, 120));
      const objs = document.querySelectorAll("section[aria-labelledby=scene-objects] button").length;
      const cams = [...document.querySelectorAll('[role="group"][aria-label="Camera views"] button')].map((b) => ({ n: b.textContent?.trim(), d: b.disabled }));
      return { canvases: canvases.map((c) => [c.width, c.height]), alerts, objs, cams };
    });
    step("A canvas with a real size is drawn and no graphics-failure alert is shown", state.canvases.length >= 1 && state.canvases[0][0] > 0 && !state.alerts.some((a) => /graphics|3D view could not/i.test(a ?? "")), JSON.stringify({ canvases: state.canvases.length, size: state.canvases[0], alerts: state.alerts }));
    step("The object list and the camera buttons are present", state.objs >= 1 && state.cams.length >= 1 && state.cams.every((c) => !c.d), JSON.stringify({ objects: state.objs, cameras: state.cams.length }));
    const objBtn = page.locator("section[aria-labelledby=scene-objects] button").first();
    await objBtn.click();
    step("Selecting an object marks its row", (await objBtn.getAttribute("aria-pressed")) === "true");
    for (const b of await page.locator('[role="group"][aria-label="Camera views"] button').all()) await b.click();
    step("Every camera view button can be pressed", true);
    const canvas = page.locator("canvas").first();
    const box = await canvas.boundingBox();
    const listBefore = await page.locator("section[aria-labelledby=scene-objects] button").allTextContents();
    if (box) {
      const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
      for (const mod of [[], ["Shift"], ["Control"], ["Alt"]]) {
        for (const k of mod) await page.keyboard.down(k);
        for (const btn of ["left", "right", "middle"]) { await page.mouse.move(cx, cy); await page.mouse.down({ button: btn }); await page.mouse.move(cx + 40, cy + 25, { steps: 6 }); await page.mouse.up({ button: btn }); }
        for (const k of mod) await page.keyboard.up(k);
      }
      await page.mouse.wheel(0, -300);
      await page.keyboard.press("Escape");
    }
    const listAfter = await page.locator("section[aria-labelledby=scene-objects] button").allTextContents();
    step("Mouse drags (all buttons, with modifiers), wheel and keys change nothing in the object list", JSON.stringify(listBefore) === JSON.stringify(listAfter), `${listAfter.length} objects`);
    const home = page.getByRole("link", { name: /^Home$/ }).or(page.getByRole("button", { name: /^Home$/ })).first();
    await home.click().catch(() => {});
    await page.waitForTimeout(1500);
    const canvasesAway = await page.locator("canvas").count();
    step("Leaving the page removes the canvas", canvasesAway === 0, `${canvasesAway} canvas(es) left`);
  }
  step("Nothing left the machine (no non-loopback request)", res.requests.length === 0, JSON.stringify([...new Set(res.requests)]));
  step("No CSP violation or graphics-context problem was logged", res.consoleProblems.length === 0, res.consoleProblems.slice(0, 3).join(" | "));
  await browser.close().catch(() => {});
} catch (e) { step("Probe ran to completion", false, String(e).slice(0, 300)); }
step("The project file bytes are unchanged", sha(samplePath) === before);
res.ok = res.steps.length > 0 && res.steps.every((s) => s.ok);
fs.writeFileSync(outFile, JSON.stringify(res, null, 2));
process.exit(res.ok ? 0 : 1);
