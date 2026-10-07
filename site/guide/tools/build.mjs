#!/usr/bin/env node
// Builds public/index.html from content/*.json. No dependencies.
//   node tools/build.mjs            validate + build (fails on any problem)
//   node tools/build.mjs --draft    warn instead of fail when screenshot geometry is missing (while capturing)
import { readFileSync, writeFileSync, existsSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const { inline, esc, plain } = await import(pathToFileURL(join(root, "public/assets/md.js")).href);
const draft = process.argv.includes("--draft");
const read = (p) => JSON.parse(readFileSync(join(root, p), "utf8"));
const content = read("content/lessons.json");
const shots = read("content/shots.json");
const geometry = existsSync(join(root, "content/geometry.json")) ? read("content/geometry.json") : {};
const problems = [];
const warn = [];
const bad = (m) => problems.push(m);

const links = content.links;
const resolve = (k) => links[k];
const md = (t) => inline(t, resolve);

/* ---------- validation ---------- */
const slugSet = new Set();
const usedShots = new Set();
const lessons = content.lessons;
for (const [i, l] of lessons.entries()) {
  const at = `lesson ${i + 1} (${l.id})`;
  for (const f of ["id", "title", "short", "goal", "steps", "expect", "next"]) if (!l[f] || (Array.isArray(l[f]) && !l[f].length)) bad(`${at}: missing "${f}"`);
  if (slugSet.has(l.id)) bad(`${at}: duplicate id`);
  slugSet.add(l.id);
  if (!/^[a-z][a-z0-9-]*$/.test(l.id)) bad(`${at}: id must be lowercase-hyphen`);
  for (const f of l.figures || []) usedShots.add(f.shot);
  for (const s of l.demo?.steps || []) usedShots.add(s.shot);
  for (const b of l.branches || []) if (b.shot) usedShots.add(b.shot);
}
for (const id of usedShots) {
  const s = shots[id];
  if (!s) { bad(`shot "${id}" is used but not defined in shots.json`); continue; }
  if (!s.file || !existsSync(join(root, "public/assets/img", s.file))) bad(`shot "${id}": image file ${s.file} not found in public/assets/img`);
  if (!s.alt || s.alt.length < 25) bad(`shot "${id}": alt text missing or too short`);
  if (!s.title) bad(`shot "${id}": missing title`);
  const g = geometry[id];
  if (!g) { (draft ? warn : problems).push(`shot "${id}": no capture geometry (run npm run capture)`); continue; }
  for (const h of s.hotspots || []) if (!g.hotspots?.[h.key]) (draft ? warn : problems).push(`shot "${id}": hotspot "${h.key}" has no captured position`);
}
// Two numbered circles must never sit on top of each other: a person could not tell which one they are clicking.
for (const id of usedShots) {
  const g = geometry[id];
  const hs = (shots[id]?.hotspots || []).map((h, i) => ({ n: i + 1, key: h.key, g: g?.hotspots?.[h.key] })).filter((h) => h.g);
  for (let a = 0; a < hs.length; a++) for (let b = a + 1; b < hs.length; b++) {
    const dx = Math.abs(hs[a].g.x - hs[b].g.x) * g.width / 100;
    const dy = Math.abs(hs[a].g.y - hs[b].g.y) * g.height / 100;
    if (dx < 44 && dy < 44) bad(`shot "${id}": hotspots ${hs[a].n} (${hs[a].key}) and ${hs[b].n} (${hs[b].key}) overlap (${Math.round(dx)}x${Math.round(dy)} px apart in the picture)`);
  }
}
for (const l of lessons) for (const s of l.demo?.steps || []) {
  const sh = shots[s.shot];
  const m = /circle \*\*(\d+)\*\*/.exec(s.instruction);
  if (sh && m) {
    const idx = (sh.hotspots || []).findIndex((h) => h.key === s.hotspot) + 1;
    if (idx !== Number(m[1])) bad(`lesson ${l.id}: demo says circle ${m[1]} but hotspot "${s.hotspot}" of shot "${s.shot}" is number ${idx}`);
  }
  if (sh && !(sh.hotspots || []).some((h) => h.key === s.hotspot)) bad(`lesson ${l.id}: demo step uses unknown hotspot "${s.hotspot}" of shot "${s.shot}"`);
}
const allText = JSON.stringify([content, shots]);
if (/\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/.test(allText)) bad("content contains something that looks like an IP address");
if (/[A-Za-z]:\\\\Users\\\\(?!you\\\\)/i.test(allText) || /\/home\/[a-z]/i.test(allText)) bad("content contains a local path");
if (/\b(octo|codex|sonnet|opus|fable|gemini|antigravity)\b/i.test(allText)) bad("content contains an internal tooling term");
if (/\b100% (print )?success\b|guaranteed print/i.test(allText.replace(/not a guarantee|never claims|does not guarantee/gi, ""))) bad("content makes a guarantee claim");

if (problems.length) {
  console.error("Guide build failed:\n - " + problems.join("\n - "));
  process.exit(1);
}
for (const w of warn) console.warn("warning:", w);

/* ---------- rendering ---------- */
const lessonUrl = (id) => `#${id}`;
const num = (n) => String(n);

function figureHtml(shotId, captionOverride, { compact = false } = {}) {
  const s = shots[shotId];
  const g = geometry[shotId] || { width: s.width || 1230, height: s.height || 960 };
  const items = (s.hotspots || []).map((h, i) => ({ ...h, n: i + 1 }));
  const rows = items.map((h) => `<li><span class="num" aria-hidden="true">${h.n}</span><span><strong class="t">${esc(h.title)}</strong>${md(h.text)}</span></li>`).join("");
  const list = !items.length ? ""
    : compact ? `<details class="hs-details"><summary>What the numbers mean</summary><ol class="hs-text">${rows}</ol></details>`
    : `<h4 class="vh">What the numbers mean</h4><ol class="hs-text">${rows}</ol>`;
  return `<figure class="shot${compact ? " compact" : ""}" data-shot="${esc(shotId)}">
  <p class="swipe-hint">Swipe sideways to see the whole screenshot, or tap it to enlarge.</p>
  <div class="shot-scroll"><div class="shot-frame"><img src="assets/img/${esc(s.file)}" alt="${esc(s.alt)}" width="${g.width}" height="${g.height}" loading="lazy" decoding="async"></div></div>
  <figcaption>${md(captionOverride || s.caption)}</figcaption>
  ${list}
</figure>`;
}

function lessonHtml(l, i) {
  const prev = lessons[i - 1];
  const next = lessons[i + 1];
  const meta = [`<li>About ${esc(l.time || "5 min")}</li>`];
  if (l.group) meta.push(`<li>${esc(l.group)}</li>`);
  if (l.optional) meta.push(`<li>Optional</li>`);
  const parts = [];
  parts.push(`<header class="lesson-head">
  <p class="kicker">Lesson ${i + 1} of ${lessons.length}</p>
  <h2 class="title" id="${esc(l.id)}-title" tabindex="-1">${i + 1}. ${esc(l.title)}</h2>
  <p class="goal"><b>Goal:</b> ${md(l.goal)}</p>
  <ul class="meta" aria-label="Lesson details">${meta.join("")}</ul>
</header>`);
  if (l.demo) parts.push(`<p class="js-only"><a class="btn btn-sm" href="#${esc(l.id)}-demo">Jump to the example walkthrough ↓</a></p>`);
  if (l.prereq?.length) parts.push(`<div class="block"><h3>Before you start</h3><ul class="steps">${l.prereq.map((p) => `<li>${md(p)}</li>`).join("")}</ul></div>`);
  if (l.explain && l.explain.position === "before") parts.push(explainHtml(l.explain));
  parts.push(`<div class="block"><h3>Steps</h3><ol class="steps">${l.steps.map((s) => stepHtml(s)).join("")}</ol></div>`);
  for (const f of l.figures || []) parts.push(`<div class="block">${figureHtml(f.shot, f.caption)}</div>`);
  parts.push(`<div class="block expect"><h3>What you should see</h3><ul>${l.expect.map((e) => `<li>${md(e)}</li>`).join("")}</ul></div>`);
  if (l.explain && l.explain.position !== "before") parts.push(explainHtml(l.explain));
  for (const n of l.notes || []) {
    const kind = { unknown: "unknown", safe: "safe", limit: "limit" }[n.kind] || "";
    const tag = { unknown: "Studio can’t tell", safe: "Your files are safe", limit: "Not in this version", tip: "Tip", important: "Important" }[n.kind] || "Note";
    parts.push(`<div class="note ${kind}"><span class="tag">${tag}</span><p>${md(n.text)}</p></div>`);
  }
  if (l.branches?.length) {
    parts.push(`<div class="block"><h3>Optional tools — pick the one you need</h3><div class="branches">${l.branches.map((b) => `<section class="branch" id="${esc(l.id)}-${esc(b.id)}" aria-labelledby="${esc(l.id)}-${esc(b.id)}-h">
  <h4 id="${esc(l.id)}-${esc(b.id)}-h">${esc(b.title)}</h4>
  <p class="when">${md(b.when)}</p>
  <ol>${b.steps.map((s) => `<li>${md(s)}</li>`).join("")}</ol>
  ${b.see ? `<p class="see">${md(b.see)}</p>` : ""}
  ${b.shot ? figureHtml(b.shot, b.caption, { compact: true }) : ""}
</section>`).join("")}</div></div>`);
  }
  if (l.demo) parts.push(demoHtml(l));
  if (l.help?.length) parts.push(`<div class="block help"><h3>If this looks different</h3>${l.help.map((h) => `<details><summary>${md(h.if)}</summary><div>${(Array.isArray(h.then) ? h.then : [h.then]).map((t) => `<p>${md(t)}</p>`).join("")}</div></details>`).join("")}</div>`);
  parts.push(`<p class="next-line">${next ? "Next: " : "You’re done: "}${md(l.next)}</p>`);
  parts.push(`<nav class="lesson-nav" aria-label="Lesson navigation">
  ${prev ? `<a class="btn js-prev" href="${lessonUrl(prev.id)}" rel="prev">← Back<span class="vh">: ${esc(prev.title)}</span></a>` : "<span></span>"}
  ${next ? `<a class="btn btn-primary js-next" href="${lessonUrl(next.id)}" rel="next">Next →<span class="vh">: ${esc(next.title)}</span></a>` : `<a class="btn" href="#top">Back to the start</a>`}
</nav>`);
  return `<section class="lesson" id="${esc(l.id)}" data-index="${i}" aria-labelledby="${esc(l.id)}-title">\n${parts.join("\n")}\n</section>`;
}

function explainHtml(e) {
  return `<div class="block"><h3>${esc(e.title)}</h3><div class="branches">${e.items.map((i) => `<div class="branch"><h4>${esc(i.h)}</h4><p class="when">${md(i.text)}</p></div>`).join("")}</div></div>`;
}

function stepHtml(s) {
  if (typeof s === "string") return `<li>${md(s)}</li>`;
  return `<li>${md(s.text)}${s.sub?.length ? `<ul>${s.sub.map((x) => `<li>${md(x)}</li>`).join("")}</ul>` : ""}</li>`;
}

function demoHtml(l) {
  const d = l.demo;
  const steps = d.steps;
  return `<div class="block"><div class="demo" id="${esc(l.id)}-demo" data-demo="${esc(l.id)}" role="group" aria-label="Example walkthrough: ${esc(d.title)}">
  <span class="demo-label">Example walkthrough</span>
  <h3>${esc(d.title)}</h3>
  <p class="intro">${md(d.intro)}</p>
  <ol class="demo-static">${steps.map((s) => `<li>${md(s.instruction)} <em>${md(s.result)}</em></li>`).join("")}</ol>
  <p class="swipe-hint" hidden>Swipe sideways to see the whole picture.</p>
  <div class="demo-stage-slot shot-scroll js-only" hidden></div>
  <div class="demo-panel js-only" hidden>
    <div class="demo-say" aria-live="polite"></div>
    <div class="demo-actions">
      <button type="button" class="btn btn-primary btn-sm demo-next" disabled>Next step</button>
      <button type="button" class="btn btn-sm demo-reset">Start this example again</button>
    </div>
    <ol class="demo-steps"></ol>
  </div>
  <p class="demo-safe">This is a picture-based example inside the guide. It never connects to a printer, sends a file or changes anything on your computer.</p>
</div></div>`;
}

const welcome = content.welcome;
const site = content.site;
const tocHtml = lessons.map((l, i) => `<li><a href="${lessonUrl(l.id)}" data-lesson="${esc(l.id)}"><span class="n">${i + 1}</span><span>${esc(l.short)}</span></a></li>`).join("");
const segsHtml = lessons.map(() => "<li></li>").join("");

/* data for the client */
const shotData = {};
for (const id of usedShots) {
  const s = shots[id];
  const g = geometry[id];
  shotData[id] = {
    src: `assets/img/${s.file}`, alt: s.alt, title: s.title, caption: plain(s.caption), width: g?.width || 1230, height: g?.height || 960,
    hotspots: (s.hotspots || []).map((h, i) => ({ key: h.key, n: i + 1, title: h.title, html: md(h.text) })),
  };
}
const demos = {};
for (const l of lessons) if (l.demo) {
  demos[l.id] = { steps: l.demo.steps.map((s) => ({ shot: s.shot, hotspot: s.hotspot, instructionHtml: md(s.instruction), resultHtml: md(s.result) })) };
}
const geomOut = {};
for (const id of usedShots) if (geometry[id]) geomOut[id] = geometry[id];
const dataJson = JSON.stringify({
  lessons: lessons.map((l) => ({ id: l.id, title: l.title, short: l.short })),
  shots: shotData, demos, geometry: geomOut,
}).replace(/</g, "\\u003c");

const html = `<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(site.title)}</title>
<meta name="description" content="${esc(site.description)}">
<meta name="color-scheme" content="dark light">
<link rel="icon" href="assets/brand/favicon.svg" type="image/svg+xml">
<script src="assets/theme-init.js"></script>
<link rel="stylesheet" href="assets/guide.css">
</head>
<body id="top">
<a class="skip" href="#main">Skip to the guide</a>
<header class="top">
  <div class="top-in">
    <a class="brand" href="#top" aria-label="Snapmaker Studio user guide — start">
      <img class="mark mark-color" src="assets/brand/icon.svg" alt="" width="34" height="34">
      <span class="mark-mono" aria-hidden="true"></span>
      <span>Snapmaker Studio<small>User guide · v${esc(site.guideVersion)}</small></span>
    </a>
    <nav class="top-nav" aria-label="Guide">
      <a class="hide-sm" href="#top">Start</a>
      <a class="hide-sm" href="#${esc(lessons[0].id)}">Install</a>
      <a class="hide-sm" href="#${esc(lessons[lessons.length - 1].id)}">Help</a>
      <a class="hide-sm" href="${esc(links.repo)}" rel="noopener noreferrer" target="_blank">GitHub<span class="vh"> (opens in a new tab)</span></a>
      <button type="button" class="btn-ghost menu-btn js-only" id="menu-btn" aria-expanded="false" aria-controls="toc">Lessons</button>
      <button type="button" class="btn-ghost js-only" id="theme-btn" aria-label="Switch to the light theme"><span class="label">Light theme</span></button>
    </nav>
  </div>
</header>
<main id="main">
<section class="welcome" aria-labelledby="welcome-title">
  <div class="wrap welcome-grid">
    <div>
      <p class="eyebrow">${esc(welcome.eyebrow)}</p>
      <h1 id="welcome-title">${md(welcome.title)}</h1>
      <p class="lede">${md(welcome.lede)}</p>
      <p class="version-line">${md(welcome.versionLine)}</p>
      <p class="disclaimer">${md(site.disclaimer)}</p>
      <p class="nojs-note">${md(welcome.noJs)}</p>
    </div>
    <div>
      <div class="card">
        <h2>${esc(welcome.cardTitle)}</h2>
        <p>${md(welcome.cardText)}</p>
        <a class="btn btn-primary" id="start-tour" href="${lessonUrl(lessons[0].id)}"><span id="start-label">Start the tour →</span></a>
      </div>
      <div class="card tourbar js-only" aria-labelledby="tour-count">
        <div class="count" id="tour-count" aria-live="polite">Lesson 1 of ${lessons.length}</div>
        <p class="sub" id="tour-sub">Tour position</p>
        <ol class="segs" id="tour-segs" aria-hidden="true">${segsHtml}</ol>
        <div class="row"><button type="button" class="btn btn-sm" id="start-again">Start again</button></div>
        <p class="sub tight">This shows where you are in the tour, not what you have completed. Your place is saved in this browser only.</p>
      </div>
    </div>
  </div>
</section>
<div class="wrap shell" id="tour">
  <aside class="toc" id="toc" aria-label="Lessons">
    <h2>Tour steps</h2>
    <p class="hint">One lesson at a time</p>
    <ol>${tocHtml}</ol>
  </aside>
  <div class="lessons">
${lessons.map(lessonHtml).join("\n")}
  </div>
</div>
</main>
<footer class="foot">
  <div class="wrap">
    <p>${md(site.disclaimer)}</p>
    <p>${md(site.footer)}</p>
  </div>
</footer>
<dialog class="viewer" id="viewer" aria-labelledby="viewer-title">
  <div class="viewer-bar"><h2 id="viewer-title">Screenshot</h2><button type="button" class="btn btn-sm" id="viewer-close">Close</button></div>
  <div class="viewer-body" id="viewer-body"></div>
</dialog>
<script type="application/json" id="guide-data">${dataJson}</script>
<script type="module" src="assets/guide.js"></script>
</body>
</html>
`;
writeFileSync(join(root, "public/index.html"), html);
console.log(`built public/index.html — ${lessons.length} lessons, ${usedShots.size} screenshots${warn.length ? `, ${warn.length} warning(s)` : ""}`);
