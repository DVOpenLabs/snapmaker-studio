#!/usr/bin/env node
// End-to-end checks for the built guide, in a real browser, at desktop and phone widths in both themes.
//   node tools/e2e.mjs                       serves public/ itself and runs everything
//   node tools/e2e.mjs --shots <folder>      also saves screenshots of the finished guide
// Exit code 0 only if every check passed. Needs Microsoft Edge or Chrome installed (channel "msedge" / "chrome").
import { createRequire } from "node:module";
import { createServer } from "node:http";
import { readFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, extname, join, normalize, sep } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const pub = join(root, "public");
const require = createRequire(import.meta.url);
let playwright;
try { playwright = require("playwright-core"); } catch { playwright = createRequire(join(root, "../../tools/acceptance/package.json"))("playwright-core"); }
const { chromium } = playwright;
const args = process.argv.slice(2);
const shotsDir = args.includes("--shots") ? args[args.indexOf("--shots") + 1] : null;
const liveUrl = args.includes("--url") ? args[args.indexOf("--url") + 1].replace(/\/?$/, "/") : null; // test a deployed copy instead of public/
if (shotsDir) mkdirSync(shotsDir, { recursive: true });

const CSP = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
const types = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };
const server = createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (p.endsWith("/")) p += "index.html";
  const f = normalize(join(pub, p));
  if (!f.startsWith(pub + sep) || !existsSync(f)) { res.writeHead(404).end(); return; }
  res.writeHead(200, { "content-type": types[extname(f)] || "application/octet-stream", "content-security-policy": CSP }).end(readFileSync(f));
});
if (!liveUrl) await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = liveUrl ?? `http://127.0.0.1:${server.address().port}/`;

const content = JSON.parse(readFileSync(join(root, "content/lessons.json"), "utf8"));
const lessons = content.lessons;
const results = [];
function check(name, ok, detail = "") { results.push({ name, ok: !!ok }); if (!ok) console.log(`FAIL  ${name}${detail ? "  — " + detail : ""}`); }

const center = (loc) => loc.evaluate((e) => { const r = e.getBoundingClientRect(); window.scrollBy(0, r.top + r.height / 2 - window.innerHeight * 0.55); });

async function launch() {
  for (const channel of ["msedge", "chrome"]) { try { return await chromium.launch({ channel, headless: true }); } catch { /* try next */ } }
  throw new Error("No Edge or Chrome found for the browser checks.");
}
const browser = await launch();

