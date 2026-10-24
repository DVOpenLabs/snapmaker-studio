// Refuses to run builds and tests on a Node.js release affected by the October 2026 security releases
// (notably CVE-2026-111497, the Brotli decoder in node:zlib). Updating npm packages does not patch Node, so the
// runtime itself is checked.
//
// Source: https://nodejs.org/en/blog/vulnerability/october-2026-security-releases (fixed: 22.23.4, 24.22.1, 26.12.1).
// Node 20 and odd-numbered lines received no fix and are refused. Raise MINIMUMS when a newer security release
// ships; never lower them.
//
// Usage: node scripts/check-node-floor.mjs      (prints the version; appends it to the CI step summary when set)
import { appendFileSync, realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const MINIMUMS = { 22: [22, 23, 4], 24: [24, 22, 1], 26: [26, 12, 1] };

/** `{ ok, reason }` for a Node version string such as "v22.23.4" or "22.23.4". */
export function checkNodeVersion(version) {
  // Pre-release and nightly builds are refused: their version number does not show that the fix is included.
  const m = /^v?(\d+)\.(\d+)\.(\d+)$/.exec(String(version).trim());
  if (!m) return { ok: false, reason: `cannot parse the Node.js version "${version}" (only plain release versions are accepted)` };
  const v = [Number(m[1]), Number(m[2]), Number(m[3])];
  const floor = MINIMUMS[v[0]];
  const supported = Object.values(MINIMUMS).map((f) => f.join(".")).join(", ");
  if (!floor) return { ok: false, reason: `Node.js ${v.join(".")} is on a line with no security fix (fixed releases: ${supported}); use a supported line` };
  for (let i = 0; i < 3; i++) {
    if (v[i] > floor[i]) return { ok: true, reason: "" };
    if (v[i] < floor[i]) return { ok: false, reason: `Node.js ${v.join(".")} is below the fixed release ${floor.join(".")} (CVE-2026-111497 and other October 2026 fixes); update Node.js` };
  }
  return { ok: true, reason: "" };
}

// Run as a command unless this module was imported (the test imports it). Paths are compared by real path so a
// symlink, junction or drive-letter case cannot make the check skip silently.
function isMain() {
  if (!process.argv[1]) return false;
  try {
    return realpathSync(fileURLToPath(import.meta.url)) === realpathSync(process.argv[1]);
  } catch {
    return true; // cannot tell: run the check rather than skip it
  }
}

if (isMain()) {
  const result = checkNodeVersion(process.version);
  const line = `Node.js ${process.version} ${result.ok ? "meets" : "does NOT meet"} the security floor`;
  console.log(line);
  if (process.env.GITHUB_STEP_SUMMARY) {
    try { appendFileSync(process.env.GITHUB_STEP_SUMMARY, `- ${line}\n`); } catch { /* the summary is informational */ }
  }
  if (!result.ok) { console.error(`error: ${result.reason}`); process.exit(1); }
}
