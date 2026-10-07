#!/usr/bin/env node
// Builds public/index.html from content/*.json. No dependencies.
//   node tools/build.mjs            validate + build (fails on any problem)
//   node tools/build.mjs --draft    warn instead of fail when screenshot geometry is missing (while capturing)
//
// The page is complete without JavaScript: every page (home, the example path, tasks, warnings) is rendered in order, the
// interactive examples are rendered as worked examples, and search is replaced by the lists you can scroll.
// guide.js then shows one page at a time and adds search, the interactive examples, hotspots and the viewer.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const { inline, esc, plain } = await import(pathToFileURL(join(root, "public/assets/md.js")).href);
const draft = process.argv.includes("--draft");
const read = (p) => JSON.parse(readFileSync(join(root, p), "utf8"));
const G = read("content/guide.json");
const stages = read("content/path.json");
const { groups: taskGroups, tasks } = read("content/tasks.json");
const problems = read("content/problems.json");
const examples = read("content/examples.json");
const shots = read("content/shots.json");
const geometry = existsSync(join(root, "content/geometry.json")) ? read("content/geometry.json") : {};
const bad = [];
const warn = [];
const fail = (m) => bad.push(m);
const md = (t) => inline(t, (k) => G.links[k]);

/* ---------- page registry ---------- */
const pageId = {
  stage: (s) => s.page,
  task: (t) => t.page ?? `task-${t.id}`,
  problem: (p) => `problem-${p.id}`,
};
const byStage = Object.fromEntries(stages.map((s) => [s.id, s]));
const byTask = Object.fromEntries(tasks.map((t) => [t.id, t]));
const byProblem = Object.fromEntries(problems.map((p) => [p.id, p]));
const pages = new Set(["home", "tasks", "problems", "search", ...stages.map(pageId.stage), ...tasks.map(pageId.task), ...problems.map(pageId.problem)]);
const usedShots = new Set();
const useShot = (id, where) => { if (!id) return; if (!shots[id]) fail(`${where}: unknown shot "${id}"`); else usedShots.add(id); };

/* ---------- validation ---------- */
const OPTIONAL_EMPTY = new Set(["prereq", "differs", "notes", "problems", "tasks", "do", "examples"]);
const need = (obj, fields, where) => {
  for (const f of fields) {
    const v = obj[f];
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length && !OPTIONAL_EMPTY.has(f))) fail(`${where}: missing "${f}"`);
  }
};
const seen = new Set();
const unique = (id, where) => { if (seen.has(id)) fail(`${where}: duplicate page id "${id}"`); seen.add(id); };
for (const s of stages) {
  const w = `stage ${s.id}`;
  need(s, ["id", "page", "n", "lane", "label", "title", "question", "lead", "evidence", "means", "steps", "success", "keywords", "next"], w);
  unique(s.page, w);
  for (const e of s.evidence.shots) useShot(e.shot, w);
  for (const m of s.means) if (!G.certainty[m.certainty]) fail(`${w}: unknown certainty "${m.certainty}"`);
  for (const id of s.problems || []) if (!byProblem[id]) fail(`${w}: unknown problem "${id}"`);
  for (const id of s.tasks || []) if (!byTask[id]) fail(`${w}: unknown task "${id}"`);
  for (const id of s.examples || []) if (!examples[id]) fail(`${w}: unknown example "${id}"`);
  if (!pages.has(s.next.page)) fail(`${w}: next page "${s.next.page}" does not exist`);
}
const groupIds = new Set(taskGroups.map((g) => g.id));
for (const t of tasks) {
  const w = `task ${t.id}`;
  need(t, ["id", "group", "title", "when", "steps", "success", "keywords"], w);
  unique(pageId.task(t), w);
  if (!groupIds.has(t.group)) fail(`${w}: unknown group "${t.group}"`);
  useShot(t.shot, w);
  for (const id of t.problems || []) if (!byProblem[id]) fail(`${w}: unknown problem "${id}"`);
}
for (const p of problems) {
  const w = `problem ${p.id}`;
  need(p, ["id", "label", "certainty", "seen", "means", "why", "do", "dont", "keywords"], w);
  unique(pageId.problem(p), w);
  if (!G.certainty[p.certainty]) fail(`${w}: unknown certainty "${p.certainty}"`);
  useShot(p.shot, w);
  for (const id of p.tasks || []) if (!byTask[id]) fail(`${w}: unknown task "${id}"`);
  for (const sId of p.seen) if (!byStage[sId]) fail(`${w}: unknown stage "${sId}"`);
}
for (const m of G.map) if (!pages.has(m.page)) fail(`map ${m.id}: page "${m.page}" does not exist`);
for (const [from, to] of Object.entries(G.redirects)) if (!pages.has(to)) fail(`redirect ${from}: target "${to}" does not exist`);
for (const d of G.home.doors) { if (!pages.has(d.cta.page)) fail(`home door ${d.id}: bad cta`); for (const l of d.links) if (!pages.has(l.page)) fail(`home door ${d.id}: bad link ${l.page}`); }
for (const [id, ex] of Object.entries(examples)) {
  const w = `example ${id}`;
  useShot(ex.shot, w);
  if (!["choose", "sort", "multi"].includes(ex.type)) fail(`${w}: unknown type`);
  if (ex.type === "choose") for (const c of ex.cases) { useShot(c.shot, w); if (c.options.filter((o) => o.verdict === "best").length !== 1) fail(`${w}/${c.id}: needs exactly one "best" option`); }
  if (ex.type === "sort") for (const it of ex.items) if (!ex.categories.some((c) => c.id === it.answer)) fail(`${w}: item answer "${it.answer}" is not a category`);
  if (ex.type === "multi") for (const it of ex.items) if (typeof it.answer !== "boolean") fail(`${w}: multi answers must be true/false`);
}
const referencedExamples = new Set(stages.flatMap((s) => s.examples || []));
for (const id of Object.keys(examples)) if (!referencedExamples.has(id)) fail(`example "${id}" is not used by any stage`);

