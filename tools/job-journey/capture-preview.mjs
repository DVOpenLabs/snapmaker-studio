// Painted-preview captures: node tools/job-journey/capture-preview.mjs --out <dir> [--probe]
// Synthetic fixtures and an invented loopback spool list only; the harness refuses printer, discovery and off-machine calls.
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { launch } from "./harness.mjs";

const arg = (n) => (process.argv.includes(n) ? process.argv[process.argv.indexOf(n) + 1] : null);
const out = arg("--out") ?? join(process.cwd(), "preview");
const probe = process.argv.includes("--probe");
mkdirSync(out, { recursive: true });
const h = await launch();
const log = [];
const spools = [
  { id: 1, registered: "2026-01-01T00:00:00Z", remaining_weight: 800, filament: { name: "Invented Blue", material: "PLA", color_hex: "1E64F0", weight: 1000, vendor: { name: "Invented" } } },
  { id: 2, registered: "2026-01-01T00:00:00Z", remaining_weight: 700, filament: { name: "Invented Pink", material: "PLA", color_hex: "F04EA0", weight: 1000, vendor: { name: "Invented" } } },
  { id: 3, registered: "2026-01-01T00:00:00Z", remaining_weight: 600, filament: { name: "Invented Orange", material: "PLA", color_hex: "FF7A00", weight: 1000, vendor: { name: "Invented" } } },
];
try {
  const fake = await h.fakeSpools(spools);
  const painted = h.fixture("painted/orcaslicer-2.4.2-painted-cube.3mf");
  const slab = h.fixture("painted/snapmaker-orca-2.3.5-authored.3mf");
  for (const theme of ["light", "dark"]) {
    const { ctx, page, go, openProject } = await h.newPage({ theme, provider: fake.address });
    await go("/this-print");
    await openProject(painted);
    await page.waitForSelector('[data-testid="viewer-stub"], [data-testid="model-viewer"] canvas, [data-testid="preview-unavailable"]', { timeout: 30000 }).catch(() => log.push("no preview"));
    await page.waitForTimeout(1200);
    await page.screenshot({ path: join(out, `${theme}-1-original.png`) });
    if (probe) {
      const names = await page.getByRole("button").evaluateAll((els) => els.map((e) => (e.getAttribute("aria-label") || e.textContent || "").trim().slice(0, 60)));
      console.log(JSON.stringify(names, null, 1));
      console.log(await page.locator('[data-testid="model-viewer"]').evaluate((e) => ({ drawn: e.dataset.drawn, instances: e.dataset.instances, triangles: e.dataset.triangles })).catch((e) => String(e)));
    }
    // Choose a spool for slot 1 (first row's Pink) and slot 3 (third row's Blue), then compare.
    await page.getByRole("button", { name: /^Pink/ }).nth(0).click();
    await page.getByRole("button", { name: /^Blue/ }).nth(2).click();
    await page.waitForTimeout(300);
    await page.getByRole("button", { name: "Your choices" }).click();
    await page.waitForTimeout(500);
    await page.screenshot({ path: join(out, `${theme}-2-your-choices.png`) });
    log.push(`${theme} drawn after choices: ` + await page.locator('[data-testid="model-viewer"]').evaluate((e) => e.dataset.drawn));
    // Highlight one head through the keyboard, as a keyboard user would.
    await page.locator('[data-testid="legend"] button[data-slot="2"]').focus();
    await page.waitForTimeout(400);
    await page.screenshot({ path: join(out, `${theme}-3-legend-focus.png`) });
    await ctx.close();
  }
  // A dense 5-colour project: more colours than toolheads, exact painted patches, and the copy read back.
  for (const theme of ["light", "dark"]) {
    const { ctx, page, go, openProject } = await h.newPage({ theme, provider: fake.address });
    await go("/this-print");
    const t0 = Date.now();
    await openProject(slab);
    await page.waitForSelector('[data-testid="model-viewer"] canvas, [data-testid="preview-unavailable"]', { timeout: 60000 }).catch(() => log.push("no slab preview"));
    log.push(`${theme} slab preview ready in ${Date.now() - t0} ms; ` + await page.locator('[data-testid="model-viewer"]').evaluate((e) => `${e.dataset.triangles} triangles, ${e.dataset.drawn}`).catch(() => "no canvas"));
    await page.waitForTimeout(800);
    await page.screenshot({ path: join(out, `${theme}-4-five-colours.png`) });
    await page.waitForSelector('[data-primary="create"]:not([disabled])', { timeout: 30000 }).catch(() => {});
    await page.click('[data-primary="create"]');
    await page.waitForSelector('[data-testid="copy-result"]', { timeout: 60000 }).catch(() => log.push("no slab copy"));
    await page.getByRole("button", { name: /Open project/ }).first().click().catch(() => {});
    await page.waitForTimeout(1500);
    const copyBtn = page.getByRole("button", { name: "U1 copy" });
    if (await copyBtn.count()) { await copyBtn.click(); await page.waitForTimeout(500); await page.screenshot({ path: join(out, `${theme}-5-copy-colours.png`) }); log.push(`${theme} copy drawn: ` + await page.locator('[data-testid="model-viewer"]').evaluate((e) => e.dataset.drawn).catch(() => "none")); }
    else log.push(`${theme}: no U1 copy toggle`);
    await ctx.close();
  }
  { // Narrow widths with the preview.
    for (const [w, hgt] of [[1024, 700], [720, 800]]) {
      const { ctx, page, go, openProject } = await h.newPage({ theme: "light", width: w, height: hgt, provider: fake.address });
      await go("/this-print");
      await openProject(painted);
      await page.waitForSelector('[data-testid="model-viewer"] canvas', { timeout: 30000 }).catch(() => log.push(`no preview at ${w}`));
      await page.waitForTimeout(1000);
      await page.screenshot({ path: join(out, `light-6-width-${w}.png`), fullPage: true });
      await ctx.close();
    }
  }
  console.log(JSON.stringify({ log, violations: h.violations, errors: h.errors.slice(0, 8) }, null, 1));
} finally { await h.close(); }
