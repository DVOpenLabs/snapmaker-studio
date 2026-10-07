// Snapmaker Studio user guide — client enhancement.
// The page is complete without this file (every lesson is pre-rendered as plain HTML). This adds: one lesson at a
// time, stable hash links, saved tour position, progress, screenshot viewer, hotspots and the example walkthroughs.
// Nothing here makes a network request. Walkthroughs only move between pictures; they never touch hardware.

const store = {
  get(k) { try { return window.localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { window.localStorage.setItem(k, v); } catch { /* storage blocked: the guide still works */ } },
  del(k) { try { window.localStorage.removeItem(k); } catch { /* ignore */ } },
};

const DATA = JSON.parse(document.getElementById("guide-data").textContent);
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const lessons = $$(".lesson");
const slugs = lessons.map((el) => el.id);
const total = lessons.length;
const POS_KEY = "sg.position";
const THEME_KEY = "sg.theme";

/* ---------- theme ---------- */
const root = document.documentElement;
const themeBtn = $("#theme-btn");
function setTheme(t, persist) {
  root.dataset.theme = t;
  if (persist) store.set(THEME_KEY, t);
  if (themeBtn) {
    themeBtn.setAttribute("aria-label", t === "dark" ? "Switch to the light theme" : "Switch to the dark theme");
    themeBtn.querySelector(".label").textContent = t === "dark" ? "Light theme" : "Dark theme";
  }
}
setTheme(root.dataset.theme === "light" ? "light" : "dark", false);
themeBtn?.addEventListener("click", () => setTheme(root.dataset.theme === "dark" ? "light" : "dark", true));

/* ---------- hotspots (shared by figures, viewer and demos) ---------- */
function geometryFor(shotId) { return DATA.geometry[shotId]; }
function shotMeta(shotId) { return DATA.shots[shotId]; }

function makeHotspot(shotId, spot, opts = {}) {
  const g = geometryFor(shotId)?.hotspots?.[spot.key];
  if (!g) return null;
  const b = document.createElement("button");
  b.type = "button";
  b.className = "hs";
  b.textContent = String(spot.n);
  b.style.left = `${Math.min(97, Math.max(3, g.x))}%`;
  b.style.top = `${Math.min(97, Math.max(3, g.y))}%`;
  b.dataset.key = spot.key;
  b.setAttribute("aria-label", `${spot.n}. ${spot.title}`);
  if (!opts.demo) b.setAttribute("aria-pressed", "false");
  return b;
}
function makeBox(shotId, spot) {
  const g = geometryFor(shotId)?.hotspots?.[spot.key];
  const box = document.createElement("span");
  box.className = "hs-box";
  box.dataset.key = spot.key;
  if (g) Object.assign(box.style, { left: `${g.x}%`, top: `${g.y}%`, width: `${g.w}%`, height: `${g.h}%` });
  return box;
}

function mountHotspots(frame, shotId, callout) {
  const meta = shotMeta(shotId);
  if (!meta || !meta.hotspots?.length) return;
  const boxes = {};
  const buttons = [];
  for (const spot of meta.hotspots) {
    const box = makeBox(shotId, spot);
    frame.appendChild(box);
    boxes[spot.key] = box;
  }
  for (const spot of meta.hotspots) {
    const b = makeHotspot(shotId, spot);
    if (!b) continue;
    buttons.push(b);
    b.addEventListener("click", () => {
      const on = b.getAttribute("aria-pressed") !== "true";
      buttons.forEach((x) => x.setAttribute("aria-pressed", "false"));
      Object.values(boxes).forEach((x) => x.classList.remove("on"));
      if (on) {
        b.setAttribute("aria-pressed", "true");
        boxes[spot.key].classList.add("on");
        callout.innerHTML = `<b>${spot.n}. ${escapeHtml(spot.title)}</b> — ${spot.html}`;
      } else {
        callout.textContent = "Select a numbered circle to see what that part of the screen does.";
      }
    });
    frame.appendChild(b);
  }
}
function escapeHtml(s) { return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function enhanceFigures() {
  for (const fig of $$("figure.shot")) {
    const shotId = fig.dataset.shot;
    const frame = $(".shot-frame", fig);
    const img = $("img", frame);
    const compact = fig.classList.contains("compact");   // small thumbnails: numbered circles would crowd, so they appear in the enlarged view
    const callout = document.createElement("div");
    callout.className = "hs-callout js-only";
    callout.setAttribute("aria-live", "polite");
    callout.textContent = "Select a numbered circle to see what that part of the screen does.";
    // The picture itself opens the viewer; the circles sit on top of it as separate buttons.
    const openBtn = document.createElement("button");
    openBtn.type = "button";
    openBtn.className = "shot-open";
    openBtn.setAttribute("aria-label", `Enlarge screenshot: ${img.alt}`);
    img.replaceWith(openBtn);
    openBtn.appendChild(img);
    if (!compact) mountHotspots(frame, shotId, callout);
    const tools = document.createElement("div");
    tools.className = "shot-tools js-only";
    const enlarge = document.createElement("button");
    enlarge.type = "button";
    enlarge.className = "btn btn-sm";
    enlarge.textContent = "Enlarge screenshot";
    tools.appendChild(enlarge);
    fig.appendChild(tools);
    if (!compact) fig.appendChild(callout);
    const open = (ev) => openViewer(shotId, ev.currentTarget);
    openBtn.addEventListener("click", open);
    enlarge.addEventListener("click", open);
  }
}

/* ---------- viewer dialog ---------- */
const dlg = $("#viewer");
let lastFocus = null;
function openViewer(shotId, opener) {
  const meta = shotMeta(shotId);
  lastFocus = opener || document.activeElement;
  $("#viewer-title").textContent = meta.title;
  const body = $("#viewer-body");
  body.textContent = "";
  const frame = document.createElement("div");
  frame.className = "shot-frame";
  const img = document.createElement("img");
  img.src = meta.src;
  img.alt = meta.alt;
  img.width = meta.width;
  img.height = meta.height;
  frame.appendChild(img);
  const callout = document.createElement("div");
  callout.className = "hs-callout";
  callout.setAttribute("aria-live", "polite");
  callout.textContent = "Select a numbered circle to see what that part of the screen does.";
  mountHotspots(frame, shotId, callout);
  const cap = document.createElement("p");
  cap.className = "viewer-cap";
  cap.textContent = meta.caption;
  body.append(frame, callout, cap);
  dlg.showModal();
  $("#viewer-close").focus();
}
function closeViewer() { if (dlg.open) dlg.close(); }
$("#viewer-close")?.addEventListener("click", closeViewer);
dlg?.addEventListener("click", (e) => { if (e.target === dlg) closeViewer(); });
dlg?.addEventListener("close", () => { if (lastFocus && document.contains(lastFocus)) lastFocus.focus(); lastFocus = null; });

/* ---------- example walkthroughs ---------- */
function enhanceDemos() {
  for (const el of $$(".demo")) {
    const demo = DATA.demos[el.dataset.demo];
    if (!demo) continue;
    const stageWrap = $(".demo-stage-slot", el);
    const panel = $(".demo-panel", el);
    const static_ = $(".demo-static", el);
    static_?.setAttribute("hidden", "");
    $(".swipe-hint", el)?.removeAttribute("hidden");
    stageWrap.removeAttribute("hidden");
    panel.removeAttribute("hidden");
    const stage = document.createElement("div");
    stage.className = "demo-stage";
    const img = document.createElement("img");
    stage.appendChild(img);
    stageWrap.textContent = "";
    stageWrap.appendChild(stage);
    const say = $(".demo-say", panel);
    const list = $(".demo-steps", panel);
    const nextBtn = $(".demo-next", panel);
    const resetBtn = $(".demo-reset", panel);
    let i = 0;
    let acted = false;
    const done = new Set();

    const items = demo.steps.map((s, idx) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="b">${idx + 1}</span><span>${s.instructionHtml}</span>`;
      list.appendChild(li);
      return li;
    });

    function render() {
      const step = demo.steps[i];
      const meta = shotMeta(step.shot);
      img.src = meta.src; img.alt = `${meta.alt} (example walkthrough, step ${i + 1} of ${demo.steps.length})`;
      img.width = meta.width; img.height = meta.height;
      $$(".hs, .hs-box", stage).forEach((n) => n.remove());
      const spots = meta.hotspots || [];
      for (const spot of spots) {
        const b = makeHotspot(step.shot, spot, { demo: true });
        if (!b) continue;
        const isCurrent = spot.key === step.hotspot;
        b.classList.add(isCurrent ? (acted ? "done" : "next") : "idle");
        if (isCurrent) b.setAttribute("aria-label", `${spot.n}. ${spot.title} — click this to do step ${i + 1}`);
        b.addEventListener("click", () => {
          if (!isCurrent) { say.innerHTML = `<span class="k">Not this one</span>This example is on step ${i + 1}: ${step.instructionHtml}`; return; }
          acted = true; done.add(i);
          say.innerHTML = `<span class="k">What you would see</span>${step.resultHtml}`;
          render();
        });
        stage.appendChild(b);
      }
      items.forEach((li, idx) => {
        li.className = done.has(idx) ? "done" : idx === i ? "now" : "";
        li.querySelector(".b").textContent = done.has(idx) ? "✓" : String(idx + 1);
      });
      if (!acted) say.innerHTML = `<span class="k">Step ${i + 1} of ${demo.steps.length}</span>${step.instructionHtml}`;
      nextBtn.disabled = !(acted && i < demo.steps.length - 1);
      nextBtn.textContent = i < demo.steps.length - 1 ? "Next step" : "End of example";
      if (acted && i === demo.steps.length - 1) say.insertAdjacentHTML("beforeend", `<br><br><strong>That is the end of this example.</strong> Nothing was sent anywhere.`);
    }
    nextBtn.addEventListener("click", () => { if (i < demo.steps.length - 1) { i += 1; acted = false; render(); stage.querySelector(".hs.next")?.focus(); } });
    resetBtn.addEventListener("click", () => { i = 0; acted = false; done.clear(); render(); });
    el._reset = () => resetBtn.click();
    render();
  }
}

/* ---------- lessons, progress, routing ---------- */
const tocLinks = $$(".toc a[data-lesson]");
const countEl = $("#tour-count");
const subEl = $("#tour-sub");
const segs = $$("#tour-segs li");
const startBtn = $("#start-tour");
const startLabel = $("#start-label");
const prevBtns = $$(".js-prev");
const nextBtns = $$(".js-next");
let current = -1;

function indexFromHash() {
  const slug = decodeURIComponent(location.hash.replace(/^#/, ""));
  return slugs.indexOf(slug);
}
function activate(i, { focus = false, scroll = false } = {}) {
  if (i < 0 || i >= total) i = 0;
  current = i;
  lessons.forEach((el, k) => el.classList.toggle("is-active", k === i));
  tocLinks.forEach((a, k) => { if (k === i) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  countEl.textContent = `Lesson ${i + 1} of ${total}`;
  subEl.textContent = `Tour position: ${DATA.lessons[i].short}`;
  segs.forEach((s, k) => { s.className = k < i ? "on" : k === i ? "here" : ""; });
  document.title = `Lesson ${i + 1}: ${DATA.lessons[i].title} — Snapmaker Studio guide`;
  store.set(POS_KEY, slugs[i]);
  for (const b of prevBtns) b.hidden = i === 0;
  for (const b of nextBtns) b.hidden = i === total - 1;
  if (startLabel) startLabel.textContent = i === 0 && !store.get("sg.started") ? "Start the tour →" : `Continue — lesson ${i + 1}`;
  if (scroll) lessons[i].scrollIntoView({ block: "start" });
  if (focus) $("h2.title", lessons[i]).focus({ preventScroll: true });
  $(".toc")?.classList.remove("open");
  $("#menu-btn")?.setAttribute("aria-expanded", "false");
}
function goTo(i, opts) {
  const slug = slugs[i];
  if (location.hash === `#${slug}`) activate(i, opts); else { pendingOpts = opts; location.hash = slug; }
}
let pendingOpts = null;
window.addEventListener("hashchange", () => {
  const i = indexFromHash();
  if (i >= 0) { activate(i, pendingOpts || { scroll: true }); pendingOpts = null; }
});
for (const b of prevBtns) b.addEventListener("click", (e) => { e.preventDefault(); goTo(current - 1, { scroll: true, focus: true }); });
for (const b of nextBtns) b.addEventListener("click", (e) => { e.preventDefault(); goTo(current + 1, { scroll: true, focus: true }); });
startBtn?.addEventListener("click", (e) => {
  e.preventDefault();
  store.set("sg.started", "1");
  const saved = slugs.indexOf(store.get(POS_KEY));
  goTo(saved >= 0 ? saved : 0, { scroll: true, focus: true });
});
$("#start-again")?.addEventListener("click", () => {
  store.del(POS_KEY); store.del("sg.started");
  $$(".demo").forEach((d) => d._reset?.());
  goTo(0, { scroll: true, focus: true });
  if (startLabel) startLabel.textContent = "Start the tour →";
});
$("#menu-btn")?.addEventListener("click", (e) => {
  const open = !$(".toc").classList.contains("open");
  $(".toc").classList.toggle("open", open);
  e.currentTarget.setAttribute("aria-expanded", String(open));
});
tocLinks.forEach((a, k) => a.addEventListener("click", (e) => {
  if (location.hash === a.getAttribute("href")) { e.preventDefault(); activate(k, { scroll: true, focus: true }); }
  else pendingOpts = { scroll: true, focus: true };
}));

enhanceFigures();
enhanceDemos();
const fromHash = indexFromHash();
const saved = slugs.indexOf(store.get(POS_KEY));
activate(fromHash >= 0 ? fromHash : saved >= 0 ? saved : 0, { scroll: fromHash >= 0 && location.hash.length > 1 });
if (fromHash < 0 && saved >= 0 && startLabel) startLabel.textContent = `Continue — lesson ${saved + 1}`;
document.body.classList.add("ready");