/* screenshots: files, alt text, geometry, hotspot overlap */
for (const id of usedShots) {
  const s = shots[id];
  if (!s) continue;
  if (!s.file || !existsSync(join(root, "public/assets/img", s.file))) fail(`shot "${id}": image file ${s.file} not found`);
  if (!s.alt || s.alt.length < 25) fail(`shot "${id}": alt text missing or too short`);
  if (!s.title) fail(`shot "${id}": missing title`);
  const g = geometry[id];
  if (!g) { (draft ? warn : bad).push(`shot "${id}": no capture geometry (run npm run capture)`); continue; }
  for (const h of s.hotspots || []) if (!g.hotspots?.[h.key]) (draft ? warn : bad).push(`shot "${id}": hotspot "${h.key}" has no captured position`);
  const hs = (s.hotspots || []).map((h, i) => ({ n: i + 1, key: h.key, g: g.hotspots?.[h.key] })).filter((h) => h.g);
  for (let a = 0; a < hs.length; a++) for (let b = a + 1; b < hs.length; b++) {
    const dx = Math.abs(hs[a].g.x - hs[b].g.x) * g.width / 100;
    const dy = Math.abs(hs[a].g.y - hs[b].g.y) * g.height / 100;
    if (dx < 44 && dy < 44) fail(`shot "${id}": hotspots ${hs[a].n} (${hs[a].key}) and ${hs[b].n} (${hs[b].key}) overlap`);
  }
}

/* text lint */
const allText = JSON.stringify([G, stages, tasks, problems, examples, shots]);
if (/\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/.test(allText)) fail("content contains something that looks like an IP address");
if (/[A-Za-z]:\\\\Users\\\\(?!you\\\\)/i.test(allText) || /\/home\/[a-z]/i.test(allText)) fail("content contains a local path");
if (/\b(octo|codex|sonnet|opus|fable|gemini|antigravity)\b/i.test(allText)) fail("content contains an internal tooling term");
if (/\b100% (print )?success\b|guaranteed print/i.test(allText.replace(/not a guarantee|never claims|does not guarantee|never a guarantee|not a promise/gi, ""))) fail("content makes a guarantee claim");

if (bad.length) { console.error("Guide build failed:\n - " + bad.join("\n - ")); process.exit(1); }
for (const w of warn) console.warn("warning:", w);

/* ---------- rendering helpers ---------- */
const CERT_ICON = { confirmed: "●", check: "▲", unknown: "?", ok: "✓", info: "i" };
const badge = (c) => `<span class="cert cert-${c}"><span class="cert-ico" aria-hidden="true">${CERT_ICON[c]}</span>${esc(G.certainty[c].label)}</span>`;
const href = (id) => `#${id}`;
const link = (id, text, cls = "") => `<a${cls ? ` class="${cls}"` : ""} href="${href(id)}">${text}</a>`;
const laneLabel = (id) => G.lanes.find((l) => l.id === id).label;
const taskLink = (id) => link(pageId.task(byTask[id]), esc(byTask[id].title));
const problemChip = (id) => {
  const p = byProblem[id];
  return `<a class="chip cert-${p.certainty}" href="${href(pageId.problem(p))}"><span class="cert-ico" aria-hidden="true">${CERT_ICON[p.certainty]}</span>${esc(p.label.length > 44 ? p.label.slice(0, 42) + "…" : p.label)}</a>`;
};

