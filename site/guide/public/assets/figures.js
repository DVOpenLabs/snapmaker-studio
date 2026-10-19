// Screenshots: the enlarged viewer and the optional numbered notes on controls.
// Numbered circles explain controls; they are an extra, never the way the guide teaches a decision.
import { DATA, $, $$, escapeHtml, el } from "./common.js";

const dlg = $("#viewer");
let lastFocus = null;
const HINT = "Select a numbered circle to see what that control does.";

function hotspotBox(shotId, spot) {
  const g = DATA.geometry[shotId]?.hotspots?.[spot.key];
  const box = el("span", { class: "hs-box", "data-key": spot.key });
  if (g) Object.assign(box.style, { left: `${g.x}%`, top: `${g.y}%`, width: `${g.w}%`, height: `${g.h}%` });
  return box;
}

/** Puts numbered circles (and a callout) on a screenshot frame. */
export function mountHotspots(frame, shotId, callout) {
  const meta = DATA.shots[shotId];
  if (!meta?.hotspots?.length) return;
  const boxes = {};
  const buttons = [];
  for (const spot of meta.hotspots) {
    const box = hotspotBox(shotId, spot);
    frame.appendChild(box);
    boxes[spot.key] = box;
  }
  for (const spot of meta.hotspots) {
    const g = DATA.geometry[shotId]?.hotspots?.[spot.key];
    if (!g) continue;
    const b = el("button", { type: "button", class: "hs", "aria-pressed": "false", "data-key": spot.key, "aria-label": `${spot.n}. ${spot.title}` }, String(spot.n));
    b.style.left = `${Math.min(97, Math.max(3, g.x))}%`;
    b.style.top = `${Math.min(97, Math.max(3, g.y))}%`;
    buttons.push(b);
    b.addEventListener("click", () => {
      const on = b.getAttribute("aria-pressed") !== "true";
      buttons.forEach((x) => x.setAttribute("aria-pressed", "false"));
      Object.values(boxes).forEach((x) => x.classList.remove("on"));
      if (on) {
        b.setAttribute("aria-pressed", "true");
        boxes[spot.key].classList.add("on");
        callout.innerHTML = `<b>${spot.n}. ${escapeHtml(spot.title)}</b> — ${spot.html}`;
      } else callout.textContent = HINT;
    });
    frame.appendChild(b);
  }
}

export function openViewer(shotId, opener) {
  const meta = DATA.shots[shotId];
  if (!meta) return;
  lastFocus = opener || document.activeElement;
  $("#viewer-title").textContent = meta.title;
  const body = $("#viewer-body");
  body.textContent = "";
  const frame = el("div", { class: "shot-frame" });
  frame.appendChild(el("img", { src: meta.src, alt: meta.alt, width: meta.width, height: meta.height }));
  const callout = el("div", { class: "hs-callout", "aria-live": "polite" });
  callout.textContent = meta.hotspots.length ? HINT : "";
  mountHotspots(frame, shotId, callout);
  body.append(frame, ...(meta.hotspots.length ? [callout] : []), el("p", { class: "viewer-cap" }, escapeHtml(meta.caption)));
  dlg.showModal();
  $("#viewer-close").focus();
}
$("#viewer-close")?.addEventListener("click", () => dlg.open && dlg.close());
dlg?.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
dlg?.addEventListener("close", () => { if (lastFocus && document.contains(lastFocus)) lastFocus.focus(); lastFocus = null; });

/** Makes every screenshot open the viewer, and wires the "show numbered notes" switch of each evidence block. */
export function initFigures(root = document) {
  for (const fig of $$("figure.shot", root)) {
    if (fig.dataset.ready) continue;
    fig.dataset.ready = "1";
    const frame = $(".shot-frame", fig);
    const img = $("img", frame);
    const open = el("button", { type: "button", class: "shot-open", "aria-label": `Enlarge screenshot: ${img.alt}` });
    img.replaceWith(open);
    open.appendChild(img);
    open.addEventListener("click", () => openViewer(fig.dataset.shot, open));
  }
  for (const section of $$(".evidence", root)) {
    const toggle = $(".toggle-notes", section);
    if (!toggle || toggle.dataset.ready) continue;
    toggle.dataset.ready = "1";
    toggle.addEventListener("click", () => {
      const on = toggle.getAttribute("aria-pressed") !== "true";
      toggle.setAttribute("aria-pressed", String(on));
      toggle.textContent = on ? "Hide numbered notes on the controls" : "Show numbered notes on the controls";
      section.classList.toggle("notes-on", on);
      for (const fig of $$("figure.shot", section)) {
        const frame = $(".shot-frame", fig);
        if (on && !fig.dataset.notes) {
          fig.dataset.notes = "1";
          const callout = el("div", { class: "hs-callout", "aria-live": "polite" });
          callout.textContent = HINT;
          mountHotspots(frame, fig.dataset.shot, callout);
          const cap = $("figcaption", fig);
          cap.after(callout);
        }
        const callout = $(".hs-callout", fig);
        if (callout) callout.hidden = !on;
      }
    });
  }
}
