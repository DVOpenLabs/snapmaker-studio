// BEFORE screenshots of the existing app (run on the base commit): node tools/job-journey/capture-before.mjs --out <dir>
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { launch } from "./harness.mjs";

const out = process.argv.includes("--out") ? process.argv[process.argv.indexOf("--out") + 1] : join(process.cwd(), "before");
mkdirSync(out, { recursive: true });
const h = await launch();
try {
  const painted = h.fixture("painted/bambustudio-2.08.02.61-authored.3mf");
  for (const theme of ["light", "dark"]) {
    const { ctx, page, go, openProject } = await h.newPage({ theme });
    await go("/this-print");
    await page.screenshot({ path: join(out, `${theme}-this-job-empty.png`) });
    await openProject(painted);
    await page.waitForTimeout(2500);
    await page.screenshot({ path: join(out, `${theme}-this-job-opened.png`), fullPage: false });
    await page.screenshot({ path: join(out, `${theme}-this-job-opened-full.png`), fullPage: true });
    await go("/workspace");
    await openProject(painted);
    await page.waitForTimeout(2500);
    await page.screenshot({ path: join(out, `${theme}-workspace.png`), fullPage: true });
    await go("/compatibility");
    await openProject(painted);
    await page.waitForTimeout(3500);
    await page.screenshot({ path: join(out, `${theme}-compatibility-materials.png`), fullPage: true });
    await ctx.close();
  }
  console.log(JSON.stringify({ violations: h.violations, errors: h.errors.slice(0, 5) }));
} finally { await h.close(); }