function stepsHtml(steps) {
  return `<ol class="steps">${steps.map((s) => typeof s === "string"
    ? `<li>${md(s)}</li>`
    : `<li>${md(s.text)}${s.sub?.length ? `<ul>${s.sub.map((x) => `<li>${md(x)}</li>`).join("")}</ul>` : ""}</li>`).join("")}</ol>`;
}
const NOTE_TAG = { unknown: "Studio can’t tell", safe: "Safety", limit: "Limit", tip: "Tip", important: "Important" };
const notesHtml = (notes = []) => notes.map((n) => `<div class="note note-${n.kind}"><span class="tag">${NOTE_TAG[n.kind] || "Note"}</span><p>${md(n.text)}</p></div>`).join("");
function differsHtml(items = []) {
  if (!items.length) return "";
  return `<section class="block differs"><h3>If something is different</h3>${items.map((h) => `<details><summary>${md(h.if)}</summary><div><p>${md(h.then)}</p></div></details>`).join("")}</section>`;
}
function figureHtml(shotId, label) {
  const s = shots[shotId];
  const g = geometry[shotId] || { width: 1230, height: 960 };
  const items = (s.hotspots || []).map((h, i) => ({ ...h, n: i + 1 }));
  const rows = items.map((h) => `<li><span class="num" aria-hidden="true">${h.n}</span><span><strong class="t">${esc(h.title)}</strong>${md(h.text)}</span></li>`).join("");
  return `<figure class="shot" data-shot="${esc(shotId)}">
  ${label ? `<p class="shot-label">${md(label)}</p>` : ""}
  <p class="swipe-hint">Swipe sideways to see the whole screenshot, or tap it to enlarge.</p>
  <div class="shot-scroll"><div class="shot-frame"><img src="assets/img/${esc(s.file)}" alt="${esc(s.alt)}" width="${g.width}" height="${g.height}" loading="lazy" decoding="async"></div></div>
  <figcaption>${md(s.caption)}</figcaption>
  ${items.length ? `<details class="controls-notes"><summary>Notes on the controls in this screenshot</summary><ol class="hs-text">${rows}</ol></details>` : ""}
</figure>`;
}

/* ---------- the workflow map ---------- */
const MAP_W = 1000;
// Pixel geometry (y is never scaled, only x), so text can never collide with lanes or lines:
// lane height, and the y of the stage marker centre inside a lane, per size.
const GEO = { full: { laneH: 140, cy: 43 }, compact: { laneH: 88, cy: 33 } };
const MAP_X = [96, 236, 376, 516, 668, 800, 922];
function mapHtml({ current = null, compact = false } = {}) {
  const geo = compact ? GEO.compact : GEO.full;
  const MAP_H = geo.laneH * 3;
  const LANE_Y = { studio: geo.cy, orca: geo.laneH + geo.cy, printer: geo.laneH * 2 + geo.cy };
  const pts = G.map.map((m, i) => ({ ...m, x: MAP_X[i], y: LANE_Y[m.lane] }));
  // Lane changes are drawn so the line never crosses a stage's text (the text sits under its marker):
  // going down, run level first and drop just before the next marker; going up, rise right after leaving.
  const path = pts.map((p, i) => {
    if (i === 0) return `M ${p.x} ${p.y}`;
    const q = pts[i - 1];
    if (q.y === p.y) return `L ${p.x} ${p.y}`;
    if (p.y > q.y) return `L ${p.x - 45} ${q.y} C ${p.x - 23} ${q.y}, ${p.x - 22} ${p.y}, ${p.x} ${p.y}`;
    return `C ${q.x + 22} ${q.y}, ${q.x + 23} ${p.y}, ${q.x + 45} ${p.y} L ${p.x} ${p.y}`;
  }).join(" ");
  const ribbons = ["#00E1FF", "#FF00FF", "#FFFF00", "#0000FF", "#32CD32", "#FF8500", "#8F00FF"].map((c, i) => {
    const y0 = LANE_Y.studio - 27 + i * 9;
    return `<path d="M 0 ${y0} C 40 ${y0}, 52 ${LANE_Y.studio}, ${MAP_X[0] - 22} ${LANE_Y.studio}" stroke="${c}" stroke-width="2" fill="none" opacity=".85" vector-effect="non-scaling-stroke"/>`;
  }).join("");
  const lanes = G.lanes.map((l) => `<div class="wf-lane wf-lane-${l.id}"><span>${esc(l.label)}</span></div>`).join("");
  const nodes = pts.map((p, i) => `<a class="wf-node wf-${p.lane} wf-p${i}${current === p.id ? " is-current" : ""}" href="${href(p.page)}" data-stage="${p.id}"${current === p.id ? ' aria-current="step"' : ""}><span class="wf-n" aria-hidden="true">${p.id === "print" ? "★" : i + 1}</span><span class="wf-t">${esc(p.label)}</span>${compact ? "" : `<span class="wf-q">${esc(p.ask)}</span>`}</a>`).join("");
  return `<nav class="wfmap${compact ? " compact" : ""}" aria-label="The job, stage by stage: Studio, then Snapmaker Orca, then Studio again, then your printer">
  <div class="wf-board">
    ${lanes}
    <svg class="wf-svg" viewBox="0 0 ${MAP_W} ${MAP_H}" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      ${ribbons}
      <path class="wf-line" d="${path}" fill="none" vector-effect="non-scaling-stroke"/>
    </svg>
    ${nodes}
  </div>
  <ol class="wf-list">${pts.map((p, i) => `<li${current === p.id ? ' aria-current="step"' : ""}><a href="${href(p.page)}"><b>${p.id === "print" ? "★" : i + 1}. ${esc(p.label)}</b> <span>${esc(p.ask)}</span> <i>${esc(laneLabel(p.lane))}</i></a></li>`).join("")}</ol>
</nav>`;
}

