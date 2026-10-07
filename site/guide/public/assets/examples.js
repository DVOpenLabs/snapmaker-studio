// Interactive examples. Each one asks for a decision, then explains why every choice is right or wrong, using only what
// Studio v1.5.0 actually shows. Nothing here touches hardware, files or the network: it only moves between pictures and text.
import { DATA, $, el, escapeHtml } from "./common.js";
import { openViewer } from "./figures.js";

const VERDICT_LABEL = { best: "Best answer", ok: "Reasonable, with a catch", wrong: "Not quite" };

function shotButton(shotId) {
  const meta = DATA.shots[shotId];
  const fig = el("figure", { class: "shot" });
  const scroll = el("div", { class: "shot-scroll" });
  const frame = el("div", { class: "shot-frame" });
  const btn = el("button", { type: "button", class: "shot-open", "aria-label": `Enlarge screenshot: ${meta.alt}` });
  btn.appendChild(el("img", { src: meta.src, alt: meta.alt, width: meta.width, height: meta.height }));
  btn.addEventListener("click", () => openViewer(shotId, btn));
  frame.appendChild(btn);
  scroll.appendChild(frame);
  fig.append(scroll, el("figcaption", {}, escapeHtml(meta.caption)));
  return fig;
}

/* ---------- choose: a few cases, one decision each ---------- */
function buildChoose(id, ex, live) {
  let i = 0;
  let best = 0;
  const answered = new Set();
  function render() {
    live.textContent = "";
    if (i >= ex.cases.length) {
      const done = el("div", { class: "fb fb-best", role: "status" },
        `<span class="fb-h">You chose the best answer in ${best} of ${ex.cases.length} cases.</span><p>The takeaways below sum up how to read these messages. Try again to see the other explanations.</p>`);
      const again = el("button", { type: "button", class: "btn btn-sm" }, "Try the cases again");
      again.addEventListener("click", () => { i = 0; best = 0; answered.clear(); render(); });
      live.append(done, el("div", { class: "ex-actions" }), again);
      again.focus();
      return;
    }
    const c = ex.cases[i];
    const name = `ex-${id}-c${i}`;
    const left = el("div", {});
    if (c.shot) left.appendChild(shotButton(c.shot));
    const right = el("div", {});
    right.appendChild(el("h4", {}, escapeHtml(c.title)));
    right.appendChild(el("ul", { class: "facts" }, c.facts.map((f) => `<li>${f}</li>`).join("")));
    const fs = el("fieldset", { class: "ex-q" });
    fs.appendChild(el("legend", {}, escapeHtml(c.question)));
    c.options.forEach((o, k) => {
      const label = el("label", { class: "opt" }, `<input type="radio" name="${name}" value="${k}"><span>${o.label}</span>`);
      fs.appendChild(label);
    });
    const feedback = el("div", { class: "ex-feedback", "aria-live": "polite" });
    const actions = el("div", { class: "ex-actions" });
    const check = el("button", { type: "button", class: "btn btn-primary btn-sm", disabled: true }, "Check my answer");
    actions.appendChild(check);
    fs.addEventListener("change", () => { check.disabled = false; });
    check.addEventListener("click", () => {
      const sel = fs.querySelector("input:checked");
      if (!sel) return;
      const choice = c.options[Number(sel.value)];
      fs.querySelectorAll("input").forEach((x) => { x.disabled = true; });
      fs.querySelectorAll(".opt").forEach((lab, k) => lab.classList.add(`is-${{ best: "correct", ok: "ok", wrong: "wrong" }[c.options[k].verdict]}`));
      let html = `<div class="fb fb-${choice.verdict}"><span class="fb-h">${VERDICT_LABEL[choice.verdict]}</span><p>${choice.feedback}</p></div>`;
      if (choice.verdict !== "best") {
        const b = c.options.find((o) => o.verdict === "best");
        html += `<div class="fb fb-best"><span class="fb-h">The best answer</span><p>${b.label} — ${b.feedback}</p></div>`;
      }
      feedback.innerHTML = html;
      if (choice.verdict === "best" && !answered.has(i)) best += 1;
      answered.add(i);
      check.remove();
      const next = el("button", { type: "button", class: "btn btn-primary btn-sm" }, i + 1 < ex.cases.length ? "Next case" : "Finish");
      next.addEventListener("click", () => { i += 1; render(); live.scrollIntoView({ block: "nearest" }); (live.querySelector("input, button") || live).focus?.(); });
      actions.appendChild(next);
      next.focus();
    });
    right.append(fs, actions, feedback);
    live.append(el("p", { class: "ex-progress" }, `Case ${i + 1} of ${ex.cases.length}`), el("div", { class: "ex-case" }));
    const grid = live.querySelector(".ex-case");
    grid.append(left, right);
  }
  render();
}

