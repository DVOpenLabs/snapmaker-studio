// Client-side search over the index embedded in the page. Nothing leaves the browser.
import { DATA, escapeHtml, el } from "./common.js";

const STOP = new Set(["the", "a", "an", "to", "of", "in", "on", "is", "it", "and", "or", "my", "for", "do", "i", "how", "what", "why", "can", "with", "this", "that"]);
const norm = (s) => s.toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/[’']/g, "");
const stem = (w) => (w.length > 4 && w.endsWith("s") && !w.endsWith("ss") ? w.slice(0, -1) : w);
const words = (s) => norm(s).split(/[^a-z0-9]+/).filter(Boolean).map(stem);

const docs = DATA.index.map((d) => ({
  d,
  title: words(d.title),
  keywords: words(d.keywords),
  segs: d.segs.map((s) => ({ ...s, hw: new Set(words(s.h)), tw: new Set(words(s.t)) })),
}));

function terms(q) {
  const all = words(q);
  const kept = all.filter((w) => !STOP.has(w));
  return kept.length ? kept : all;
}

const has = (list, t) => list.some((w) => w === t || (t.length > 3 && w.startsWith(t)));

function scoreDoc(doc, ts) {
  let score = 0;
  let matched = 0;
  const segScore = doc.segs.map(() => 0);
  for (const t of ts) {
    let hit = false;
    if (has(doc.title, t)) { score += 10; hit = true; }
    if (has(doc.keywords, t)) { score += 6; hit = true; }
    doc.segs.forEach((s, i) => {
      if (has([...s.hw], t)) { score += 3; segScore[i] += 3; hit = true; }
      if (has([...s.tw], t)) { score += 1; segScore[i] += 1; hit = true; }
    });
    if (hit) matched += 1;
  }
  return { score, matched, segScore };
}

function excerpt(seg, ts) {
  const text = seg.t;
  const low = norm(text);
  let at = -1;
  for (const t of ts) { const i = low.indexOf(t.replace(/s$/, "")); if (i >= 0 && (at < 0 || i < at)) at = i; }
  const start = Math.max(0, at - 50);
  let snip = text.slice(start, start + 180);
  if (start > 0) snip = "…" + snip.replace(/^\S*\s/, "");
  if (start + 180 < text.length) snip = snip.replace(/\s\S*$/, "") + "…";
  let html = escapeHtml(snip);
  for (const t of ts) {
    const re = new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/s$/, "")}[a-z0-9]*)`, "gi");
    html = html.replace(re, "<mark>$1</mark>");
  }
  return html;
}

export function search(q) {
  const ts = terms(q);
  if (!ts.length) return { terms: ts, results: [], fallback: false };
  const run = (needAll) => docs
    .map((doc) => ({ doc, ...scoreDoc(doc, ts) }))
    .filter((r) => (needAll ? r.matched === ts.length : r.matched > 0))
    .sort((a, b) => b.score - a.score)
    .slice(0, 12);
  let results = run(true);
  let fallback = false;
  if (!results.length && ts.length > 2) { results = run(false).filter((r) => r.matched >= ts.length - 1); fallback = results.length > 0; }
  return {
    terms: ts,
    fallback,
    results: results.map((r) => {
      const best = r.segScore.reduce((bi, v, i, a) => (v > a[bi] ? i : bi), 0);
      const seg = r.doc.d.segs[best] || r.doc.d.segs[0];
      return { id: r.doc.d.id, title: r.doc.d.title, kind: r.doc.d.kind, type: r.doc.d.type, heading: seg?.h || "", excerpt: seg ? excerpt(seg, ts) : "" };
    }),
  };
}

export function renderSearch(container, q) {
  container.textContent = "";
  const query = q.trim();
  if (!query) {
    container.append(el("p", {}, "Type what you are trying to do or the words Studio showed you, for example:"),
      el("ul", { class: "suggest" }, DATA.suggestions.map((s) => `<li><a href="#search:${encodeURIComponent(s)}">${escapeHtml(s)}</a></li>`).join("")));
    return 0;
  }
  const { results, fallback } = search(query);
  if (!results.length) {
    const box = el("div", { class: "empty", role: "status" });
    box.innerHTML = `<h3>Nothing matched “${escapeHtml(query)}”</h3>
      <p>The guide only covers what Studio v1.5.0 does. Try fewer or different words, or browse:</p>
      <ul><li><a href="#tasks">Find help for my current task</a></li><li><a href="#problems">Understand a warning or problem</a></li><li><a href="#path-open">Follow the example project from the start</a></li></ul>
      <p>Something missing from the guide? <a href="${DATA.links.issues}" rel="noopener noreferrer" target="_blank">Tell us on GitHub<span class="vh"> (opens in a new tab)</span></a>.</p>`;
    container.appendChild(box);
    return 0;
  }
  container.appendChild(el("p", { class: "result-count", role: "status" },
    `${results.length} result${results.length === 1 ? "" : "s"} for “${escapeHtml(query)}”${fallback ? " — none matched every word, so these match some of them" : ""}`));
  const list = el("ol", { class: "results" });
  for (const r of results) {
    list.appendChild(el("li", { class: "result" },
      `<span class="kind">${escapeHtml(r.kind)}</span><a class="rt" href="#${escapeHtml(r.id)}">${escapeHtml(r.title)}</a>${r.excerpt ? `<p>${r.heading && r.heading !== "Overview" ? `<b>${escapeHtml(r.heading.replace(/[.:!?]+$/, ""))}:</b> ` : ""}${r.excerpt}</p>` : ""}`));
  }
  container.appendChild(list);
  return results.length;
}