/* ---------- interactive examples (worked-example fallback; guide.js makes them interactive) ---------- */
function exampleHtml(id) {
  const ex = examples[id];
  const label = `<span class="ex-badge">Example — answers come from what Studio shows; nothing here touches your files or printer</span>`;
  let body;
  if (ex.type === "choose") {
    body = ex.cases.map((c) => `<section class="ex-case-static"><h4>${esc(c.title)}</h4>${c.shot ? figureHtml(c.shot) : ""}<ul class="facts">${c.facts.map((f) => `<li>${md(f)}</li>`).join("")}</ul>
      <p class="ex-q"><strong>${esc(c.question)}</strong></p><ul class="ex-opts">${c.options.map((o) => `<li class="verdict-${o.verdict}"><strong>${md(o.label)}</strong> <em>${o.verdict === "best" ? "Best answer." : o.verdict === "ok" ? "Reasonable, with a catch." : "Not correct."}</em> ${md(o.feedback)}</li>`).join("")}</ul></section>`).join("");
  } else if (ex.type === "sort") {
    body = `${ex.shot ? figureHtml(ex.shot) : ""}<ul class="ex-opts">${ex.items.map((it) => { const cat = ex.categories.find((c) => c.id === it.answer); return `<li><strong>${md(it.text)}</strong> <em>→ ${esc(cat.label)}.</em> ${md(it.feedback)}</li>`; }).join("")}</ul>`;
  } else {
    body = `${ex.shot ? figureHtml(ex.shot) : ""}<ul class="ex-opts">${ex.items.map((it) => `<li class="verdict-${it.answer ? "best" : "wrong"}"><strong>${md(it.text)}</strong> <em>${it.answer ? "Yes, Studio does this." : "No, Studio does not do this."}</em> ${md(it.feedback)}</li>`).join("")}</ul>`;
  }
  return `<section class="example" id="ex-${esc(id)}" data-example="${esc(id)}" aria-labelledby="ex-${esc(id)}-h">
  ${label}
  <h3 id="ex-${esc(id)}-h">${esc(ex.title)}</h3>
  <p class="ex-intro">${md(ex.intro)}</p>
  <div class="ex-static"><p class="ex-static-note">Worked example (the interactive version needs JavaScript):</p>${body}</div>
  <div class="ex-live" hidden></div>
  <ul class="takeaways"><li class="tk-head">What to take from it</li>${ex.takeaways.map((t) => `<li>${md(t)}</li>`).join("")}</ul>
</section>`;
}

