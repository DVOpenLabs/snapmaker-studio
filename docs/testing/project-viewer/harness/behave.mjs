// Behavior checks in real Edge with real WebGL: (b)+(d) interactions cannot edit but selection/camera work,
// (e) 50 mount/unmount cycles (facade level and real app panel under StrictMode), memory, bytes unchanged.
import { start, stage, launch, loopbackOnly, cleanup, sleep, sha, OUT_DIR, FIXTURES, REPO } from "./harness.mjs";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
const OUT = OUT_DIR;
mkdirSync(OUT, { recursive: true });
const FX = FIXTURES;
const { handshake, UI } = await start();
const offbed = stage("demo_offplate_foreign.3mf", FX);
const grid = join(FX, "grid-100k.3mf");
const before = { offbed: sha(offbed), grid: sha(grid) };
const browser = await launch();
const violations = [];
const results = { interaction: {}, cycles: {}, uiCycles: {}, memory: {}, large: {} };

const INSTRUMENT = () => {
  const w = (window.__inst = { ctxs: [], listeners: [], canvases: [], liveObs: 0, on: false });
  const origGet = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (t, ...a) {
    const c = origGet.call(this, t, ...a);
    if (c && /webgl/.test(String(t)) && !w.ctxs.includes(c)) w.ctxs.push(c);
    return c;
  };
  const add = EventTarget.prototype.addEventListener, rem = EventTarget.prototype.removeEventListener;
  const capOf = (o) => (typeof o === "boolean" ? o : !!(o && o.capture));
  EventTarget.prototype.addEventListener = function (type, fn, opts) {
    if (w.on && fn) {
      const entry = { t: this, type, fn, cap: capOf(opts) };
      if (this === document || this === window) entry.stack = new Error().stack.split(String.fromCharCode(10)).slice(2, 7).map((x) => x.trim().split("localhost:").join("")).join(" <- ");
      w.listeners.push(entry);
      if (opts && typeof opts === "object" && opts.once) {
        const wrapped = function (...a) { const i = w.listeners.indexOf(entry); if (i >= 0) w.listeners.splice(i, 1); return typeof fn === "function" ? fn.apply(this, a) : fn.handleEvent(...a); };
        entry.wrapped = wrapped;
        return add.call(this, type, wrapped, opts);
      }
    }
    return add.call(this, type, fn, opts);
  };
  EventTarget.prototype.removeEventListener = function (type, fn, opts) {
    const i = w.listeners.findIndex((l) => l.t === this && l.type === type && l.fn === fn && l.cap === capOf(opts));
    const wrapped = i >= 0 ? w.listeners[i].wrapped : undefined;
    if (i >= 0) w.listeners.splice(i, 1);
    return rem.call(this, type, wrapped || fn, opts);
  };
  for (const N of ["ResizeObserver", "IntersectionObserver"]) {
    const O = window[N];
    window[N] = class extends O {
      constructor(...a) { super(...a); if (w.on) w.liveObs++; this.__c = w.on; }
      disconnect() { if (this.__c && !this.__d) { this.__d = true; w.liveObs--; } return super.disconnect(); }
    };
  }
  const ce = document.createElement;
  document.createElement = function (tag, ...a) { const el = ce.call(this, tag, ...a); if (String(tag).toLowerCase() === "canvas") w.canvases.push(el); return el; };
};

async function newPage(path, { instrument = false, theme = "dark", mode = "advanced", width = 1280, height = 1000 } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: theme, serviceWorkers: "block" });
  await ctx.addInitScript(([t, m]) => { localStorage.setItem("theme", t); localStorage.setItem("mode", m); }, [theme, mode]);
  if (instrument) await ctx.addInitScript(INSTRUMENT);
  loopbackOnly(ctx, handshake.port, violations);
  const page = await ctx.newPage();
  page.errors = [];
  page.on("pageerror", (e) => page.errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR|Invalid DOM property/.test(m.text())) page.errors.push(m.text().slice(0, 200)); });
  await page.goto(`${UI}${path}${path.includes("?") ? "&" : "?"}api=${handshake.port}:${handshake.token}&file=${encodeURIComponent(offbed)}`);
  await page.locator("#brand-splash").waitFor({ state: "detached", timeout: 30000 });
  return { ctx, page };
}
const heap = async (cdp) => { await cdp.send("HeapProfiler.collectGarbage"); const m = await cdp.send("Performance.getMetrics"); return m.metrics.find((x) => x.name === "JSHeapUsedSize").value; };

