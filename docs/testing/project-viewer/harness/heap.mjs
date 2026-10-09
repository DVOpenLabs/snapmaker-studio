import { join } from "node:path";
import { start, stage, launch, loopbackOnly, cleanup, sleep, OUT_DIR, FIXTURES, REPO } from "./harness.mjs";
const { handshake, UI } = await start();
const offbed = stage("demo_offplate_foreign.3mf", FIXTURES);
const browser = await launch();
const out = { facadeHeap: [], uiHeap: [] };
try {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 }, serviceWorkers: "block" });
  await ctx.addInitScript(() => { localStorage.setItem("theme", "dark"); localStorage.setItem("mode", "advanced"); });
  loopbackOnly(ctx, handshake.port, []);
  const page = await ctx.newPage();
  await page.goto(`${UI}/help?api=${handshake.port}:${handshake.token}&file=${encodeURIComponent(offbed)}`);
  await page.locator("#brand-splash").waitFor({ state: "detached" });
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Performance.enable");
  const heap = async () => { await cdp.send("HeapProfiler.collectGarbage"); await cdp.send("HeapProfiler.collectGarbage"); const m = await cdp.send("Performance.getMetrics"); return m.metrics.find((x) => x.name === "JSHeapUsedSize").value; };
  await page.evaluate(async () => {
    const [entry, facadeMod, modelMod, fx] = await Promise.all([
      import("/src/vendor/slicerx/entry.ts"), import("/src/components/project-scene/defaultViewport.ts"),
      import("/src/components/project-scene/sceneModel.ts"), import("/src/components/project-scene/sceneFixtures.ts")]);
    const s = fx.scene(); const view = modelMod.buildViewScene(s, modelMod.buildModel(s));
    const ra = () => new Promise((r) => requestAnimationFrame(() => r()));
    window.__cyc = async (n, mode) => {
      for (let i = 0; i < n; i++) {
        const host = document.createElement("div"); host.style.cssText = "position:fixed;left:0;top:0;width:300px;height:200px";
        const canvas = document.createElement("canvas"); host.appendChild(canvas); document.body.appendChild(host);
        if (mode === "facade") { const f = facadeMod.createSceneViewer(canvas, { theme: "dark" }); f.show(view); await ra(); await ra(); f.dispose(); }
        else if (mode === "raw-empty") { const v = entry.createViewport(canvas, { quality: "balanced" }); await ra(); await ra(); v.dispose(); }
        else if (mode === "raw-plate") { const v = entry.createViewport(canvas, { quality: "balanced" }); v.setPlate({ bed: view.bed, objects: view.objects }); await ra(); await ra(); v.dispose(); }
        host.remove();
      }
    };
  });
  for (const mode of ["raw-empty", "raw-plate", "facade"]) {
    await page.evaluate((m) => window.__cyc(10, m), mode); // warm up
    const h0 = await heap();
    await page.evaluate((m) => window.__cyc(40, m), mode); await sleep(300);
    const h1 = await heap();
    out.facadeHeap.push({ mode, cycles: 40, bytesPerCycle: Math.round((h1 - h0) / 40) });
  }
} finally { await browser.close(); cleanup(); }
console.log(JSON.stringify(out));
