// Unusual states of the job screen's model area: node tools/job-journey/capture-states.mjs --out <dir>
// Synthetic files only; the harness refuses printer, discovery and off-machine calls.
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { launch, repo } from "./harness.mjs";

const arg = (n) => (process.argv.includes(n) ? process.argv[process.argv.indexOf(n) + 1] : null);
const out = arg("--out") ?? join(process.cwd(), "states");
mkdirSync(out, { recursive: true });
const log = [];
const h1 = await launch();
const made = spawnSync(process.env.PYTHON || "py", ["-3.13", join(repo, "tools", "job-journey", "make_states.py"), join(h1.work, "states")], { encoding: "utf8" });
if (made.status !== 0) { console.log(made.stderr); process.exit(1); }
const f = (n) => join(h1.work, "states", n);
const text = (page, sel) => page.locator(sel).first().innerText().catch(() => "(none)");
try {
  const { ctx, page, go, openProject } = await h1.newPage({ theme: "light" });
  await go("/this-print");
  for (const [name, file, wait] of [["inch", "inch-project.3mf", '[data-testid="preview-unavailable"]'], ["shape-only", "shape-only.stl", '[data-testid="model-viewer"] canvas'], ["very-detailed", "very-detailed.3mf", '[data-testid="preview-unavailable"], [data-testid="model-viewer"] canvas'], ["missing", "does-not-exist.3mf", '[data-testid="preview-unavailable"], [role="alert"]']]) {
    await openProject(f(file));
    await page.waitForSelector(wait, { timeout: 40000 }).catch(() => log.push(`${name}: expected element never appeared`));
    await page.waitForTimeout(1200);
    log.push(`${name}: ${(await text(page, '[data-testid="preview-unavailable"]')).slice(0, 200)} | ${await page.locator('[data-testid="coverage-note"]').count() ? "has coverage note" : "no coverage note"}`);
    await page.screenshot({ path: join(out, `light-${name}.png`) });
  }
  await ctx.close();

  // Keyboard: Tab through the pane, focus ring on a legend row and on the canvas; arrow keys move the view.
  const painted = h1.fixture("painted/bambustudio-2.08.02.61-authored.3mf");
  const k = await h1.newPage({ theme: "light", reducedMotion: "reduce" });
  await k.go("/this-print");
  await k.openProject(painted);
  await k.page.waitForSelector('[data-testid="model-viewer"] canvas', { timeout: 30000 });
  await k.page.waitForTimeout(800);
  const order = [];
  await k.page.locator('[data-pane-tab="materials"]').focus().catch(() => {});
  await k.page.evaluate(() => document.querySelector('[aria-label="What to show"] button')?.focus());
  for (let i = 0; i < 9; i++) {
    order.push(await k.page.evaluate(() => { const e = document.activeElement; return (e?.getAttribute("aria-label") || e?.textContent || e?.tagName || "").trim().slice(0, 40) + (e?.matches?.(":focus-visible") ? " [focus-visible]" : ""); }));
    await k.page.keyboard.press("Tab");
  }
  log.push("tab order: " + JSON.stringify(order));
  await k.page.locator('[data-testid="model-viewer"] canvas').focus();
  const before = await k.page.locator('[data-testid="model-viewer"] canvas').evaluate((c) => c.toDataURL ? 1 : 0);
  await k.page.keyboard.press("ArrowLeft"); await k.page.keyboard.press("ArrowLeft");
  await k.page.waitForTimeout(300);
  await k.page.screenshot({ path: join(out, "light-keyboard-canvas-focus.png") });
  log.push(`canvas focusable: ${await k.page.evaluate(() => document.activeElement?.tagName === "CANVAS")}; reduced-motion animations running: ${await k.page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length)}`);
  await k.ctx.close();

  // 200% zoom is a 640 x 400 CSS-pixel window.
  const z = await h1.newPage({ theme: "light", width: 640, height: 400 });
  await z.go("/this-print");
  await z.openProject(painted);
  await z.page.waitForSelector('[data-testid="model-viewer"] canvas', { timeout: 30000 }).catch(() => log.push("no preview at 640x400"));
  await z.page.waitForTimeout(1000);
  await z.page.screenshot({ path: join(out, "light-zoom-200.png") });
  log.push(`zoom 200%: horizontal overflow = ${await z.page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)}`);
  await z.ctx.close();
  console.log(JSON.stringify({ log, violations: h1.violations, errors: h1.errors.slice(0, 8) }, null, 1));
} finally { await h1.close(); }

// No 3D graphics at all.
const h2 = await launch({ chromiumArgs: ["--disable-3d-apis", "--disable-webgl", "--disable-gpu"] });
try {
  const painted = h2.fixture("painted/bambustudio-2.08.02.61-authored.3mf");
  const { ctx, page, go, openProject } = await h2.newPage({ theme: "light" });
  await go("/this-print");
  await openProject(painted);
  await page.waitForSelector('[data-testid="preview-unavailable"], [data-testid="model-viewer"] canvas', { timeout: 40000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const msg = (await page.locator('[data-testid="preview-unavailable"]').first().innerText().catch(() => "(none)")).slice(0, 200);
  await page.screenshot({ path: join(out, "light-no-graphics.png") });
  console.log(JSON.stringify({ noGraphics: msg, violations: h2.violations, errors: h2.errors.slice(0, 4) }, null, 1));
  await ctx.close();
} finally { await h2.close(); }
