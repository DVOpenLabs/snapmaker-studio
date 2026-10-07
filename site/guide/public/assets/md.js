// Tiny inline-markup renderer shared by the build (Node) and the page (browser).
// Supports exactly what lesson text needs: **UI label**, `code`, *emphasis*, [text](url) and [text](@link-key).
// Everything else is escaped, so lesson data can never inject markup.

export function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** @param {string} text  @param {(key:string)=>string|undefined} [resolve] maps @key links to URLs */
export function inline(text, resolve = () => undefined) {
  const out = [];
  let rest = String(text);
  const rules = [
    { re: /^\*\*([^*]+)\*\*/, html: (m) => `<strong class="ui">${esc(m[1])}</strong>` },
    { re: /^`([^`]+)`/, html: (m) => `<code>${esc(m[1])}</code>` },
    {
      re: /^\[([^\]]+)\]\(([^)]+)\)/,
      html: (m) => {
        const raw = m[2];
        const url = raw.startsWith("@") ? resolve(raw.slice(1)) : raw;
        if (!url) throw new Error(`Unknown link key "${raw}" in: ${text}`);
        const external = /^https?:/.test(url);
        return `<a href="${esc(url)}"${external ? ' rel="noopener noreferrer" target="_blank"' : ""}>${esc(m[1])}${external ? '<span class="vh"> (opens in a new tab)</span>' : ""}</a>`;
      },
    },
    { re: /^\*([^*]+)\*/, html: (m) => `<em>${esc(m[1])}</em>` },
  ];
  while (rest.length) {
    let hit = false;
    for (const r of rules) {
      const m = r.re.exec(rest);
      if (m) { out.push(r.html(m)); rest = rest.slice(m[0].length); hit = true; break; }
    }
    if (hit) continue;
    const next = rest.slice(1).search(/[*`[]/);
    const cut = next === -1 ? rest.length : next + 1;
    out.push(esc(rest.slice(0, cut)));
    rest = rest.slice(cut);
  }
  return out.join("");
}

/** Plain text of an inline string (for aria-labels, alt text checks). */
export function plain(text) {
  return String(text).replace(/\*\*([^*]+)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1").replace(/\*([^*]+)\*/g, "$1").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
}