/* ---------- page renderers ---------- */
function asideStage(s) {
  const rel = (s.problems || []).map(problemChip).join("");
  const tk = (s.tasks || []).map((id) => `<li>${taskLink(id)}</li>`).join("");
  return `<aside class="stage-aside" aria-label="Related">
  <nav class="onpage" aria-label="On this page"><h4>On this page</h4><ul>
    <li><a href="#${s.page}--evidence" data-jump="${s.page}--evidence">What Studio shows</a></li><li><a href="#${s.page}--means" data-jump="${s.page}--means">What the result means</a></li>
    ${(s.examples || []).length ? `<li><a href="#${s.page}--decide" data-jump="${s.page}--decide">Try it</a></li>` : ""}<li><a href="#${s.page}--do" data-jump="${s.page}--do">What to do</a></li><li><a href="#${s.page}--done" data-jump="${s.page}--done">You are done when</a></li></ul></nav>
  ${rel ? `<div class="aside-block"><h4>Related warnings</h4><div class="chips">${rel}</div></div>` : ""}
  ${tk ? `<div class="aside-block"><h4>Related tasks</h4><ul>${tk}</ul></div>` : ""}
</aside>`;
}
function stageHtml(s, i) {
  const prev = stages[i - 1];
  const next = stages[i + 1];
  const meansRows = s.means.map((m) => `<tr><td data-l="You see">${md(m.seen)}</td><td data-l="It means">${md(m.meaning)}</td><td data-l="How sure is Studio?">${badge(m.certainty)}</td><td data-l="You do">${md(m.action)}</td></tr>`).join("");
  const ev = s.evidence;
  return `<article class="page stage lane-${s.lane}" id="${s.page}" data-page="${s.page}" data-type="stage" data-stage="${s.id}" aria-labelledby="${s.page}-h">
  <header class="stage-head">
    <p class="crumb"><a href="#home">Guide</a> <span aria-hidden="true">›</span> <a href="#path-open">Example project</a> <span aria-hidden="true">›</span> Stage ${s.n} of ${stages.length}</p>
    ${mapHtml({ current: s.id, compact: true })}
    <p class="lane-tag lane-${s.lane}">${esc(laneLabel(s.lane))}</p>
    <h2 class="ptitle" id="${s.page}-h" tabindex="-1"><span class="q-mark" aria-hidden="true">Q</span>${esc(s.question)}</h2>
    <p class="lead">${md(s.lead)}</p>
  </header>
  <div class="stage-grid">
    <div class="stage-main">
      <section class="block evidence" id="${s.page}--evidence" aria-labelledby="${s.page}-ev"><h3 id="${s.page}-ev">What Studio shows</h3>
        <p class="evidence-note">Real screenshots from Studio v1.5.0. ${md(ev.note)}</p>
        <button type="button" class="btn btn-sm js-only toggle-notes" aria-pressed="false">Show numbered notes on the controls</button>
        ${ev.shots.map((e) => figureHtml(e.shot, e.label)).join("")}
      </section>
      <section class="block means" id="${s.page}--means" aria-labelledby="${s.page}-me"><h3 id="${s.page}-me">What the result means</h3>
        <table class="means-table"><thead><tr><th scope="col">You see</th><th scope="col">It means</th><th scope="col">How sure is Studio?</th><th scope="col">You do</th></tr></thead><tbody>${meansRows}</tbody></table>
        <p class="legend">How sure is Studio? ${Object.keys(G.certainty).map((c) => badge(c)).join(" ")} <a href="#problems">What these mean</a></p>
      </section>
      ${(s.examples || []).length ? `<section class="block decide" id="${s.page}--decide" aria-label="Try it">${s.examples.map(exampleHtml).join("")}</section>` : ""}
      <section class="block do" id="${s.page}--do" aria-labelledby="${s.page}-do"><h3 id="${s.page}-do">What to do</h3>${stepsHtml(s.steps)}</section>
      <section class="block done" id="${s.page}--done" aria-labelledby="${s.page}-dn"><h3 id="${s.page}-dn">You are done when</h3><ul class="checks">${s.success.map((x) => `<li>${md(x)}</li>`).join("")}</ul></section>
      ${differsHtml(s.differs)}
      ${notesHtml(s.notes)}
      <nav class="stage-nav" aria-label="Next and previous stage">
        ${prev ? `<a class="btn js-nav" href="${href(prev.page)}" rel="prev">← Stage ${prev.n}: ${esc(prev.label)}</a>` : `<a class="btn js-nav" href="#home">← Guide home</a>`}
        <a class="btn btn-primary js-nav" href="${href(s.next.page)}"${next ? ' rel="next"' : ""}>${esc(s.next.why)} →</a>
      </nav>
    </div>
    ${asideStage(s)}
  </div>
</article>`;
}
function taskHtml(t) {
  const id = pageId.task(t);
  const g = taskGroups.find((x) => x.id === t.group);
  const prob = (t.problems || []).map(problemChip).join("");
  const stageFor = { start: "open", check: "check", prepare: "prepare", review: "orca", job: "job", printer: "print" }[t.group];
  const stageEntry = G.map.find((m) => m.id === stageFor);
  return `<article class="page task" id="${id}" data-page="${id}" data-type="task" aria-labelledby="${id}-h">
  <header class="task-head">
    <p class="crumb"><a href="#home">Guide</a> <span aria-hidden="true">›</span> <a href="#tasks">Tasks</a> <span aria-hidden="true">›</span> ${esc(g.label)}</p>
    <h2 class="ptitle" id="${id}-h" tabindex="-1">${esc(t.title)}</h2>
    ${t.optional ? `<p class="opt-tag">Optional tool — not needed for the main path</p>` : ""}
    <p class="when"><strong>Use this when:</strong> ${md(t.when)}</p>
  </header>
  <div class="task-grid">
    <div class="task-main">
      ${t.prereq?.length ? `<section class="block"><h3>Before you start</h3><ul class="plain">${t.prereq.map((p) => `<li>${md(p)}</li>`).join("")}</ul></section>` : ""}
      <section class="block"><h3>Steps</h3>${stepsHtml(t.steps)}</section>
      <section class="block done"><h3>You are done when</h3><ul class="checks">${t.success.map((x) => `<li>${md(x)}</li>`).join("")}</ul></section>
      ${differsHtml(t.differs)}
      ${notesHtml(t.notes)}
    </div>
    <aside class="task-aside" aria-label="Related">
      ${t.shot ? figureHtml(t.shot) : ""}
      ${prob ? `<div class="aside-block"><h4>Related warnings</h4><div class="chips">${prob}</div></div>` : ""}
      ${stageEntry && t.group !== "tools" && t.group !== "maintain" ? `<div class="aside-block"><h4>Where this fits</h4><p>${link(stageEntry.page, esc(`Example path: ${stageEntry.label} — ${stageEntry.ask}`))}</p></div>` : ""}
    </aside>
  </div>
</article>`;
}
const METER = ["confirmed", "check", "unknown", "ok", "info"];
function problemHtml(p) {
  const id = pageId.problem(p);
  const meter = METER.map((c) => `<li class="${c === p.certainty ? "on" : ""} cert-${c}"${c === p.certainty ? ' aria-current="true"' : ""}>${esc(G.certainty[c].label)}</li>`).join("");
  return `<article class="page problem" id="${id}" data-page="${id}" data-type="problem" aria-labelledby="${id}-h">
  <header class="problem-head">
    <p class="crumb"><a href="#home">Guide</a> <span aria-hidden="true">›</span> <a href="#problems">Warnings</a></p>
    <p class="seen">${esc(p.speaker || "Studio")} says</p>
    <h2 class="ptitle label-text" id="${id}-h" tabindex="-1">${esc(p.label)}</h2>
    <div class="howsure"><p class="hs-q">${p.speaker ? "What kind of message is this?" : "How sure is Studio?"}</p><ul class="meter" aria-label="Certainty: ${esc(G.certainty[p.certainty].label)}">${meter}</ul><p class="hs-a">${badge(p.certainty)} ${esc(G.certainty[p.certainty].means)}</p></div>
  </header>
  <div class="problem-grid">
    <div class="problem-main">
      <section class="block"><h3>What it means</h3><p>${md(p.means)}</p></section>
      <section class="block"><h3>Why you see this</h3><p>${md(p.why)}</p></section>
      <section class="block do"><h3>What to do</h3><ol class="steps">${p.do.map((x) => `<li>${md(x)}</li>`).join("")}</ol></section>
      <section class="block dont"><h3>What not to conclude</h3><p>${md(p.dont)}</p></section>
    </div>
    <aside class="problem-aside" aria-label="Related">
      ${p.shot ? figureHtml(p.shot) : ""}
      <div class="aside-block"><h4>Seen at</h4><ul>${p.seen.map((sid) => `<li>${link(byStage[sid].page, esc(`Stage ${byStage[sid].n}: ${byStage[sid].title}`))}</li>`).join("")}</ul></div>
      ${(p.tasks || []).length ? `<div class="aside-block"><h4>Related tasks</h4><ul>${p.tasks.map((x) => `<li>${taskLink(x)}</li>`).join("")}</ul></div>` : ""}
    </aside>
  </div>
</article>`;
}
function tasksIndexHtml() {
  return `<article class="page index" id="tasks" data-page="tasks" data-type="index" aria-labelledby="tasks-h">
  <header class="index-head"><p class="crumb"><a href="#home">Guide</a> <span aria-hidden="true">›</span> Tasks</p><h2 class="ptitle" id="tasks-h" tabindex="-1">Find help for my current task</h2>
    <p class="lead">Pick what you are doing. Tasks that are not part of the main path are marked <span class="opt-inline">optional</span>.</p></header>
  <div class="filters js-only" role="group" aria-label="Filter tasks"><button type="button" class="chip is-on" data-filter="all" aria-pressed="true">All</button>${taskGroups.map((g) => `<button type="button" class="chip" data-filter="${g.id}" aria-pressed="false">${esc(g.label)}</button>`).join("")}</div>
  ${taskGroups.map((g) => `<section class="tgroup" data-group="${g.id}" aria-labelledby="tg-${g.id}"><h3 id="tg-${g.id}">${esc(g.label)}</h3><p class="blurb">${esc(g.blurb)}</p>
    <ul class="tlist">${tasks.filter((t) => t.group === g.id).map((t) => `<li>${link(pageId.task(t), `<strong>${esc(t.title)}</strong>${t.optional ? ' <span class="opt-inline">optional</span>' : ""}<span class="when-s">${md(t.when)}</span>`)}</li>`).join("")}</ul></section>`).join("")}
</article>`;
}
function problemsIndexHtml() {
  return `<article class="page index" id="problems" data-page="problems" data-type="index" aria-labelledby="problems-h">
  <header class="index-head"><p class="crumb"><a href="#home">Guide</a> <span aria-hidden="true">›</span> Warnings</p><h2 class="ptitle" id="problems-h" tabindex="-1">Understand a warning or problem</h2>
    <p class="lead">Every message below is marked by how sure Studio is, because the right response differs for a fact, a possibility and a gap.</p></header>
  <dl class="legend-grid">${METER.map((c) => `<div class="cert-${c}"><dt>${badge(c)}</dt><dd>${esc(G.certainty[c].means)}</dd></div>`).join("")}</dl>
  <div class="filters js-only" role="group" aria-label="Filter warnings"><button type="button" class="chip is-on" data-filter="all" aria-pressed="true">All</button>${METER.map((c) => `<button type="button" class="chip" data-filter="${c}" aria-pressed="false">${esc(G.certainty[c].label)}</button>`).join("")}</div>
  ${METER.map((c) => { const list = problems.filter((p) => p.certainty === c); return list.length ? `<section class="pgroup" data-group="${c}" aria-labelledby="pg-${c}"><h3 id="pg-${c}">${badge(c)}</h3><ul class="plist">${list.map((p) => `<li>${link(pageId.problem(p), `<strong class="label-text">${esc(p.label)}</strong><span class="when-s">${md(p.means)}</span>`)}</li>`).join("")}</ul></section>` : ""; }).join("")}
</article>`;
}
function homeHtml() {
  const H = G.home;
  return `<article class="page home" id="home" data-page="home" data-type="home" aria-labelledby="home-h">
  <header class="home-head">
    <p class="eyebrow">Snapmaker Studio · guide for v${esc(G.site.version)}</p>
    <h2 class="ptitle" id="home-h" tabindex="-1">Get your project ready to print</h2>
    <p class="lead">Check a downloaded model, prepare a U1 copy, and understand what to review before printing.</p>
  </header>
  <section class="doors" aria-label="Where to start">
    ${H.doors.map((d, i) => `<div class="door door-${d.id}"><h3>${esc(d.title)}</h3><p>${md(d.text)}</p>${d.links.length ? `<ul>${d.links.map((l) => `<li>${link(l.page, md(l.label))}</li>`).join("")}</ul>` : ""}<a class="btn ${i === 0 ? "btn-primary" : ""} js-nav" href="${href(d.cta.page)}">${esc(d.cta.label)} →</a></div>`).join("")}
  </section>
  <section class="home-map" aria-label="The whole job"><details class="map-fold" open><summary>See the whole job<small>Studio, Snapmaker Orca and your printer, stage by stage</small></summary>${mapHtml()}</details>
    <p class="map-key">Studio works on your computer. <strong>Snapmaker Orca slices</strong>: it turns the model into G-code, the instructions your printer runs. You decide when the print starts. Studio never slices and never starts a print on its own.</p></section>
  <section class="home-foot" aria-label="Before you start">
    <div><h3>Not installed yet?</h3><p>${link("setup", "Install and open Studio")} — about ten minutes. If Studio is already installed, skip it: the example starts from opening a file.</p></div>
    <div><h3>Optional tools</h3><p>Cost, scale, print quality, batch, model sites and spool providers are under ${link("tasks", "Tasks")}, marked optional, so they never interrupt the main path.</p></div>
    <div id="not-shown"><h3>What this guide does not show</h3><p>No screenshot of a connected printer, none of Snapmaker Orca's own window, and none from Linux. Where that matters, the page says so. How each claim was verified: <a href="${G.links.repo}/blob/main/site/guide/EVIDENCE.md" rel="noopener noreferrer" target="_blank">evidence record<span class="vh"> (opens in a new tab)</span></a>.</p></div>
  </section>
</article>`;
}
function searchHtml() {
  return `<article class="page search" id="search" data-page="search" data-type="search" aria-labelledby="search-h">
  <header class="index-head"><p class="crumb"><a href="#home">Guide</a> <span aria-hidden="true">›</span> Search</p><h2 class="ptitle" id="search-h" tabindex="-1">Search the guide</h2></header>
  <div id="search-out" class="search-out" aria-live="polite"><p class="nojs-note">Search needs JavaScript. Without it, use the <a href="#tasks">task list</a> and the <a href="#problems">list of warnings</a>, which contain everything searchable.</p></div>
</article>`;
}

