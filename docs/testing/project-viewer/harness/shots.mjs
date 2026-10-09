// Screenshots of the project view (anonymous fixtures only) in light/dark, wide/narrow, and the WebGL fallback states.
import { start, stage, launch, loopbackOnly, cleanup, sleep, sha, OUT_DIR, FIXTURES, REPO } from "./harness.mjs";
import { mkdirSync, writeFileSync, copyFileSync } from "node:fs";
import { join } from "node:path";
const OUT = OUT_DIR;
mkdirSync(OUT, { recursive: true });
const FX = FIXTURES;
const { handshake, UI } = await start();
const files = {
  offbed: stage("demo_offplate_foreign.3mf", FX), normal: stage("sample_cube_U1.3mf", FX),
  stl: stage("sample_cube.stl", FX), showcase: stage("demo_u1_showcase.3mf", FX),
  roles: join(FX, "three-roles.3mf"), plates: join(FX, "two-plates.3mf"), inch: join(FX, "inch-cube.3mf"),
};
const before = Object.fromEntries(Object.entries(files).map(([k, p]) => [k, sha(p)]));
const browser = await launch();
const violations = [], results = { shots: {}, notes: [] };

async function scenario(name, { file, theme = "dark", mode = "advanced", width = 1280, height = 1500, noWebgl = false, lose = false, select = false, slope = false }) {
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: theme, serviceWorkers: "block" });
  await ctx.addInitScript(([t, m, nw]) => {
    localStorage.setItem("theme", t); localStorage.setItem("mode", m);
    if (nw) { const orig = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function (type, ...a) { return /webgl/.test(type) ? null : orig.call(this, type, ...a); }; }
  }, [theme, mode, noWebgl]);
  loopbackOnly(ctx, handshake.port, violations);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR|Invalid DOM property/.test(m.text())) errors.push(m.text().slice(0, 200)); });
  await page.goto(`${UI}/?api=${handshake.port}:${handshake.token}&file=${encodeURIComponent(file)}`);
  await page.locator("#brand-splash").waitFor({ state: "detached", timeout: 30000 });
  await page.getByRole("button", { name: /Open a model/ }).first().click();
  const panel = page.getByTestId("project-scene");
  await panel.waitFor({ timeout: 90000 });
  await page.waitForFunction(() => {
    const p = document.querySelector('[data-testid="project-scene"]');
    if (!p) return false;
    const t = p.textContent || "";
    return /Retry 3D view|Try again/.test(t) || ([...p.querySelectorAll("button")].find((b) => b.textContent === "Top") || {}).disabled === false;
  }, null, { timeout: 90000 });
  await sleep(2500);
  if (lose) {
    await page.evaluate(() => { const c = document.querySelector('[data-testid="scene-host"] canvas'); const gl = c.getContext("webgl2") || c.getContext("webgl"); gl.getExtension("WEBGL_lose_context").loseContext(); });
    await page.getByRole("button", { name: /Retry 3D view/ }).waitFor({ timeout: 10000 });
  }
  if (slope) { await page.getByRole("button", { name: "Slope view" }).click(); await sleep(1200); }
  if (select) { await page.getByRole("button", { name: /^Object 1/ }).click(); await sleep(1200); }
  await panel.scrollIntoViewIfNeeded();
  const out = join(OUT, `${name}.png`);
  await panel.screenshot({ path: out });
  const info = await page.evaluate(() => ({
    overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    canvases: document.querySelectorAll("canvas").length,
    buttons: [...document.querySelectorAll('[data-testid="project-scene"] button')].map((b) => ({ name: (b.textContent || "").trim().slice(0, 40), disabled: b.disabled })),
    text: document.querySelector('[data-testid="project-scene"]').innerText.replace(/\s+/g, " ").slice(0, 700),
  }));
  results.shots[name] = { ...info, errors };
  await ctx.close();
}

try {
  await scenario("wide-dark-offbed", { file: files.offbed });
  await scenario("wide-light-offbed", { file: files.offbed, theme: "light" });
  await scenario("wide-dark-normal", { file: files.normal });
  await scenario("wide-dark-selected", { file: files.offbed, select: true });
  await scenario("wide-dark-slope", { file: files.normal, slope: true });
  await scenario("wide-dark-roles", { file: files.roles });
  await scenario("wide-dark-stl", { file: files.stl });
  await scenario("wide-dark-two-plates", { file: files.plates });
  await scenario("wide-dark-inch", { file: files.inch });
  await scenario("narrow-dark-offbed", { file: files.offbed, mode: "simple", width: 820, height: 1500 });
  await scenario("narrow-light-offbed", { file: files.offbed, mode: "simple", width: 820, height: 1500, theme: "light" });
  await scenario("xnarrow-dark-offbed", { file: files.offbed, mode: "simple", width: 390, height: 1900 });
  await scenario("wide-dark-no-webgl", { file: files.offbed, noWebgl: true });
  await scenario("narrow-light-no-webgl", { file: files.offbed, noWebgl: true, mode: "simple", width: 820, height: 1500, theme: "light" });
  await scenario("wide-dark-context-lost", { file: files.offbed, lose: true });
} catch (e) { results.harnessError = String(e?.stack ?? e); }
finally { await browser.close(); }
results.violations = violations;
results.originalsUnchanged = Object.fromEntries(Object.entries(files).map(([k, p]) => [k, sha(p) === before[k]]));
writeFileSync(join(OUT, "shots-results.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 1).slice(0, 6000));
cleanup();
process.exit(0);
