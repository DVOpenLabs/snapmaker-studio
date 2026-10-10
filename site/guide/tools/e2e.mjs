#!/usr/bin/env node
// End-to-end checks for the built guide, in a real browser, at desktop and phone widths in both themes.
//   node tools/e2e.mjs                       serves public/ itself (with a strict Content-Security-Policy) and runs everything
//   node tools/e2e.mjs --shots <folder>      also saves screenshots of the finished guide
//   node tools/e2e.mjs --url <deployed url>  tests a deployed copy instead of public/
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
const liveUrl = args.includes("--url") ? args[args.indexOf("--url") + 1].replace(/\/?$/, "/") : null;
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

const html = readFileSync(join(pub, "index.html"), "utf8");
const DATA = JSON.parse(/<script type="application\/json" id="guide-data">([\s\S]*?)<\/script>/.exec(html)[1]);
const pageIds = [...html.matchAll(/<article class="page [^"]*" id="([^"]+)" data-page=/g)].map((m) => m[1]);
const pageTypes = Object.fromEntries([...html.matchAll(/<article class="page [^"]*" id="([^"]+)" data-page="[^"]+" data-type="([^"]+)"/g)].map((m) => [m[1], m[2]]));
const results = [];
function check(name, ok, detail = "") { results.push({ name, ok: !!ok }); if (!ok) console.log(`FAIL  ${name}${detail ? "  — " + detail : ""}`); }

async function launch() {
  for (const channel of ["msedge", "chrome"]) { try { return await chromium.launch({ channel, headless: true }); } catch { /* try next */ } }
  throw new Error("No Edge or Chrome found for the browser checks.");
}
const browser = await launch();

async function run(label, viewport, theme) {
  const ctx = await browser.newContext({ viewport, colorScheme: theme, deviceScaleFactor: 1 });
  await ctx.addInitScript((t) => { try { if (localStorage.getItem("sg.theme") === null && !sessionStorage.getItem("seeded")) { localStorage.setItem("sg.theme", t); sessionStorage.setItem("seeded", "1"); } } catch { /* ignore */ } }, theme);
  await ctx.addInitScript(() => { const s = new CSSStyleSheet(); s.replaceSync("html{scroll-behavior:auto!important}"); document.addEventListener("DOMContentLoaded", () => { document.adoptedStyleSheets = [...document.adoptedStyleSheets, s]; }); });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  const mobile = viewport.width < 700;
  const T = (n) => `${label}: ${n}`;
  const active = () => page.evaluate(() => document.querySelector("article.page.is-active")?.dataset.page ?? null);
  const nActive = () => page.locator("article.page.is-active").count();
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  const go = async (hash) => { await page.goto(`${base}${hash}`, { waitUntil: "load" }); await page.waitForTimeout(60); };
  const snap = async (name) => { if (shotsDir) { await page.waitForTimeout(250); await page.screenshot({ path: join(shotsDir, `${name}-${label}.png`) }); } };
  const eager = () => page.evaluate(() => document.querySelectorAll("img[loading=lazy]").forEach((i) => { i.loading = "eager"; }));

  /* ---------- home ---------- */
  await page.goto(base, { waitUntil: "networkidle" });
  check(T("theme applied"), (await page.evaluate(() => document.documentElement.dataset.theme)) === theme);
  check(T("home is the only page shown"), (await active()) === "home" && (await nActive()) === 1);
  check(T("exactly one h1"), (await page.locator("h1").count()) === 1);
  check(T("home offers three ways in"), (await page.locator("#home .door").count()) === 3);
  check(T("home shows the workflow map with seven stages"), (await page.locator("#home .wf-node").count()) === 7);
  check(T("home map has Studio, Orca and printer lanes"), (await page.locator("#home .wf-lane").count()) === 3);
  check(T("home has no horizontal overflow"), !(await overflow()));
  check(T("home states what the guide does not show"), /No screenshot of a connected printer/.test(await page.locator("#not-shown").innerText()));
  await snap("home");
  check(T("home heading is concrete"), (await page.locator("#home-h").innerText()) === "Check your project before you slice");
  check(T("home description is concrete"), /Check a downloaded model, prepare a U1 copy, and understand what to review before printing./.test(await page.locator("#home .lead").innerText()));
  const yDoors = await page.locator("#home .doors").evaluate((n) => n.getBoundingClientRect().top);
  const yMap = await page.locator("#home .home-map").evaluate((n) => n.getBoundingClientRect().top);
  check(T("the three entry points come before the workflow map"), yDoors < yMap);
  const fold = page.locator("#home .map-fold");
  if (mobile) {
    check(T("phone: the workflow map starts folded"), (await fold.evaluate((n) => n.open)) === false && (await page.locator("#home .wfmap a:visible").count()) === 0);
    await fold.locator("summary").focus();
    await page.keyboard.press("Enter");
    check(T("phone: the map opens from the keyboard and its seven stages are reachable"), (await fold.evaluate((n) => n.open)) && (await page.locator("#home .wfmap a:visible").count()) === 7);
    check(T("phone: no overflow with the map open"), !(await overflow()));
    await snap("home-map-open");
    await page.keyboard.press("Enter");
    check(T("phone: the map folds again"), (await fold.evaluate((n) => n.open)) === false);
  } else {
    check(T("desktop: the map is open and its toggle is hidden"), (await fold.evaluate((n) => n.open)) && !(await fold.locator("summary").isVisible()));
    const collide = () => page.evaluate(() => {
      const board = document.querySelector("#home .wf-board");
      const R = (n) => n.getBoundingClientRect();
      const boxes = [...board.querySelectorAll(".wf-lane span, .wf-n, .wf-t, .wf-q")].map((n) => ({ n, r: R(n), name: n.className + ":" + n.textContent.slice(0, 14) }));
      const bad = [];
      for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
        const p = boxes[i].r, q = boxes[j].r;
        if (p.left < q.right - 0.5 && q.left < p.right - 0.5 && p.top < q.bottom - 0.5 && q.top < p.bottom - 0.5) bad.push(boxes[i].name + " x " + boxes[j].name);
      }
      const B = R(board);
      const lanes = [...board.querySelectorAll(".wf-lane")].map(R);
      for (const nd of board.querySelectorAll(".wf-node")) {
        const r = R(nd);
        const lane = lanes.find((l) => nd.classList.contains("wf-" + (nd.className.match(/wf-(studio|orca|printer)/) || [])[1]) && r.top >= l.top - 1 && r.top < l.bottom);
        if (!lane || r.bottom > lane.bottom + 0.5) bad.push("node leaves its lane: " + nd.textContent.slice(0, 20));
        if (r.left < B.left || r.right > B.right) bad.push("node leaves the board: " + nd.textContent.slice(0, 20));
      }
      // the connecting line must not run through any text
      const path = board.querySelector(".wf-line"), svg = board.querySelector(".wf-svg");
      const sb = R(svg), vb = svg.viewBox.baseVal, len = path.getTotalLength();
      const text = [...board.querySelectorAll(".wf-t, .wf-q")].map((n) => ({ r: R(n), t: n.textContent.slice(0, 14) }));
      for (let s = 0; s <= len; s += 4) {
        const pt = path.getPointAtLength(s);
        const x = sb.left + (pt.x / vb.width) * sb.width, y = sb.top + (pt.y / vb.height) * sb.height;
        const hit = text.find((t) => x > t.r.left && x < t.r.right && y > t.r.top && y < t.r.bottom);
        if (hit) { bad.push("line crosses text: " + hit.t); break; }
      }
      return [...new Set(bad)];
    });
    for (const w of [1280, 1000]) {
      await page.setViewportSize({ width: w, height: 900 });
      await page.waitForTimeout(60);
      const bad = await collide();
      check(T("workflow map has no collisions at " + w + " px"), bad.length === 0, bad.join("; "));
    }
    await page.setViewportSize(viewport);
    await snap("home-map");
  }

  /* ---------- every page: deep link, title, focus, overflow, images ---------- */
  for (const id of pageIds) {
    await go(`#${id}`);
    const ok = (await active()) === id && (await nActive()) === 1;
    check(T(`deep link #${id}`), ok);
    if (!ok) continue;
    check(T(`#${id} has a heading and a title`), (await page.locator(`#${id} .ptitle`).count()) === 1 && (await page.title()).includes("Snapmaker Studio guide"));
    check(T(`#${id} has no horizontal overflow`), !(await overflow()));
    const broken = await page.evaluate(async (pid) => {
      const bad = [];
      for (const im of document.querySelectorAll(`#${pid} img`)) {
        const r = await fetch(im.getAttribute("src"));
        if (!r.ok || !(r.headers.get("content-type") || "").startsWith("image/")) bad.push(im.getAttribute("src"));
      }
      return bad;
    }, id);
    check(T(`#${id} images load`), broken.length === 0, broken.join(", "));
  }

  /* ---------- old lesson links still land somewhere right ---------- */
  for (const [old, to] of Object.entries(DATA.redirects)) {
    await go(`#${old}`);
    check(T(`old link #${old} opens ${to}`), (await active()) === to);
    check(T(`old link #${old} is rewritten to #${to}`), (await page.evaluate(() => location.hash)) === `#${to}`);
  }
  await go("#path-prepare--do");
  check(T("a section link opens its page"), (await active()) === "path-prepare");
  await go("#no-such-page");
  check(T("an unknown link falls back to home"), (await active()) === "home");

  /* ---------- the path: structure of a stage ---------- */
  await go("#path-prepare");
  for (const sel of [".evidence img", ".means-table", ".do .steps", ".done .checks", ".wfmap [aria-current=step]", ".example"]) check(T(`stage has ${sel}`), (await page.locator(`#path-prepare ${sel}`).count()) > 0);
  check(T("stage map marks the current stage"), /Prepare/.test(await page.locator("#path-prepare .wfmap [aria-current=step]").first().textContent()));
  check(T("stage means table has a certainty word for every row"), await page.evaluate(() => [...document.querySelectorAll("#path-prepare .means-table tbody tr")].every((r) => r.querySelector(".cert")?.textContent.trim().length > 3)));
  check(T("stage focus lands on the heading after navigating"), await (async () => {
    await page.locator("#path-prepare .stage-nav a.btn-primary").click();
    await page.waitForTimeout(80);
    return (await page.evaluate(() => document.activeElement?.classList.contains("ptitle"))) && (await active()) === "path-review";
  })());
  await page.goBack(); await page.waitForTimeout(80);
  check(T("browser Back returns to the previous stage"), (await active()) === "path-prepare");

  /* numbered notes are optional and explain controls */
  await go("#path-check");
  await eager();
  const toggle = page.locator("#path-check .toggle-notes");
  check(T("numbered notes are off by default"), (await page.locator("#path-check .hs:visible").count()) === 0 && (await toggle.getAttribute("aria-pressed")) === "false");
  await toggle.click();
  const hs = page.locator("#path-check .hs:visible");
  check(T("numbered notes appear on request"), (await hs.count()) > 0);
  if (await hs.count()) {
    await hs.first().scrollIntoViewIfNeeded();
    await hs.first().click();
    check(T("a numbered note explains its control"), (await page.locator("#path-check .hs-callout:visible").first().innerText()).length > 30);
  }
  await snap("stage-check-notes");
  await toggle.click();

  /* viewer: open, focus, Escape, focus restored */
  const opener = page.locator("#path-check .shot-open").first();
  await opener.scrollIntoViewIfNeeded();
  await opener.focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(60);
  check(T("enlarging a screenshot opens the viewer"), await page.locator("#viewer[open]").count() === 1);
  check(T("viewer moves focus inside"), (await page.evaluate(() => document.activeElement?.id)) === "viewer-close");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(60);
  check(T("Escape closes the viewer"), (await page.locator("#viewer[open]").count()) === 0);
  check(T("focus returns to the screenshot button"), await page.evaluate(() => document.activeElement?.classList.contains("shot-open")));

  /* ---------- examples ---------- */
  // placement: choose
  await go("#path-prepare");
  await eager();
  const px = page.locator('#path-prepare .example[data-example="placement"]');
  await px.scrollIntoViewIfNeeded();
  check(T("placement example is interactive and the static copy is hidden"), (await px.locator(".ex-live").isVisible()) && !(await px.locator(".ex-static").isVisible()));
  const placement = DATA.examples.placement;
  for (let c = 0; c < placement.cases.length; c++) {
    const cs = placement.cases[c];
    check(T(`placement case ${c + 1} is announced`), new RegExp(`Case ${c + 1} of ${placement.cases.length}`, "i").test(await px.locator(".ex-progress").innerText()));
    // first pick a non-best option (if any) to confirm wrong answers are explained, then retry is not offered; next case follows
    const wrongIdx = cs.options.findIndex((o) => o.verdict !== "best");
    const bestIdx = cs.options.findIndex((o) => o.verdict === "best");
    const pick = c === 0 ? wrongIdx : bestIdx;
    await px.locator("label.opt").nth(pick).click();
    await px.getByRole("button", { name: "Check my answer" }).click();
    const fbText = await px.locator(".ex-feedback").innerText();
    check(T(`placement case ${c + 1}: feedback explains the choice`), fbText.length > 40);
    if (c === 0) {
      check(T("placement case 1: a wrong answer also shows the best one"), /The best answer/.test(fbText));
      await snap("example-placement");
    }
    check(T(`placement case ${c + 1}: answers lock after checking`), (await px.locator("fieldset input:disabled").count()) === cs.options.length);
    await px.getByRole("button", { name: c + 1 < placement.cases.length ? "Next case" : "Finish" }).click();
  }
  check(T("placement example ends with a score"), /of 3 cases/.test(await px.locator(".ex-live").innerText()));
  await px.getByRole("button", { name: "Try the cases again" }).click();
  check(T("placement example can be repeated"), /Case 1 of/i.test(await px.locator(".ex-progress").innerText()));

  // assign vs load: multi
  const ax = page.locator('#path-prepare .example[data-example="assign-vs-load"]');
  await ax.scrollIntoViewIfNeeded();
  const al = DATA.examples["assign-vs-load"].items;
  for (const [i, it] of al.entries()) if (it.answer) await ax.locator("label.opt").nth(i).click();
  await ax.getByRole("button", { name: "Check my answers" }).click();
  check(T("assign-vs-load: all correct scores full marks"), new RegExp(`${al.length} of ${al.length} right`).test(await ax.locator(".score").innerText()));
  check(T("assign-vs-load: every statement gets feedback"), (await ax.locator(".ex-feedback .fb").count()) === al.length);
  await snap("example-assign");

  // read the change: sort (with a wrong answer first)
  await go("#path-review");
  await eager();
  const rx = page.locator('#path-review .example[data-example="read-change"]');
  await rx.scrollIntoViewIfNeeded();
  await rx.getByRole("button", { name: "Check my sorting" }).click();
  check(T("read-change: an unfinished sort is not marked"), /Not finished/.test(await rx.locator(".ex-feedback").innerText()));
  const rc = DATA.examples["read-change"];
  for (const [i, it] of rc.items.entries()) {
    const ans = i === 0 ? rc.categories.find((c) => c.id !== it.answer).id : it.answer;
    await rx.locator(`input[name="ex-read-change-i${i}"][value="${ans}"]`).locator("xpath=..").click();
  }
  await rx.getByRole("button", { name: "Check my sorting" }).click();
  const rcScore = await rx.locator(".score").innerText();
  check(T("read-change: score reflects the one deliberate mistake"), new RegExp(`${rc.items.length - 1} of ${rc.items.length}`).test(rcScore));
  check(T("read-change: the mistake is explained with the right bucket"), /Not quite — this one is/.test(await rx.locator(".sort-row").first().innerText()));
  await snap("example-read-change");

  // unknown vs confirmed: sort, keyboard only
  await go("#path-job");
  await eager();
  const ux = page.locator('#path-job .example[data-example="unknown-vs-confirmed"]');
  await ux.scrollIntoViewIfNeeded();
  const uc = DATA.examples["unknown-vs-confirmed"];
  await ux.locator(`input[name="ex-unknown-vs-confirmed-i0"]`).first().focus();
  await page.keyboard.press("Space");
  check(T("unknown-vs-confirmed: a radio can be chosen from the keyboard"), (await ux.locator('input[name="ex-unknown-vs-confirmed-i0"]:checked').count()) === 1);
  for (const [i, it] of uc.items.entries()) await ux.locator(`input[name="ex-unknown-vs-confirmed-i${i}"][value="${it.answer}"]`).locator("xpath=..").click();
  await ux.getByRole("button", { name: "Check my sorting" }).click();
  check(T("unknown-vs-confirmed: full marks when sorted right"), new RegExp(`${uc.items.length} of ${uc.items.length}`).test(await ux.locator(".score").innerText()));
  await ux.getByRole("button", { name: "Try again" }).click();
  check(T("unknown-vs-confirmed: can try again"), (await ux.locator("input:checked").count()) === 0 && (await ux.getByRole("button", { name: "Check my sorting" }).count()) === 1);

  /* ---------- search ---------- */
  await go("");
  await page.locator("body").click({ position: { x: 5, y: 300 } });
  await page.keyboard.press("/");
  check(T("the / key focuses search"), (await page.evaluate(() => document.activeElement?.id)) === "q");
  await page.keyboard.type("object off the plate");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(100);
  check(T("search opens the results page"), (await active()) === "search");
  const hits = await page.locator("#search-out .result a.rt").evaluateAll((a) => a.map((x) => x.getAttribute("href")));
  check(T("search for 'object off the plate' finds the placement warning first"), hits[0] === "#problem-object-outside-area" || hits.includes("#problem-object-outside-area"), hits.slice(0, 4).join(","));
  check(T("search results carry an excerpt"), (await page.locator("#search-out .result p").first().innerText()).length > 20);
  check(T("search keeps the query in the address (shareable)"), /^#search:/.test(await page.evaluate(() => location.hash)));
  await snap("search");
  await page.locator("#search-out .result a.rt").first().click();
  await page.waitForTimeout(80);
  check(T("a search result opens its page"), (await active()) === hits[0].slice(1));
  await go("#search:" + encodeURIComponent("zzqx nothing"));
  check(T("a search with no match shows an empty state with next steps"), (await page.locator("#search-out .empty").count()) === 1 && (await page.locator("#search-out .empty a").count()) >= 3);
  for (const [q, want] of [["nozzle", "nozzle"], ["different printer", "sliced-for-different-printer"], ["spool", "spool"], ["watch folder", "watch"]]) {
    await go("#search:" + encodeURIComponent(q));
    const r = await page.locator("#search-out .result a.rt").evaluateAll((a) => a.map((x) => x.getAttribute("href")));
    check(T(`search '${q}' finds something relevant`), r.some((h) => h.includes(want)), r.slice(0, 5).join(","));
  }
  for (const s of DATA.suggestions) {
    await go("#search:" + encodeURIComponent(s));
    check(T(`suggested search '${s}' returns results`), (await page.locator("#search-out .result").count()) > 0);
  }
  await go("#search:" + encodeURIComponent("amp mar colors"));
  check(T("highlighting never breaks entities or marks"), await page.evaluate(() => { const h = document.querySelector("#search-out").innerHTML; return !/&<mark>|<mark>[^<]*<mark>|<[/]mark>[a-z]*;/.test(h) && !/&amp;<mark>amp/.test(h); }));
  await go("#search");
  check(T("empty search offers suggestions"), (await page.locator("#search-out .suggest a").count()) === DATA.suggestions.length);
  await page.locator("#q").fill("nozzle");
  await page.waitForTimeout(80);
  check(T("typing on the search page updates results live"), (await page.locator("#search-out .result").count()) > 0);

  /* ---------- tasks and warnings ---------- */
  await go("#tasks");
  const groups = await page.locator("#tasks .tgroup").count();
  check(T("task list is grouped by need"), groups >= 5);
  check(T("optional tools are marked optional"), (await page.locator("#tasks .opt-inline").count()) > 0);
  await snap("tasks");
  await page.locator('#tasks .filters button[data-filter="prepare"]').click();
  check(T("task filter narrows the list"), (await page.locator("#tasks .tgroup:visible").count()) === 1 && (await page.locator('#tasks .filters button[aria-pressed="true"]').count()) === 1);
  await page.locator('#tasks .filters button[data-filter="all"]').click();
  check(T("task filter can be cleared"), (await page.locator("#tasks .tgroup:visible").count()) === groups);
  await page.locator("#tasks .tlist a").first().click();
  await page.waitForTimeout(80);
  check(T("selecting a task opens it"), pageTypes[await active()] === "task");
  check(T("task page has steps and a success signal"), (await page.locator("article.page.is-active .steps").count()) > 0 && (await page.locator("article.page.is-active .done .checks li").count()) > 0);
  await snap("task");

  await go("#problems");
  check(T("warnings are grouped by how sure Studio is"), (await page.locator("#problems .pgroup").count()) >= 4);
  await page.locator('#problems .filters button[data-filter="unknown"]').click();
  check(T("warning filter narrows the list"), (await page.locator("#problems .pgroup:visible").count()) === 1);
  await go("#problem-studio-cant-tell");
  check(T("warning page shows how sure Studio is, in words and shape"), (await page.locator("article.page.is-active .howsure .cert").count()) === 1 && (await page.locator("article.page.is-active .meter li").count()) === 5);
  check(T("warning page says what not to conclude"), (await page.locator("article.page.is-active .dont").count()) === 1);
  await snap("problem");

  /* ---------- navigation, keyboard, theme ---------- */
  await go("#path-open");
  check(T("current section is marked in the top navigation"), (await page.locator('.bar-nav [data-nav="path"][aria-current=page]').count()) === 1);
  await go("#problem-controls-off");
  check(T("warning pages mark Warnings as current"), (await page.locator('.bar-nav [data-nav="problems"][aria-current=page]').count()) === 1);
  await go("");
  await page.keyboard.press("Tab");
  check(T("first Tab stop is the skip link"), (await page.evaluate(() => document.activeElement?.className)) === "skip");
  await page.keyboard.press("Enter");
  check(T("skip link stays on the page and focuses the main content"), (await active()) === "home" && (await page.evaluate(() => document.activeElement?.id)) === "main");
  await go("#problem-controls-off");
  await page.locator(".skip").focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(60);
  check(T("on another page the skip link does not jump to home"), (await active()) === "problem-controls-off" && (await page.evaluate(() => document.activeElement?.id)) === "main");
  await go("");
  if (mobile) await page.locator("#home .map-fold summary").click();
  const mapLink = page.locator("#home .wfmap a[href=\"#path-orca\"]:visible").first();
  await mapLink.focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(80);
  check(T("a map stage is reachable and opens by keyboard"), (await active()) === "path-orca");
  await page.locator("#theme-btn").focus();
  const before = await page.evaluate(() => document.documentElement.dataset.theme);
  await page.keyboard.press("Enter");
  const after = await page.evaluate(() => document.documentElement.dataset.theme);
  check(T("theme switch works from the keyboard"), before !== after);
  await page.keyboard.press("Enter");
  check(T("theme switch toggles back"), (await page.evaluate(() => document.documentElement.dataset.theme)) === before);
  check(T("focus ring is visible on the focused control"), await page.evaluate(() => { const o = getComputedStyle(document.activeElement).outlineStyle; return o !== "none"; }));

  /* readable with a wider fallback font */
  await page.addInitScript(() => { const s = new CSSStyleSheet(); s.replaceSync("*{font-family:Verdana,sans-serif!important}"); document.adoptedStyleSheets = [...document.adoptedStyleSheets, s]; });
  for (const id of ["home", "path-prepare", "tasks", "problem-studio-cant-tell", "search"]) {
    await go(`#${id}`);
    check(T(`#${id} has no sideways scroll with a wide fallback font`), !(await overflow()));
    if (id === "home" && !mobile) { const bad = await page.evaluate(() => { const board = document.querySelector("#home .wf-board"); const rs = [...board.querySelectorAll(".wf-lane span, .wf-n, .wf-t, .wf-q")].map((n) => ({ r: n.getBoundingClientRect(), t: n.textContent.slice(0, 12) })); const out = []; for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) { const p = rs[i].r, q = rs[j].r; if (p.left < q.right - 0.5 && q.left < p.right - 0.5 && p.top < q.bottom - 0.5 && q.top < p.bottom - 0.5) out.push(rs[i].t + " x " + rs[j].t); } const lanes = [...board.querySelectorAll(".wf-lane")].map((l) => l.getBoundingClientRect()); for (const nd of board.querySelectorAll(".wf-node")) { const r = nd.getBoundingClientRect(); const l = lanes.find((x) => r.top >= x.top - 1 && r.top < x.bottom); if (!l || r.bottom > l.bottom + 0.5) out.push("leaves lane: " + nd.textContent.slice(0, 14)); } return out; }); check(T("workflow map has no collisions with a wide fallback font"), bad.length === 0, bad.join("; ")); }
  }
  await go("#home");
  await snap("home-final");
  await go("#path-prepare");
  await eager();
  await page.evaluate(() => document.querySelector("#path-prepare .example")?.scrollIntoView({ block: "start" }));
  await snap("stage-prepare");

  check(T("no console errors (page served with a strict CSP)"), errors.length === 0, errors.join(" | "));
  await ctx.close();
}

await run("desktop-dark", { width: 1280, height: 900 }, "dark");
await run("desktop-light", { width: 1280, height: 900 }, "light");
await run("phone-dark", { width: 390, height: 844 }, "dark");
await run("phone-light", { width: 390, height: 844 }, "light");

/* ---------- without JavaScript: complete and readable ---------- */
{
  const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 }, javaScriptEnabled: false });
  const page = await ctx.newPage();
  await page.goto(base, { waitUntil: "load" });
  const shown = await page.evaluate(() => Array.from(document.querySelectorAll("article.page")).filter((l) => getComputedStyle(l).display !== "none").length);
  check("no-JS: every page is readable", shown === pageIds.length, `${shown} of ${pageIds.length}`);
  check("no-JS: search explains it needs JavaScript and points to lists", /needs JavaScript/.test(await page.locator("#search-out").innerText()));
  check("no-JS: the search box and theme button are hidden", !(await page.locator("#search-form").isVisible()) && !(await page.locator("#theme-btn").isVisible()));
  check("no-JS: worked examples are shown as text", (await page.locator(".ex-static:visible").count()) === 4);
  check("no-JS: control notes are plain text", (await page.locator(".controls-notes").count()) > 10);
  check("no-JS: every old lesson link has an anchor", (await page.locator(".legacy-anchor").count()) === Object.keys(DATA.redirects).length);
  if (shotsDir) await page.screenshot({ path: join(shotsDir, "no-javascript.png") });
  await ctx.close();
}

await browser.close();
server.close();
const failed = results.filter((r) => !r.ok);
console.log(`${results.length - failed.length}/${results.length} browser checks passed`);
process.exit(failed.length ? 1 : 0);