/* ---------- search index ---------- */
function indexDoc(id, type, kind, title, keywords, segments) {
  return { id, type, kind, title: plain(title), keywords: keywords.join(" "), segs: segments.filter((s) => s.t).map((s) => ({ h: plain(s.h || ""), t: plain(s.t) })) };
}
const index = [];
for (const s of stages) index.push(indexDoc(s.page, "stage", `Example · stage ${s.n}`, `${s.title}: ${s.question}`, s.keywords, [
  { h: "Question", t: s.question }, { h: "Overview", t: s.lead },
  ...s.means.map((m) => ({ h: plain(m.seen), t: `${m.meaning} ${m.action}` })),
  ...s.steps.map((x, i) => ({ h: `Step ${i + 1}`, t: typeof x === "string" ? x : x.text })),
  ...s.success.map((x) => ({ h: "Done when", t: x })), ...(s.differs || []).map((d) => ({ h: plain(d.if), t: d.then })),
  ...(s.examples || []).flatMap((id) => [{ h: examples[id].title, t: examples[id].intro }, ...(examples[id].takeaways || []).map((t) => ({ h: examples[id].title, t }))]),
]));
for (const t of tasks) index.push(indexDoc(pageId.task(t), "task", `Task · ${taskGroups.find((g) => g.id === t.group).label}`, t.title, t.keywords, [
  { h: "Use this when", t: t.when }, ...(t.prereq || []).map((x) => ({ h: "Before you start", t: x })),
  ...t.steps.map((x, i) => ({ h: `Step ${i + 1}`, t: typeof x === "string" ? x : x.text })), ...t.success.map((x) => ({ h: "Done when", t: x })),
  ...(t.differs || []).map((d) => ({ h: plain(d.if), t: d.then })), ...(t.notes || []).map((n) => ({ h: "Note", t: n.text })),
]));
for (const p of problems) index.push(indexDoc(pageId.problem(p), "problem", `Warning · ${G.certainty[p.certainty].label}`, p.label, p.keywords, [
  { h: "What it means", t: p.means }, { h: "Why you see this", t: p.why }, ...p.do.map((x) => ({ h: "What to do", t: x })), { h: "What not to conclude", t: p.dont },
]));

