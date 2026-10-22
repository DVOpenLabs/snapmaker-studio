// AFTER screenshots of the job screen: node tools/job-journey/capture-after.mjs --out <dir> [--only <name>]
// Synthetic fixtures only; the harness refuses printer and discovery calls and every non-local host.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { launch, repo } from "./harness.mjs";

const arg = (n) => (process.argv.includes(n) ? process.argv[process.argv.indexOf(n) + 1] : null);
const out = arg("--out") ?? join(process.cwd(), "after");
const only = arg("--only");
mkdirSync(out, { recursive: true });
const h = await launch();
const shot = (page, name, opts = {}) => page.screenshot({ path: join(out, `${name}.png`), ...opts });
const want = (name) => !only || only === name;
const log = [];

try {
  const painted = h.fixture("painted/bambustudio-2.08.02.61-authored.3mf");
  const native = h.fixture("painted/snapmaker-orca-2.3.5-authored.3mf");
  const broken = join(h.work, "broken.3mf");
  writeFileSync(broken, "this is not a zip archive");

  for (const theme of ["light", "dark"]) {
    // Empty, loading, ready.
    if (want("flow")) {
      const { ctx, page, go, openProject } = await h.newPage({ theme });
      await go("/this-print");
      await shot(page, `${theme}-1-empty`);
      await openProject(painted);
      await page.waitForTimeout(150);
      await shot(page, `${theme}-2-loading`);
      await page.waitForSelector('[data-primary="create"]:not([disabled])', { timeout: 20000 }).catch(() => log.push(`${theme}: create never enabled`));
      await page.waitForTimeout(1500);
      await shot(page, `${theme}-3-ready-materials`);
      await page.click('[data-pane-tab="target"]');
      await page.waitForTimeout(1200);
      await shot(page, `${theme}-4-target`);
      await page.click('[data-pane-tab="settings"]');
      await shot(page, `${theme}-5-copy-settings`);
      await page.click('[data-primary="create"]');
      await page.waitForSelector('[data-testid="copy-result"], [data-testid="prepare-refusal"], [data-testid="job-blocked"]', { timeout: 30000 }).catch(() => log.push(`${theme}: no copy result`));
      await page.waitForTimeout(1500);
      await shot(page, `${theme}-6-copy-created`);
      await shot(page, `${theme}-6-copy-created-full`, { fullPage: true });
      await ctx.close();
    }
    // The returned slice, compared inside the same job. The G-code is built from the backend test constants (synthetic).
    if (want("compare")) {
      const gcode = join(h.work, "synthetic-job.gcode");
      const made = spawnSync(process.env.PYTHON || "py", ["-c", "import sys; sys.path.insert(0,\".\"); from tests import test_gcode as t; open(sys.argv[1],\"w\").write(t.HEADER+t.SUMMARY+t.CONFIG)", gcode], { cwd: join(repo, "backend") });
      if (made.status !== 0) log.push("could not build the synthetic G-code");
      const { ctx, page, go, openProject } = await h.newPage({ theme });
      await go("/this-print");
      await openProject(painted);
      await page.waitForSelector('[data-primary="create"]:not([disabled])', { timeout: 20000 }).catch(() => {});
      await page.click('[data-primary="create"]');
      await page.waitForSelector('[data-testid="copy-result"]', { timeout: 30000 }).catch(() => log.push(theme + ": no copy for compare"));
      await page.evaluate(async (p) => { const m = await import("/src/store/sliced.ts"); m.useSliced.getState().setSliced(p); }, gcode);
      await page.waitForTimeout(3500);
      await shot(page, theme + "-10-compare-slice");
      await shot(page, theme + "-10-compare-slice-full", { fullPage: true });
      await ctx.close();
    }
    // A project made for the U1 itself, then one the engine cannot read.
    if (want("other")) {
      const { ctx, page, go, openProject } = await h.newPage({ theme });
      await go("/this-print");
      await openProject(native);
      await page.waitForTimeout(3000);
      await shot(page, `${theme}-7-native-project`);
      await openProject(broken);
      await page.waitForTimeout(3000);
      await shot(page, `${theme}-8-unreadable`);
      await ctx.close();
    }
    // Narrow desktop widths.
    if (want("narrow")) {
      for (const [w, hgt] of [[1024, 700], [900, 700], [720, 800]]) {
        const { ctx, page, go, openProject } = await h.newPage({ theme, width: w, height: hgt });
        await go("/this-print");
        await openProject(painted);
        await page.waitForTimeout(3500);
        await shot(page, `${theme}-9-width-${w}`, { fullPage: true });
        await ctx.close();
      }
    }
  }
  console.log(JSON.stringify({ log, violations: h.violations, errors: h.errors.slice(0, 8) }, null, 1));
} finally { await h.close(); }
