#!/usr/bin/env node
// Static checks on the built guide: links, assets, accessibility basics, privacy and no third-party requests.
//   node tools/check.mjs            offline checks
//   node tools/check.mjs --online   additionally confirms every external link answers (needs the network)
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const guideContent = JSON.parse(readFileSync(join(root, "content/guide.json"), "utf8"));
const tauriPath = process.env.SNAPSTUDIO_TAURI_CONF || join(root, "..", "..", "desktop/src-tauri/tauri.conf.json");
const tauri = JSON.parse(readFileSync(tauriPath, "utf8"));
const pub = join(root, "public");
const html = readFileSync(join(pub, "index.html"), "utf8");
const css = readFileSync(join(pub, "assets/guide.css"), "utf8");
const js = readdirSync(join(pub, "assets")).filter((f) => f.endsWith(".js")).map((f) => readFileSync(join(pub, "assets", f), "utf8")).join(String.fromCharCode(10));
const online = process.argv.includes("--online");
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${!ok && detail ? "  — " + detail : ""}`); };
check("built HTML states the guide version", html.includes(`Checked against Snapmaker Studio v${guideContent.site.version}.`), `v${guideContent.site.version}`);

/* ids and in-page links */
const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]);
const dupes = ids.filter((v, i) => ids.indexOf(v) !== i);
check("every id is unique", dupes.length === 0, [...new Set(dupes)].join(", "));
const anchors = [...html.matchAll(/href="#([^"]*)"/g)].map((m) => m[1]).filter(Boolean);
const missing = [...new Set(anchors.filter((a) => !ids.includes(a)))];
check("every in-page link points at something", missing.length === 0, missing.join(", "));

/* images */
const imgs = [...html.matchAll(/<img\b[^>]*>/g)].map((m) => m[0]);
const noAlt = imgs.filter((t) => !/\salt="[^"]+"/.test(t) && !/\salt=""/.test(t));
check("every image has an alt attribute", noAlt.length === 0);
const decorativeOnly = imgs.filter((t) => /\salt=""/.test(t) && !/mark-color|brand\//.test(t));
check("only the brand mark is marked decorative", decorativeOnly.length === 0);
const srcs = [...new Set(imgs.map((t) => /src="([^"]+)"/.exec(t)?.[1]).filter(Boolean))];
const absent = srcs.filter((s) => !existsSync(join(pub, s)));
check("every image file exists", absent.length === 0, absent.join(", "));
const used = new Set(srcs.map((s) => s.replace(/^assets\/img\//, "")));
const unused = readdirSync(join(pub, "assets/img")).filter((f) => f.endsWith(".png") && !used.has(f));
check("no screenshot is left unused", unused.length === 0, unused.join(", "));
const bigAlt = imgs.filter((t) => (/\salt="([^"]*)"/.exec(t)?.[1] || "").length > 0 && (/\salt="([^"]*)"/.exec(t)[1].length > 0)).length;
check("screenshots carry descriptive alt text (25+ characters)", imgs.filter((t) => /assets\/img\//.test(t)).every((t) => (/\salt="([^"]*)"/.exec(t)?.[1] || "").length >= 25));
check("every image declares its size (no layout shift)", imgs.every((t) => /\swidth="\d+"/.test(t) && /\sheight="\d+"/.test(t)));

/* no third-party requests */
const refs = [...html.matchAll(/<(?:script|link|img|iframe|source)\b[^>]*?(?:src|href)="(https?:[^"]+)"/g)].map((m) => m[1]);
const thirdParty = refs.filter((u) => !/^https:\/\/github\.com\//.test(u));
check("no script, stylesheet, font or image comes from another site", refs.filter((u) => /\.(js|css|woff2?|png|jpe?g|svg)(\?|$)/.test(u)).length === 0 && thirdParty.length === 0, thirdParty.join(", "));
check("no external URL in the stylesheet or script", !/https?:\/\//.test(css.replace(/\/\*[\s\S]*?\*\//g, "")) && !/\bfetch\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource/.test(js));
check("page loads two small local scripts and one local stylesheet", (html.match(/<script\b[^>]*\bsrc="assets\//g) || []).length === 2 && (html.match(/<link\b[^>]*rel="stylesheet"/g) || []).length === 1);
check("no inline script or inline style, so a strict Content-Security-Policy works", !/<script(?![^>]*\bsrc=)(?![^>]*type="application\/json")[^>]*>/.test(html) && !/\sstyle="/.test(html));

/* external links */
const external = [...new Set([...html.matchAll(/href="(https?:[^"]+)"/g)].map((m) => m[1]))];
const allowed = [/^https:\/\/github\.com\/DVOpenLabs\/snapmaker-studio(\/|$)/, /^https:\/\/github\.com\/Snapmaker\/OrcaSlicer\/releases$/];
const odd = external.filter((u) => !allowed.some((re) => re.test(u)));
check("external links go only to the Studio repository and Snapmaker Orca's releases", odd.length === 0, odd.join(", "));
check("external links open safely (noopener noreferrer)", [...html.matchAll(/<a\b[^>]*target="_blank"[^>]*>/g)].every((m) => /rel="noopener noreferrer"/.test(m[0])));
if (online) {
  let bad = [];
  for (const u of external) {
    try { const r = await fetch(u, { method: "HEAD", redirect: "follow" }); if (r.status >= 400) bad.push(`${u} → ${r.status}`); } catch (e) { bad.push(`${u} → ${e.message}`); }
  }
  check(`all ${external.length} external links answer`, bad.length === 0, bad.join("; "));
}

/* structure */
check("one main landmark and a skip link", /<main\b/.test(html) && /class="skip"/.test(html));
check("page language declared", /<html lang="en"/.test(html));
check("exactly one h1", (html.match(/<h1\b/g) || []).length === 1);
check("the dialog has an accessible name", /<dialog[^>]*aria-labelledby="viewer-title"/.test(html));
check("buttons that open images say so", /Enlarge screenshot: /.test(js));
check("independent-project statement is on the page", /not affiliated with or endorsed by Snapmaker/.test(html));
const versionsMatch = guideContent.site.version === tauri.version;
if (versionsMatch) check("guide and desktop versions match", true);
else console.warn(`WARNING  guide and desktop versions differ: ${guideContent.site.version} vs ${tauri.version}`);

/* CSS: focus, motion, forced colours */
check("visible focus styles exist", /:focus-visible/.test(css));
check("reduced-motion preference is honoured", /prefers-reduced-motion: reduce/.test(css));
check("forced-colours mode is considered", /forced-colors: active/.test(css));
check("light and dark themes both defined", /data-theme="dark"/.test(css) && /data-theme="light"/.test(css));

/* contrast of the colour tokens (WCAG 2.x) */
function parseTokens(block) {
  const out = {};
  for (const m of block.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b/g)) out[m[1]] = m[2];
  return out;
}
const dark = parseTokens(css.slice(css.indexOf(":root,"), css.indexOf(':root[data-theme="light"]')));
const light = parseTokens(css.slice(css.indexOf(':root[data-theme="light"]'), css.indexOf("*, *::before")));
const lum = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
for (const [label, t] of [["dark", dark], ["light", light]]) {
  const pairs = [
    ["text on page", t.text, t.bg, 4.5], ["text on panel", t.text, t.panel, 4.5], ["muted text on page", t.muted, t.bg, 4.5],
    ["muted text on panel", t.muted, t.panel, 4.5], ["muted text on soft panel", t.muted, t["panel-2"], 4.5],
    ["link on page", t.accent, t.bg, 4.5], ["link on panel", t.accent, t.panel, 4.5], ["button text on accent", t["accent-ink"], t.accent, 4.5],
    ["ready on panel", t.ready, t.panel, 4.5], ["warning on panel", t.warn, t.panel, 4.5], ["limit on panel", t.risk, t.panel, 4.5],
    ["border against page (UI component)", t.border, t.bg, 1.3],
  ];
  for (const [name, fg, bg, min] of pairs) {
    if (!fg || !bg) { check(`${label} contrast: ${name}`, false, "token missing"); continue; }
    const r = ratio(fg, bg);
    check(`${label} contrast: ${name} (${r.toFixed(1)}:1, needs ${min}:1)`, r >= min);
  }
}

const failed = results.filter((r) => !r).length;
console.log(`${results.length - failed}/${results.length} static checks passed`);
process.exit(failed ? 1 : 0);
