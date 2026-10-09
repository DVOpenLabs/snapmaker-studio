// Gathers one evidence run into docs/testing/project-viewer/results.json. Run it AFTER mkfx.py, shots.mjs, behave.mjs, csp.mjs,
// heap.mjs and heap2.mjs have written their *-results.json files to P3B_OUT, on the exact commit you want the evidence to be
// about. It runs the type check, the unit tests and the build itself, records the commit it ran on, and copies the screenshots.
// Nothing in the README's measurement tables is typed by hand: make-readme-tables.mjs generates them from the file written here.
//
//   node collect-results.mjs            writes results.json and copies the screenshots
//   P3B_BASE_REF=<commit-ish>           also builds that commit's main chunk to report the size change (optional)
import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { OUT_DIR, REPO } from "./paths.mjs";

const DOCS = join(REPO, "docs", "testing", "project-viewer");
const DESKTOP = join(REPO, "desktop");
const run = (cmd, args, cwd) => spawnSync(cmd, args, { cwd, shell: true, encoding: "utf8", maxBuffer: 1 << 28 });
const git = (...a) => run("git", a, REPO).stdout.trim();
const read = (name) => {
  const p = join(OUT_DIR, name);
  if (!existsSync(p)) throw new Error(`missing ${p}: run the harness scripts first (see harness/README.md)`);
  return JSON.parse(readFileSync(p, "utf8"));
};

const behave = read("behave-results.json");
const shots = read("shots-results.json");
const csp = read("csp-results.json");
const heap = read("heap-results.json");
const heap2 = read("heap2-results.json");

// Identity of the run. "dirty" ignores the evidence folder itself, which is committed after the run.
const commit = git("rev-parse", "HEAD");
const dirty = git("status", "--porcelain", "--", ".", ":(exclude)docs/testing/project-viewer").length > 0;

// Checks, run here so their numbers come from this run.
const tsc = run("npx", ["tsc", "--noEmit"], DESKTOP);
const vitestOut = join(tmpdir(), `p3b-vitest-${process.pid}.json`);
run("npx", ["vitest", "run", "--reporter=json", `--outputFile=${vitestOut}`], DESKTOP);
const vj = JSON.parse(readFileSync(vitestOut, "utf8"));
rmSync(vitestOut, { force: true });
const build = run("npm", ["run", "build"], DESKTOP);

const assets = join(DESKTOP, "dist", "assets");
const chunk = (prefix) => {
  const name = readdirSync(assets).find((f) => f.startsWith(prefix) && f.endsWith(".js"));
  const data = readFileSync(join(assets, name));
  return { bytes: data.length, gzip9: gzipSync(data, { level: 9 }).length };
};
const bundle = { mainChunk: chunk("index-"), lazyViewerChunk: chunk("ProjectScenePanel-") };

const baseRef = process.env.P3B_BASE_REF;
if (baseRef) {
  const dir = join(DESKTOP, ".base-build");
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir);
  const archived = run("git", ["archive", baseRef, "desktop", "|", "tar", "-x", "-C", `"${dir}"`], REPO);
  if (archived.status !== 0) console.error("baseline archive failed:", archived.stderr);
  const built = run(`"${join(DESKTOP, "node_modules", ".bin", "vite")}"`, ["build", "--outDir", "dist"], join(dir, "desktop"));
  if (built.status !== 0) console.error("baseline build failed:", built.stderr || built.stdout);
  if (built.status === 0) {
    const bAssets = join(dir, "desktop", "dist", "assets");
    const name = readdirSync(bAssets).find((f) => f.startsWith("index-") && f.endsWith(".js"));
    const data = readFileSync(join(bAssets, name));
    bundle.baseline = { ref: baseRef, commit: git("rev-parse", baseRef), mainChunk: { bytes: data.length, gzip9: gzipSync(data, { level: 9 }).length } };
  }
  rmSync(dir, { recursive: true, force: true });
}

const results = {
  schema: "project-viewer-results/2",
  commit, dirtyOutsideEvidenceFolder: dirty, collectedAt: new Date().toISOString(),
  machine: { os: process.platform, browser: behave.browser, webglHardware: behave.webglHardware },
  checks: {
    tsc: { exitCode: tsc.status },
    vitest: { files: vj.testResults.length, tests: vj.numTotalTests, passed: vj.numPassedTests, failed: vj.numFailedTests },
    build: { exitCode: build.status },
  },
  bundle,
  interaction: behave.interaction,
  cyclesFacade: behave.cycles,
  cyclesApp: { ...behave.uiCycles, documentKeydownStacks: undefined },
  memory: { app: behave.memory, perViewerCreateDispose: heap.facadeHeap, perAppMount: heap2 },
  largeScene: behave.large,
  csp: { policy: csp.csp, violations: csp.violations, canvasCount: csp.canvasCount, isProductionBuild: csp.isProductionBuild, harnessError: csp.harnessError ?? null },
  originalFilesUnchanged: { ...behave.originalsUnchanged, ...shots.originalsUnchanged, csp: csp.originalUnchanged },
  screenshots: Object.fromEntries(Object.entries(shots.shots).map(([k, v]) => [k, { overflowX: v.overflowX, canvases: v.canvases, consoleErrors: v.errors }])),
  harnessErrors: [behave.harnessError, shots.harnessError, csp.harnessError].filter(Boolean),
  notRun: [
    "Packaged Windows Tauri via tools/acceptance/run.ps1",
    "Linux WebKitGTK graphics-enabled lane",
    "macOS WKWebView", "screen reader", "weak or software-rendered GPU", "real printer (never used)",
  ],
};
writeFileSync(join(DOCS, "results.json"), JSON.stringify(results, null, 2) + "\n");

// Screenshots: the harness wrote them to P3B_OUT; the ones named in results.json are copied next to the README.
const shotDir = join(DOCS, "screenshots");
mkdirSync(shotDir, { recursive: true });
const names = [...Object.keys(shots.shots), "large-100k", "wide-dark-picked-by-click", "csp-production"];
for (const n of names) {
  const from = join(OUT_DIR, `${n}.png`);
  if (existsSync(from) && statSync(from).size > 0) copyFileSync(from, join(shotDir, `${n}.png`));
}
console.log(JSON.stringify({ commit, dirty, checks: results.checks, bundle: results.bundle, harnessErrors: results.harnessErrors }, null, 1));
process.exit(tsc.status === 0 && build.status === 0 && vj.numFailedTests === 0 && results.harnessErrors.length === 0 ? 0 : 1);