async function run(label, viewport, theme) {
  const ctx = await browser.newContext({ viewport, colorScheme: theme, deviceScaleFactor: 1 });
  await ctx.addInitScript((t) => { try { if (localStorage.getItem("sg.theme") === null && !sessionStorage.getItem("seeded")) { localStorage.setItem("sg.theme", t); sessionStorage.setItem("seeded", "1"); } } catch { /* ignore */ } }, theme);
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  const mobile = viewport.width < 700;
  const T = (n) => `${label}: ${n}`;
  const active = () => page.evaluate(() => document.querySelector(".lesson.is-active")?.id ?? null);
  const hash = () => page.evaluate(() => location.hash);

  /* load + theme */
  await page.goto(base, { waitUntil: "networkidle" });
  check(T("theme applied"), (await page.evaluate(() => document.documentElement.dataset.theme)) === theme);
  check(T("exactly one lesson is shown"), (await page.locator(".lesson.is-active").count()) === 1);
  check(T("progress reads Lesson 1 of 12"), /Lesson 1 of 12/.test(await page.locator("#tour-count").innerText()));
  check(T("progress is labelled as tour position"), /Tour position/.test(await page.locator("#tour-sub").innerText()));
  if (shotsDir) await page.screenshot({ path: join(shotsDir, `welcome-${label}.png`) });

  /* every lesson has a stable deep link */
  for (const [i, l] of lessons.entries()) {
    await page.goto(`${base}#${l.id}`, { waitUntil: "load" });
    await page.waitForTimeout(80);
    check(T(`deep link #${l.id}`), (await active()) === l.id);
    check(T(`lesson ${i + 1} count text`), new RegExp(`Lesson ${i + 1} of ${lessons.length}`).test(await page.locator("#tour-count").innerText()));
    check(T(`lesson ${i + 1} sidebar current`), (await page.locator(`.toc a[aria-current="page"]`).getAttribute("data-lesson")) === l.id);
    check(T(`lesson ${i + 1} has no horizontal overflow`), await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    const broken = await page.evaluate(async (id) => {
      const bad = [];
      for (const im of document.querySelectorAll(`#${id} img`)) {
        const r = await fetch(im.getAttribute("src"));
        if (!r.ok || !(r.headers.get("content-type") || "").startsWith("image/")) bad.push(im.getAttribute("src"));
      }
      return bad;
    }, l.id);
    check(T(`lesson ${i + 1} images load`), broken.length === 0, broken.join(", "));
  }

  /* next / back / browser history */
  await page.goto(`${base}#${lessons[0].id}`);
  await page.waitForTimeout(80);
  check(T("Back is hidden on lesson 1"), await page.locator(`#${lessons[0].id} .js-prev`).count() === 0);
  await page.locator(`#${lessons[0].id} .js-next`).click();
  await page.waitForTimeout(150);
  check(T("Next goes to lesson 2"), (await active()) === lessons[1].id && (await hash()) === `#${lessons[1].id}`);
  check(T("focus moves to the lesson heading"), await page.evaluate(() => document.activeElement?.matches("h2.title") ?? false));
  await page.locator(`#${lessons[1].id} .js-prev`).click();
  await page.waitForTimeout(150);
  check(T("Back goes to lesson 1"), (await active()) === lessons[0].id);
  await page.goBack(); await page.waitForTimeout(150);
  check(T("browser Back returns to lesson 2"), (await active()) === lessons[1].id);
  await page.goForward(); await page.waitForTimeout(150);
  check(T("browser Forward returns to lesson 1"), (await active()) === lessons[0].id);
  await page.goto(`${base}#${lessons[lessons.length - 1].id}`); await page.waitForTimeout(80);
  check(T("Next is hidden on the last lesson"), await page.locator(`#${lessons[lessons.length - 1].id} .js-next`).count() === 0);

  /* saved position and Start again */
  await page.goto(`${base}#${lessons[3].id}`); await page.waitForTimeout(80);
  await page.goto(base); await page.waitForTimeout(150);
  check(T("saved tour position restored"), (await active()) === lessons[3].id);
  check(T("start button offers Continue"), /Continue — lesson 4/.test(await page.locator("#start-label").innerText()));
  await page.locator("#start-again").click(); await page.waitForTimeout(200);
  check(T("Start again returns to lesson 1"), (await active()) === lessons[0].id);
  await page.goto(base); await page.waitForTimeout(100);
  check(T("Start again cleared the saved position"), (await active()) === lessons[0].id);

  /* theme toggle persists */
  const other = theme === "dark" ? "light" : "dark";
  if (mobile) { /* the toggle is in the header on every width */ }
  await page.locator("#theme-btn").click(); await page.waitForTimeout(100);
  check(T("theme toggle flips the theme"), (await page.evaluate(() => document.documentElement.dataset.theme)) === other);
  await page.reload({ waitUntil: "load" });
  check(T("theme choice persists"), (await page.evaluate(() => document.documentElement.dataset.theme)) === other);
  await page.locator("#theme-btn").click(); await page.waitForTimeout(100);

  /* mobile lesson menu */
  if (mobile) {
    await page.goto(`${base}#${lessons[0].id}`); await page.waitForTimeout(100);
    check(T("lesson menu starts closed"), !(await page.locator("#toc").isVisible()));
    await page.locator("#menu-btn").click();
    check(T("lesson menu opens"), await page.locator("#toc").isVisible() && (await page.locator("#menu-btn").getAttribute("aria-expanded")) === "true");
    await page.locator(`#toc a[data-lesson="${lessons[2].id}"]`).click(); await page.waitForTimeout(200);
    check(T("choosing a lesson closes the menu and opens it"), (await active()) === lessons[2].id && !(await page.locator("#toc").isVisible()));
  }

  /* screenshot viewer: open, focus, Escape, focus restored */
  await page.goto(`${base}#${lessons[0].id}`); await page.waitForTimeout(100);
  const opener = page.locator(`#${lessons[0].id} .shot-open`).first();
  await opener.focus();
  await opener.press("Enter"); await page.waitForTimeout(200);
  check(T("viewer opens"), await page.locator("dialog.viewer[open]").count() === 1);
  check(T("viewer moves focus inside"), await page.evaluate(() => document.querySelector("dialog.viewer")?.contains(document.activeElement) ?? false));
  check(T("viewer has hotspots"), (await page.locator("dialog.viewer .hs").count()) > 0);
  if (shotsDir) await page.screenshot({ path: join(shotsDir, `viewer-${label}.png`) });
  await page.keyboard.press("Escape"); await page.waitForTimeout(200);
  check(T("Escape closes the viewer"), await page.locator("dialog.viewer[open]").count() === 0);
  check(T("focus returns to the screenshot button"), await opener.evaluate((el) => el === document.activeElement));

  /* a small thumbnail has no crowded circles on the page, but its enlarged view does */
  await page.goto(`${base}#more-tools`); await page.waitForTimeout(80);
  check(T("more-tools: thumbnails carry no crowded circles"), (await page.locator("#more-tools figure.compact .hs").count()) === 0);
  await page.locator("#more-tools figure.compact .shot-open").first().click(); await page.waitForTimeout(200);
  check(T("more-tools: the enlarged view has the circles"), (await page.locator("dialog.viewer[open] .hs").count()) > 0);
  await page.keyboard.press("Escape"); await page.waitForTimeout(100);

  /* hotspots on the first figure of every lesson that has one */
  for (const l of lessons) {
    const fig = page.locator(`#${l.id} figure.shot:not(.compact)`).first();
    if (!(await fig.count())) continue;
    await page.goto(`${base}#${l.id}`); await page.waitForTimeout(60);
    const spots = fig.locator(".hs");
    const n = await spots.count();
    check(T(`${l.id}: first figure has hotspots`), n > 0);
    if (!n) continue;
    await center(spots.nth(0));
    await spots.nth(0).click();
    check(T(`${l.id}: hotspot opens its explanation`), (await spots.nth(0).getAttribute("aria-pressed")) === "true" && /1\./.test(await fig.locator(".hs-callout").innerText()));
    const ok = await fig.evaluate((f) => Array.from(f.querySelectorAll(".hs")).every((b) => { const x = parseFloat(b.style.left), y = parseFloat(b.style.top); return x >= 0 && x <= 100 && y >= 0 && y <= 100; }));
    check(T(`${l.id}: hotspots lie inside the picture`), ok);
    const textItems = await fig.locator(".hs-text li").count();
    check(T(`${l.id}: every hotspot has ordinary text too`), textItems === n, `${textItems} text items for ${n} hotspots`);
  }

  /* walkthroughs */
  for (const l of lessons) {
    if (!l.demo) continue;
    await page.goto(`${base}#${l.id}`); await page.waitForTimeout(80);
    const demo = page.locator(`#${l.id}-demo`);
    await center(demo);
    const steps = l.demo.steps.length;
    let good = true;
    for (let s = 0; s < steps; s++) {
      const nxt = demo.locator(".hs.next");
      if ((await nxt.count()) !== 1) { good = false; break; }
      await center(nxt);
      await nxt.click();
      if (!/what you would see/i.test(await demo.locator(".demo-say").innerText())) { good = false; break; }
      if (s < steps - 1) { await demo.locator(".demo-next").click(); await page.waitForTimeout(40); }
    }
    check(T(`${l.id}: walkthrough completes in ${steps} steps`), good);
    check(T(`${l.id}: walkthrough ends cleanly`), /end of this example/i.test(await demo.locator(".demo-say").innerText()));
    check(T(`${l.id}: walkthrough says it touches nothing`), /never connects to a printer/.test(await demo.locator(".demo-safe").innerText()));
    await center(demo.locator(".demo-reset"));
    await demo.locator(".demo-reset").click();
    check(T(`${l.id}: walkthrough resets`), (await demo.locator(".hs.next").count()) === 1 && /step 1 of/i.test(await demo.locator(".demo-say").innerText()));
    // a wrong circle is explained, not ignored
    const idle = demo.locator(".hs.idle").first();
    if (await idle.count()) { await center(idle); await idle.click(); check(T(`${l.id}: a wrong circle is explained`), /not this one/i.test(await demo.locator(".demo-say").innerText())); await demo.locator(".demo-reset").click(); }
  }
  if (shotsDir) {
    await page.evaluate(() => document.querySelectorAll("img[loading=lazy]").forEach((i) => { i.loading = "eager"; }));
    await page.goto(`${base}#fix-and-prepare`); await page.waitForTimeout(150);
    await page.locator("#fix-and-prepare figure.shot").first().scrollIntoViewIfNeeded();
    await page.evaluate(() => { document.querySelector("#fix-and-prepare figure.shot").scrollIntoView({ block: "start" }); window.scrollBy(0, -80); });
    await page.screenshot({ path: join(shotsDir, `figure-${label}.png`) });
    const demo = page.locator("#fix-and-prepare-demo");
    await demo.scrollIntoViewIfNeeded();
    await demo.locator(".hs.next").click();
    await page.evaluate(() => { document.querySelector("#fix-and-prepare-demo").scrollIntoView({ block: "start" }); window.scrollBy(0, -80); });
    await page.screenshot({ path: join(shotsDir, `walkthrough-${label}.png`) });
    await page.goto(`${base}#more-tools`); await page.waitForTimeout(200);
    await page.evaluate(() => { document.querySelectorAll("img[loading=lazy]").forEach((i) => { i.loading = "eager"; }); document.querySelector("#more-tools .branches").scrollIntoView({ block: "start" }); window.scrollBy(0, -100); });
    await page.waitForTimeout(600);
    await page.screenshot({ path: join(shotsDir, `lesson-more-tools-${label}.png`) });
    await page.goto(`${base}#troubleshooting`); await page.waitForTimeout(200);
    await page.screenshot({ path: join(shotsDir, `lesson-troubleshooting-${label}.png`) });
  }
  check(T("no console errors"), errors.length === 0, errors.join(" | "));
  await ctx.close();
}

await run("desktop-dark", { width: 1280, height: 900 }, "dark");
await run("desktop-light", { width: 1280, height: 900 }, "light");
await run("phone-dark", { width: 390, height: 844 }, "dark");
await run("phone-light", { width: 390, height: 844 }, "light");

/* without JavaScript: readable, complete, every hotspot as text */
{
  const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 }, javaScriptEnabled: false });
  const page = await ctx.newPage();
  await page.goto(base, { waitUntil: "load" });
  const shown = await page.evaluate(() => Array.from(document.querySelectorAll(".lesson")).filter((l) => getComputedStyle(l).display !== "none").length);
  check("no-JS: all lessons are readable", shown === lessons.length, `${shown} shown`);
  check("no-JS: explains that examples need JavaScript", await page.locator(".nojs-note").isVisible());
  check("no-JS: hotspot notes are plain text", (await page.locator(".hs-text li").count()) > 50);
  check("no-JS: walkthroughs fall back to numbered text", (await page.locator(".demo-static li").count()) > 10);
  check("no-JS: JavaScript-only controls are hidden", !(await page.locator("#theme-btn").isVisible()));
  if (shotsDir) await page.screenshot({ path: join(shotsDir, "no-javascript.png") });
  await ctx.close();
}

await browser.close();
server.close();
const failed = results.filter((r) => !r.ok);
console.log(`${results.length - failed.length}/${results.length} browser checks passed`);
process.exit(failed.length ? 1 : 0);