/* ---------- sort: put each real message in the right bucket ---------- */
function buildSort(id, ex, live) {
  function render() {
    live.textContent = "";
    if (ex.shot) live.appendChild(shotButton(ex.shot));
    const rows = [];
    ex.items.forEach((it, n) => {
      const row = el("div", { class: "sort-row" });
      const fs = el("fieldset", {});
      fs.appendChild(el("legend", { class: "sort-text" }, it.text));
      const opts = el("div", { class: "sort-opts" });
      ex.categories.forEach((c) => {
        opts.appendChild(el("label", {}, `<input type="radio" name="ex-${id}-i${n}" value="${c.id}"><span>${escapeHtml(c.label)}<small>${c.hint}</small></span>`));
      });
      fs.appendChild(opts);
      row.appendChild(fs);
      live.appendChild(row);
      rows.push({ row, it, n });
    });
    const out = el("div", { class: "ex-feedback", "aria-live": "polite" });
    const actions = el("div", { class: "ex-actions" });
    const check = el("button", { type: "button", class: "btn btn-primary btn-sm" }, "Check my sorting");
    actions.appendChild(check);
    live.append(actions, out);
    check.addEventListener("click", () => {
      const missing = rows.filter((r) => !r.row.querySelector("input:checked"));
      if (missing.length) { out.innerHTML = `<div class="fb fb-ok"><span class="fb-h">Not finished</span><p>Choose a bucket for every line first (${missing.length} left).</p></div>`; return; }
      let score = 0;
      rows.forEach(({ row, it }) => {
        const chosen = row.querySelector("input:checked").value;
        const ok = chosen === it.answer;
        if (ok) score += 1;
        row.querySelectorAll("input").forEach((x) => { x.disabled = true; });
        const cat = ex.categories.find((c) => c.id === it.answer);
        row.querySelector(".fb")?.remove();
        row.appendChild(el("div", { class: `fb fb-${ok ? "best" : "wrong"}` }, `<span class="fb-h">${ok ? "Right" : `Not quite — this one is “${escapeHtml(cat.label)}”`}</span><p>${it.feedback}</p>`));
      });
      out.innerHTML = `<p class="score">${score} of ${rows.length} sorted correctly.</p>`;
      check.remove();
      const again = el("button", { type: "button", class: "btn btn-sm" }, "Try again");
      again.addEventListener("click", render);
      actions.appendChild(again);
      again.focus();
    });
  }
  render();
}

/* ---------- multi: tick everything that is true ---------- */
function buildMulti(id, ex, live) {
  function render() {
    live.textContent = "";
    if (ex.shot) live.appendChild(shotButton(ex.shot));
    const fs = el("fieldset", { class: "ex-q" });
    fs.appendChild(el("legend", {}, "Tick everything Studio did."));
    ex.items.forEach((it, n) => fs.appendChild(el("label", { class: "opt" }, `<input type="checkbox" name="ex-${id}" value="${n}"><span>${it.text}</span>`)));
    const out = el("div", { class: "ex-feedback", "aria-live": "polite" });
    const actions = el("div", { class: "ex-actions" });
    const check = el("button", { type: "button", class: "btn btn-primary btn-sm" }, "Check my answers");
    actions.appendChild(check);
    live.append(fs, actions, out);
    check.addEventListener("click", () => {
      let score = 0;
      const boxes = [...fs.querySelectorAll("input")];
      const labels = [...fs.querySelectorAll(".opt")];
      let html = "";
      boxes.forEach((b, n) => {
        const it = ex.items[n];
        const ok = b.checked === it.answer;
        if (ok) score += 1;
        b.disabled = true;
        labels[n].classList.add(ok ? "is-correct" : "is-wrong");
        html += `<div class="fb fb-${it.answer ? "yes" : "no"}"><span class="fb-h">${it.answer ? "Studio does this" : "Studio does not do this"}${ok ? "" : b.checked ? " — you ticked it" : " — you missed it"}</span><p>${it.feedback}</p></div>`;
      });
      out.innerHTML = `<p class="score">${score} of ${boxes.length} right.</p>${html}`;
      check.remove();
      const again = el("button", { type: "button", class: "btn btn-sm" }, "Try again");
      again.addEventListener("click", render);
      actions.appendChild(again);
    });
  }
  render();
}

export function initExamples(root = document) {
  for (const node of root.querySelectorAll(".example[data-example]")) {
    if (node.dataset.ready) continue;
    node.dataset.ready = "1";
    const id = node.dataset.example;
    const ex = DATA.examples[id];
    if (!ex) continue;
    const live = $(".ex-live", node);
    live.hidden = false;
    if (ex.type === "choose") buildChoose(id, ex, live);
    else if (ex.type === "sort") buildSort(id, ex, live);
    else if (ex.type === "multi") buildMulti(id, ex, live);
  }
}