/* ---------- client data ---------- */
const shotData = {};
for (const id of usedShots) {
  const s = shots[id];
  const g = geometry[id];
  shotData[id] = { src: `assets/img/${s.file}`, alt: s.alt, title: s.title, caption: plain(s.caption), width: g?.width || 1230, height: g?.height || 960,
    hotspots: (s.hotspots || []).map((h, i) => ({ key: h.key, n: i + 1, title: h.title, html: md(h.text) })) };
}
const exData = {};
for (const [id, ex] of Object.entries(examples)) {
  exData[id] = {
    type: ex.type, title: ex.title, intro: md(ex.intro), shot: ex.shot || null, takeaways: ex.takeaways.map(md),
    categories: ex.categories?.map((c) => ({ ...c, hint: md(c.hint) })),
    cases: ex.cases?.map((c) => ({ id: c.id, title: c.title, shot: c.shot, question: c.question, facts: c.facts.map(md), options: c.options.map((o) => ({ label: md(o.label), verdict: o.verdict, feedback: md(o.feedback) })) })),
    items: ex.items?.map((i) => ({ text: md(i.text), answer: i.answer, feedback: md(i.feedback) })),
  };
}
const titles = Object.fromEntries([...stages.map((s) => [s.page, `Stage ${s.n}: ${s.question}`]), ...tasks.map((t) => [pageId.task(t), t.title]), ...problems.map((p) => [pageId.problem(p), p.label]), ["home", "Guide home"], ["tasks", "Tasks"], ["problems", "Warnings and problems"], ["search", "Search"]]);
const dataJson = JSON.stringify({
  shots: shotData, geometry: Object.fromEntries([...usedShots].filter((i) => geometry[i]).map((i) => [i, geometry[i]])), examples: exData, index,
  redirects: G.redirects, titles, stages: stages.map((s) => ({ id: s.id, page: s.page, n: s.n })), suggestions: G.home.suggestions, links: { issues: G.links.issues },
}).replace(/</g, "\\u003c");

