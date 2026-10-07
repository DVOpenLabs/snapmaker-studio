// Shared helpers. Nothing here makes a network request.
export const DATA = JSON.parse(document.getElementById("guide-data").textContent);
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export const store = {
  get(k) { try { return window.localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { window.localStorage.setItem(k, v); } catch { /* storage blocked: the guide still works */ } },
  del(k) { try { window.localStorage.removeItem(k); } catch { /* ignore */ } },
};

export function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

export function el(tag, attrs = {}, html) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "class") node.className = v; else node.setAttribute(k, v === true ? "" : String(v));
  }
  if (html !== undefined) node.innerHTML = html;
  return node;
}