try {
  // ---- (b)+(d): interactions through the facade on the real viewport ----------------------------------------------
  {
    const { ctx, page } = await newPage("/help");
    await page.evaluate(async () => {
      const [entry, facadeMod, modelMod, fx] = await Promise.all([
        import("/src/vendor/slicerx/entry.ts"), import("/src/components/project-scene/defaultViewport.ts"),
        import("/src/components/project-scene/sceneModel.ts"), import("/src/components/project-scene/sceneFixtures.ts"),
      ]);
      const EVENTS = ["pick", "select", "scale", "paintsettings", "paintstroke", "facehover", "probehover", "facepick", "brimadd", "brimremove", "brimselect", "brimmove", "brimwheel", "pathpick", "transform", "rotate", "cutplane", "cutconnector", "push", "sketch", "camera"];
      const t = (window.__t = { events: [], entry, facadeMod, modelMod, fx, EVENTS });
      t.make = (tool) => {
        const host = document.createElement("div");
        host.style.cssText = "position:fixed;left:0;top:0;width:600px;height:450px;z-index:99999;background:#000";
        const canvas = document.createElement("canvas");
        canvas.style.cssText = "display:block;width:100%;height:100%";
        host.appendChild(canvas); document.body.appendChild(host);
        t.host = host;
        const s = fx.scene();
        const model = modelMod.buildModel(s);
        // The adapter's own sequence (create, setTool probe) on the real viewport; the control differs only in the tool.
        const raw = entry.createViewport(canvas, { label: "harness", quality: "balanced" });
        t.raw = raw;
        for (const ev of EVENTS) raw.on(ev, () => t.events.push(ev));
        raw.setTool(tool === "facade" ? "probe" : "select");
        raw.setPlate({ bed: { widthMm: 270, depthMm: 270, heightMm: 270 }, objects: modelMod.buildViewScene(s, model).objects });
        t.raw.view("top", { animate: false });
      };
      t.dispose = () => { try { t.raw.dispose(); } catch {} t.host.remove(); };
      t.signature = () => { const m = {}; for (let y = 10; y < 445; y += 5) for (let x = 10; x < 595; x += 5) { const p = t.raw.pickFace(x, y); if (p && !m[p.objectId]) m[p.objectId] = p.centerBed.map((v) => Math.round(v * 1000) / 1000); } return m; };
      t.hit = () => { for (let y = 20; y < 440; y += 6) for (let x = 20; x < 590; x += 6) { const p = t.raw.pickFace(x, y); if (p) return { x, y }; } return null; };
    });
    const run = async (tool) => {
      await page.evaluate((tl) => { window.__t.events.length = 0; window.__t.make(tl); }, tool);
      await sleep(1500);
      const hit = await page.evaluate(() => window.__t.hit());
      const clip = { x: 0, y: 0, width: 600, height: 450 };
      const sigBefore = await page.evaluate(() => window.__t.signature());
      const settle = async () => { await page.evaluate(() => { window.__t.raw.view("top", { animate: false }); window.__t.raw.setSelection([]); }); await sleep(1200); };
      await settle();
      const A = await page.screenshot({ clip });
      const mouse = page.mouse, kb = page.keyboard;
      const dragFrom = async (button, mods) => {
        for (const m of mods) await kb.down(m);
        await mouse.move(hit.x, hit.y); await mouse.down({ button });
        for (let i = 1; i <= 8; i++) await mouse.move(hit.x + i * 12, hit.y + i * 3);
        await mouse.up({ button });
        for (const m of mods.slice().reverse()) await kb.up(m);
      };
      await mouse.click(hit.x, hit.y); await mouse.click(hit.x, hit.y, { clickCount: 2 });
      for (const button of ["left", "right", "middle"]) for (const mods of [[], ["Shift"], ["Control"], ["Alt"], ["Shift", "Control"], ["Shift", "Alt"]]) await dragFrom(button, mods);
      await kb.down("Space"); await dragFrom("left", []); await kb.up("Space");
      await mouse.move(hit.x, hit.y); await mouse.wheel(0, -300); await mouse.wheel(0, 300);
      await mouse.wheel(0, -200); // plain wheel; modifiers below
      for (const m of ["Control", "Alt", "Shift"]) { await kb.down(m); await mouse.wheel(0, -200); await kb.up(m); }
      await mouse.click(hit.x, hit.y);
      for (const k of ["Delete", "Backspace", "KeyR", "KeyS", "KeyM", "KeyP", "KeyC", "KeyX", "KeyB", "KeyF", "Enter", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Control+KeyZ", "Control+KeyY", "Control+KeyC", "Control+KeyV", "Control+KeyA", "Escape"]) await kb.press(k);
      const events = await page.evaluate(() => [...window.__t.events]);
      await settle();
      const B = await page.screenshot({ clip });
      const sigAfter = await page.evaluate(() => window.__t.signature());
      await page.evaluate(() => window.__t.dispose());
      const counts = events.reduce((m, e) => ((m[e] = (m[e] || 0) + 1), m), {});
      return { hit, events: counts, objectCentersBefore: sigBefore, objectCentersAfter: sigAfter, objectsDidNotMove: JSON.stringify(sigBefore) === JSON.stringify(sigAfter), imagesIdentical: Buffer.compare(A, B) === 0, bytesA: A.length, bytesB: B.length };
    };
    results.interaction.facade = await run("facade");
    results.interaction.control = await run("control");
    results.interaction.errors = page.errors;
    await ctx.close();
  }

  // ---- (e) facade-level cycles on real WebGL -----------------------------------------------------------------------
  {
    const { ctx, page } = await newPage("/help", { instrument: true });
    results.cycles = await page.evaluate(async () => {
      const [entry, facadeMod, modelMod, fx] = await Promise.all([
        import("/src/vendor/slicerx/entry.ts"), import("/src/components/project-scene/defaultViewport.ts"),
        import("/src/components/project-scene/sceneModel.ts"), import("/src/components/project-scene/sceneFixtures.ts"),
      ]);
      const w = window.__inst;
      const s = fx.scene(); const view = modelMod.buildViewScene(s, modelMod.buildModel(s));
      const baseCanvases = document.querySelectorAll("canvas").length;
      const baseListeners = w.listeners.length;
      w.on = true;
      let peakConnected = 0;
      const ra = () => new Promise((r) => requestAnimationFrame(() => r()));
      for (let i = 0; i < 50; i++) {
        const host = document.createElement("div");
        host.style.cssText = "position:fixed;left:0;top:0;width:300px;height:200px";
        const canvas = document.createElement("canvas");
        host.appendChild(canvas); document.body.appendChild(host);
        const f = facadeMod.createSceneViewer(canvas, { theme: i % 2 ? "light" : "dark" });
        f.show(view);
        await ra(); await ra();
        peakConnected = Math.max(peakConnected, document.querySelectorAll("canvas").length);
        f.dispose(); host.remove();
      }
      await new Promise((r) => setTimeout(r, 1500));
      const created = w.ctxs.length, liveCtx = w.ctxs.filter((c) => !c.isContextLost()).length;
      const kind = (t) => (t instanceof HTMLCanvasElement ? "canvas" : t === document ? "document" : t === window ? "window" : t.constructor.name);
      const left = w.listeners.reduce((m, l) => { const k = `${kind(l.t)}:${l.type}`; m[k] = (m[k] || 0) + 1; return m; }, {});
      return {
        cycles: 50, contextsCreated: created, contextsStillLive: liveCtx,
        canvasesConnectedAfter: document.querySelectorAll("canvas").length - baseCanvases,
        canvasesCreatedByViewer: w.canvases.length, detachedCanvasesWithLiveContext: w.canvases.filter((c) => !c.isConnected).length > 0 ? w.ctxs.filter((c) => !c.isContextLost() && !c.canvas.isConnected).length : 0,
        listenersLeftAfter: w.listeners.length - baseListeners, listenersLeftByKind: left, liveObservers: w.liveObs, peakConnectedCanvases: peakConnected,
      };
    });
    results.cycles.errors = page.errors;
    await ctx.close();
  }

  // ---- (e) app-level: the real panel mounted and unmounted 50 times under StrictMode ---------------------------------
  {
    const { ctx, page } = await newPage("/", { instrument: true });
    const cdp = await ctx.newCDPSession(page);
    await cdp.send("Performance.enable");
    await page.getByRole("button", { name: /Open a model/ }).first().click();
    const panel = page.getByTestId("project-scene");
    await panel.waitFor({ timeout: 90000 });
    await page.waitForFunction(() => ([...document.querySelectorAll('[data-testid="project-scene"] button')].find((b) => b.textContent === "Top") || {}).disabled === false, null, { timeout: 90000 });
    await sleep(1500);
    results.memory.panelShownJsHeapBytes = await heap(cdp);
    await page.evaluate(() => { const w = window.__inst; w.on = true; w.base = { listeners: w.listeners.length, canvases: document.querySelectorAll("canvas").length, ctxs: w.ctxs.length }; });
    const nav = (p) => page.evaluate((to) => { history.pushState({}, "", to); window.dispatchEvent(new PopStateEvent("popstate")); }, p);
    const t0 = Date.now();
    const topReady = (to) => page.waitForFunction(() => ([...document.querySelectorAll('[data-testid="project-scene"] button')].find((b) => b.textContent === "Top") || {}).disabled === false, null, { timeout: to });
    for (let i = 0; i < 50; i++) {
      await nav("/help"); await sleep(30); await nav("/workspace");
      try { await topReady(15000); } catch (e) {
        results.uiCycles.stuckAtCycle = i;
        results.uiCycles.stuckPanelText = (await page.getByTestId("project-scene").innerText().catch(() => "no panel")).replace(/s+/g, " ").slice(0, 300);
        results.uiCycles.stuckPageErrors = page.errors.slice(-5);
        break;
      }
    }
    for (let i = 0; i < 25; i++) { await nav("/help"); await sleep(20); await nav("/workspace"); await sleep(90); } // quick: unmount while still loading
    await page.waitForFunction(() => ([...document.querySelectorAll('[data-testid="project-scene"] button')].find((b) => b.textContent === "Top") || {}).disabled === false, null, { timeout: 90000 });
    await sleep(1500);
    results.uiCycles = await page.evaluate(() => {
      const w = window.__inst;
      const live = w.ctxs.filter((c) => !c.isContextLost());
      const kind = (t) => (t instanceof HTMLCanvasElement ? "canvas" : t === document ? "document" : t === window ? "window" : t.constructor.name);
      const tally = (arr) => arr.reduce((m, l) => { const k = `${kind(l.t)}:${l.type}`; m[k] = (m[k] || 0) + 1; return m; }, {});
      const onDetachedCanvas = w.listeners.filter((l) => l.t instanceof HTMLCanvasElement && !l.t.isConnected);
      const left = tally(w.listeners.filter((l) => !(l.t instanceof Node) || l.t.isConnected));
      const docStacks = [...new Set(w.listeners.filter((l) => l.t === document && l.type === "keydown").map((l) => l.stack))];
      return {
        documentKeydownStacks: docStacks,
        listenersOnDetachedCanvases: onDetachedCanvas.length,
        mountsAndUnmounts: 75, ofWhichShownBeforeUnmount: 50, contextsCreatedDuring: w.ctxs.length - w.base.ctxs, contextsLiveAtEnd: live.length,
        liveContextsAttachedToDetachedCanvas: live.filter((c) => !c.canvas.isConnected).length,
        connectedCanvasesAtEnd: document.querySelectorAll("canvas").length, connectedCanvasesBefore: w.base.canvases,
        listenersOnConnectedTargets: Object.values(left).reduce((a, b) => a + b, 0), listenersByKind: left, liveObservers: w.liveObs,
      };
    });
    results.uiCycles.secondsForAllCycles = (Date.now() - t0) / 1000;
    results.uiCycles.panelStillWorks = await page.evaluate(() => ([...document.querySelectorAll('[data-testid="project-scene"] button')].find((b) => b.textContent === "Top") || {}).disabled === false);
    {
      // A real click on the model in the 3D view selects its row in the list (no editing happens).
      const box = await page.locator('[data-testid="scene-host"]').boundingBox();
      const row = page.getByRole("button", { name: /^Object 1/ });
      let found = null;
      for (let y = box.y + 20; y < box.y + box.height - 20 && !found; y += 8)
        for (let x = box.x + box.width * 0.45; x < box.x + box.width - 10 && !found; x += 8) {
          await page.mouse.click(x, y);
          if ((await row.getAttribute("aria-pressed")) === "true") found = { x: Math.round(x - box.x), y: Math.round(y - box.y) };
        }
      results.uiCycles.clickOnModelSelectsRow = found;
      await page.getByTestId("project-scene").screenshot({ path: join(OUT, "wide-dark-picked-by-click.png") });
      // Keyboard: the row button toggles selection with Space/Enter and the camera buttons activate with Enter.
      await row.focus(); await page.keyboard.press("Space");
      results.uiCycles.spaceTogglesRow = (await row.getAttribute("aria-pressed")) === "false";
      await page.getByRole("button", { name: "Top" }).focus(); await page.keyboard.press("Enter");
    }
    results.uiCycles.errors = page.errors;
    await nav("/help"); await sleep(1200);
    results.memory.afterFiftyCyclesPanelUnmountedJsHeapBytes = await heap(cdp);
    await ctx.close();
  }

  // ---- large scene: 100k triangles ---------------------------------------------------------------------------------
  {
    const { ctx, page } = await newPage("/", { instrument: true });
    await page.evaluate((g) => { /* the dev file hook reads ?file=, so reload with the large fixture */ location.search = `?api=${new URLSearchParams(location.search).get("api")}&file=${encodeURIComponent(g)}`; }, grid);
    await page.locator("#brand-splash").waitFor({ state: "detached", timeout: 30000 });
    const cdp = await ctx.newCDPSession(page);
    await cdp.send("Performance.enable");
    const h0 = await heap(cdp);
    const t0 = Date.now();
    await page.getByRole("button", { name: /Open a model/ }).first().click();
    await page.getByTestId("project-scene").waitFor({ timeout: 120000 });
    await page.waitForFunction(() => ([...document.querySelectorAll('[data-testid="project-scene"] button')].find((b) => b.textContent === "Top") || {}).disabled === false, null, { timeout: 120000 });
    results.large.secondsUntilViewerWorking = (Date.now() - t0) / 1000;
    await sleep(2000);
    results.large.jsHeapBeforeBytes = h0; results.large.jsHeapAfterBytes = await heap(cdp);
    results.large.text = (await page.getByTestId("project-scene").innerText()).replace(/\s+/g, " ").slice(0, 200);
    await page.getByTestId("project-scene").screenshot({ path: join(OUT, "large-100k.png") });
    await page.getByRole("button", { name: "Slope view" }).click(); await sleep(1500);
    await page.getByTestId("project-scene").screenshot({ path: join(OUT, "large-100k-slope.png") });
    results.large.errors = page.errors;
    await ctx.close();
  }
} catch (e) { results.harnessError = String(e?.stack ?? e); }
finally { await browser.close(); }
results.originalsUnchanged = { offbed: sha(offbed) === before.offbed, grid: sha(grid) === before.grid };
results.violations = [...new Set(violations)];
writeFileSync(join(OUT, "behave-results.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 1));
cleanup();
process.exit(0);