/* ---------- document ---------- */
const pagesInOrder = [homeHtml(), ...stages.map(stageHtml), tasksIndexHtml(), ...taskGroups.flatMap((g) => tasks.filter((t) => t.group === g.id).map(taskHtml)), problemsIndexHtml(), ...problems.map(problemHtml), searchHtml()];
// old lesson links still work: an invisible anchor with the old id sits right before its new page (so it also works
// without JavaScript); guide.js additionally redirects the hash to the new page.
const legacyBefore = {};
for (const [old, to] of Object.entries(G.redirects)) (legacyBefore[to] ||= []).push(old);
const orderedPages = pagesInOrder.map((h) => {
  const id = /^<article class="page [^"]*" id="([^"]+)"/.exec(h)?.[1];
  return (legacyBefore[id] || []).map((o) => `<span class="legacy-anchor" id="${esc(o)}" data-redirect="${esc(id)}"></span>`).join("") + h;
});
const legacy = "";

const html = `<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(G.site.title)}</title>
<meta name="description" content="${esc(G.site.description)}">
<meta name="color-scheme" content="dark light">
<link rel="icon" href="assets/brand/favicon.svg" type="image/svg+xml">
<script src="assets/theme-init.js"></script>
<link rel="stylesheet" href="assets/guide.css">
</head>
<body id="top">
<a class="skip" href="#main">Skip to the guide</a>
<header class="bar">
  <div class="bar-in">
    <a class="brand" href="#home" aria-label="Snapmaker Studio guide — home">
      <img class="mark mark-color" src="assets/brand/icon.svg" alt="" width="30" height="30">
      <span class="mark-mono" aria-hidden="true"></span>
      <span class="brand-t">Snapmaker Studio<small>Guide · v${esc(G.site.version)}</small></span>
    </a>
    <form class="searchbar js-only" id="search-form" role="search" autocomplete="off">
      <label class="vh" for="q">Search the guide</label>
      <input id="q" type="search" name="q" placeholder="Search the guide" aria-keyshortcuts="/" enterkeyhint="search">
      <button type="submit" class="btn btn-sm">Search</button>
    </form>
    <nav class="bar-nav" aria-label="Guide sections">
      <a href="#path-open" data-nav="path">Example</a>
      <a href="#tasks" data-nav="tasks">Tasks</a>
      <a href="#problems" data-nav="problems">Warnings</a>
      <a href="#setup" data-nav="setup">Set up</a>
      <button type="button" class="btn-ghost js-only" id="theme-btn" aria-label="Switch to the light theme"><span class="label">Light theme</span></button>
    </nav>
  </div>
</header>
<main id="main" tabindex="-1">
<h1 class="vh">Snapmaker Studio user guide</h1>
${legacy}
${orderedPages.join("\n")}
</main>
<footer class="foot">
  <div class="wrap">
    <p>${md(G.site.disclaimer)}</p>
    <p>${md(G.site.footer)}</p>
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
console.log(`built public/index.html — ${stages.length} stages, ${tasks.length} tasks, ${problems.length} warnings, ${Object.keys(examples).length} examples, ${usedShots.size} screenshots, ${index.length} searchable pages${warn.length ? `, ${warn.length} warning(s)` : ""}`);
