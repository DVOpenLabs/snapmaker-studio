// Entry point. The page is complete HTML without this script; with it, the guide shows one page at a time, routes by
// hash (so every link, including the old lesson links, keeps working) and adds search, filters and the examples.
import { DATA, $, $$, store, el } from "./common.js";
import { initFigures } from "./figures.js";
import { initExamples } from "./examples.js";
import { renderSearch } from "./search.js";

const root = document.documentElement;
const pages = new Map($$("article.page").map((p) => [p.dataset.page, p]));
const qInput = $("#q");
const SITE = "Snapmaker Studio guide";
let current = null;
let booted = false;

/* ---------- theme ---------- */
const themeBtn = $("#theme-btn");
function paintTheme() {
  const dark = root.dataset.theme !== "light";
  themeBtn.setAttribute("aria-label", dark ? "Switch to the light theme" : "Switch to the dark theme");
  $(".label", themeBtn).textContent = dark ? "Light theme" : "Dark theme";
}
themeBtn?.addEventListener("click", () => {
  const next = root.dataset.theme === "light" ? "dark" : "light";
  root.dataset.theme = next;
  store.set("sg.theme", next);
  paintTheme();
});
paintTheme();

/* ---------- routing ---------- */
function parseHash() {
  let h = decodeURIComponent(location.hash.replace(/^#/, ""));
  if (!h || h === "top") return { page: "home" };
  if (h.startsWith("search:") || h === "search") return { page: "search", query: h.slice(7) };
  if (DATA.redirects[h]) return { page: DATA.redirects[h], redirected: h };
  if (pages.has(h)) return { page: h };
  const target = document.getElementById(h);
  const host = target?.closest("article.page");
  if (host) return { page: host.dataset.page, section: h };
  if (target) return { page: current?.dataset.page || "home", section: h };
  const base = h.split("--")[0];
  if (pages.has(base)) return { page: base };
  return { page: "home", missing: h };
}

function navState(page) {
  const type = pages.get(page)?.dataset.type;
  let key = "";
  if (type === "stage") key = "path";
  else if (page === "setup") key = "setup";
  else if (type === "task" || page === "tasks") key = "tasks";
  else if (type === "problem" || page === "problems") key = "problems";
  for (const a of $$("[data-nav]")) {
    if (a.dataset.nav === key) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
}

function show({ page, query, section, redirected }, { moveFocus }) {
  const node = pages.get(page) || pages.get("home");
  if (current && current !== node) current.classList.remove("is-active");
  node.classList.add("is-active");
  const changed = current !== node;
  current = node;
  if (page === "search") {
    if (qInput) qInput.value = query || "";
    renderSearch($("#search-out"), query || "");
    document.title = `${query ? `Search: ${query}` : "Search"} — ${SITE}`;
  } else {
    document.title = `${DATA.titles[page] || "Guide"} — ${SITE}`;
  }
  navState(page);
  if (page !== "search" && qInput && document.activeElement !== qInput) qInput.value = "";
  if (redirected) history.replaceState(null, "", `#${page}`);
  if (node.dataset.type === "stage") store.set("sg.last", page);
  if (page === "home") paintContinue();
  const target = section ? document.getElementById(section) : null;
  if (target) {
    target.scrollIntoView({ block: "start" });
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    if (moveFocus) target.focus({ preventScroll: true });
  } else if (changed || moveFocus) {
    window.scrollTo(0, 0);
    if (moveFocus) $(".ptitle", node)?.focus({ preventScroll: true });
  }
}

function route() {
  show(parseHash(), { moveFocus: booted });
  booted = true;
}
addEventListener("hashchange", route);

/* ---------- "continue the example" on the home page ---------- */
function paintContinue() {
  const home = pages.get("home");
  $(".continue", home)?.remove();
  const last = store.get("sg.last");
  if (!last || !pages.has(last) || !DATA.titles[last]) return;
  const box = el("p", { class: "continue" }, `Continue where you left off: <a href="#${last}">${DATA.titles[last].replace(/</g, "&lt;")}</a>`);
  $(".home-head .lead", home)?.after(box);
}

/* ---------- search ---------- */
$("#search-form")?.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = qInput.value.trim();
  const next = q ? `#search:${encodeURIComponent(q)}` : "#search";
  if (location.hash === next) route(); else location.hash = next;
});
qInput?.addEventListener("input", () => {
  if (current?.dataset.page !== "search") return;
  const q = qInput.value;
  renderSearch($("#search-out"), q);
  history.replaceState(null, "", q.trim() ? `#search:${encodeURIComponent(q.trim())}` : "#search");
});
addEventListener("keydown", (e) => {
  if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
  const t = e.target;
  if (t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
  e.preventDefault();
  qInput?.focus();
});

/* ---------- filters on the task and warning lists ---------- */
for (const bar of $$(".filters")) {
  const page = bar.closest("article.page");
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-filter]");
    if (!b) return;
    const f = b.dataset.filter;
    for (const x of $$("button", bar)) { const on = x === b; x.classList.toggle("is-on", on); x.setAttribute("aria-pressed", String(on)); }
    for (const g of $$("[data-group]", page)) g.hidden = f !== "all" && g.dataset.group !== f;
  });
}

/* ---------- the home map is folded on phones (its stages stay reachable by opening it) ---------- */
const fold = $(".map-fold");
if (fold && matchMedia("(max-width: 960px)").matches) fold.open = false;

/* ---------- start ---------- */
initFigures(document);
initExamples(document);
route();
