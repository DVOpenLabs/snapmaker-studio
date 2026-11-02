#!/usr/bin/env node
// Runs the Studio+ development-build demo journeys one after the other and reports one overall result.
//   node tools/demo/studio-plus/run.mjs            # Journeys A + C (with sidebar sweep), then Journey B
//   node tools/demo/studio-plus/run.mjs ac | b      # one part only
// Env: DEMO_OUT (screenshots + results; default <tmp>/studio-demo-out), PYTHON, EDGE_PATH, DEMO_REPO. See docs/demo/REPRODUCE.md.
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const which = (process.argv[2] || "all").toLowerCase();
if (!["all", "ac", "b"].includes(which)) { console.error("usage: run.mjs [all|ac|b]"); process.exit(2); }
const parts = [];
if (which === "all" || which === "ac") parts.push("journey-ac.mjs");
if (which === "all" || which === "b") parts.push("journey-b.mjs");

let failed = 0;
for (const p of parts) {
  console.log(`\n===== ${p} =====`);
  const r = spawnSync(process.execPath, [join(here, p)], { stdio: "inherit", env: process.env });
  if (r.status !== 0) failed++;
}
console.log(failed ? `\n${failed} part(s) FAILED` : "\nall parts passed");
process.exit(failed ? 1 : 0);
