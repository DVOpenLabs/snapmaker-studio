import { join } from "node:path";
import { start, stage, launch, loopbackOnly, cleanup, sleep, OUT_DIR, FIXTURES, REPO } from "./harness.mjs";
const { handshake, UI } = await start();
const offbed = stage("demo_offplate_foreign.3mf", FIXTURES);
const browser = await launch();
const out = [];
try {
  for (const noWebgl of [false, true]) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 }, serviceWorkers: "block" });
    await ctx.addInitScript((nw) => { localStorage.setItem("theme", "dark"); localStorage.setItem("mode", "advanced");
      if (nw) { const o = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function (t, ...a) { return /webgl/.test(String(t)) ? null : o.call(this, t, ...a); }; } }, noWebgl);
    loopbackOnly(ctx, handshake.port, []);
    const page = await ctx.newPage();
    await page.goto(`${UI}/?api=${handshake.port}:${handshake.token}&file=${encodeURIComponent(offbed)}`);
    await page.locator("#brand-splash").waitFor({ state: "detached" });
    const cdp = await ctx.newCDPSession(page); await cdp.send("Performance.enable");
    const heap = async () => { await cdp.send("HeapProfiler.collectGarbage"); await cdp.send("HeapProfiler.collectGarbage"); const m = await cdp.send("Performance.getMetrics"); return m.metrics.find((x) => x.name === "JSHeapUsedSize").value; };
    await page.getByRole("button", { name: /Open a model/ }).first().click();
    const ready = () => page.waitForFunction(() => { const p = document.querySelector('[data-testid="project-scene"]'); return p && /Retry 3D view|Try again/.test(p.textContent || "") || ([...(p?.querySelectorAll("button") ?? [])].find((b) => b.textContent === "Top") || {}).disabled === false; }, null, { timeout: 30000 });
    await ready();
    const nav = (p) => page.evaluate((to) => { history.pushState({}, "", to); window.dispatchEvent(new PopStateEvent("popstate")); }, p);
    for (let i = 0; i < 10; i++) { await nav("/help"); await sleep(30); await nav("/workspace"); await ready(); }
    await sleep(500); const h0 = await heap();
    for (let i = 0; i < 40; i++) { await nav("/help"); await sleep(30); await nav("/workspace"); await ready(); }
    await sleep(500); const h1 = await heap();
    out.push({ noWebgl, cycles: 40, bytesPerCycle: Math.round((h1 - h0) / 40) });
    await ctx.close();
  }
} finally { await browser.close(); cleanup(); }
console.log(JSON.stringify(out));
