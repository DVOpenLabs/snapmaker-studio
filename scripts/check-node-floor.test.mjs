// node --test scripts/check-node-floor.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { checkNodeVersion, MINIMUMS } from "./check-node-floor.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

test("fixed releases and newer patch/minor releases pass", () => {
  for (const v of ["v22.23.4", "22.23.4", "v22.23.5", "v22.24.0", "v24.22.1", "v24.23.0", "v26.12.1", "v26.13.0"]) {
    assert.equal(checkNodeVersion(v).ok, true, v);
  }
});

test("affected releases fail, including the machine versions seen in the audit", () => {
  for (const v of ["v22.23.3", "v22.22.0", "v22.0.0", "v24.22.0", "v24.21.0", "v24.11.0", "v26.12.0", "v26.0.0"]) {
    assert.equal(checkNodeVersion(v).ok, false, v);
  }
});

test("lines without a fix are refused: Node 20, 21, 23, 25, 27, 18", () => {
  for (const v of ["v20.19.5", "v20.99.99", "v21.7.3", "v23.11.1", "v25.9.0", "v27.0.0", "v18.20.8"]) {
    const r = checkNodeVersion(v);
    assert.equal(r.ok, false, v);
    assert.match(r.reason, /no security fix/);
  }
});

test("pre-release and nightly builds are refused at every fixed boundary", () => {
  for (const v of ["v22.23.4-rc.0", "v24.22.1-rc.0", "v26.12.1-nightly2026102101", "v22.23.5-pre", "22.23.4+build", "v24.22.1-"]) {
    assert.equal(checkNodeVersion(v).ok, false, v);
  }
});

test("the command line check exits 0 on this runtime exactly when the floor is met", () => {
  const script = join(root, "scripts", "check-node-floor.mjs");
  const r = spawnSync(process.execPath, [script], { encoding: "utf8" });
  assert.equal(r.status, checkNodeVersion(process.version).ok ? 0 : 1, r.stdout + r.stderr);
  assert.match(r.stdout, /security floor/);
});

test("unparseable input fails closed", () => {
  for (const v of ["", "latest", "22", "v22.x"]) assert.equal(checkNodeVersion(v).ok, false, v);
});

test(".nvmrc names a release that meets the floor, and no workflow requests a floating or old major", () => {
  const pinned = readFileSync(join(root, ".nvmrc"), "utf8").trim();
  assert.equal(checkNodeVersion(pinned).ok, true, pinned);
  assert.deepEqual(MINIMUMS[22], [22, 23, 4]);
  for (const name of ["ci", "guide-ci", "linux-ci", "release", "release-linux"]) {
    const text = readFileSync(join(root, ".github", "workflows", `${name}.yml`), "utf8");
    assert.doesNotMatch(text, /node-version:\s*["']?(18|20|21|22|23|24)["']?\s*$/m, `${name}: floating major`);
    assert.match(text, /node-version-file:\s*\.nvmrc/, `${name}: setup-node must read .nvmrc`);
    assert.match(text, /check-node-floor\.mjs/, `${name}: must run the floor check`);
  }
});

// Smoke test of the decoder on the running runtime. It is NOT proof of the CVE-2026-111497 fix (that comes from the
// version floor above) and uses no exploit input: a round trip and a damaged stream that must fail with a normal
// error. It runs only on a release that meets the floor, so an affected runtime never decodes damaged input here.
import { brotliCompressSync, brotliDecompressSync } from "node:zlib";
import { checkNodeVersion as floor } from "./check-node-floor.mjs";

test("brotli decoder smoke test on a patched runtime", { skip: floor(process.version).ok ? false : "runtime is below the security floor" }, () => {
  const text = Buffer.from("snapmaker studio ".repeat(500));
  assert.deepEqual(brotliDecompressSync(brotliCompressSync(text)), text);
  const damaged = Buffer.from(brotliCompressSync(text));
  damaged[Math.floor(damaged.length / 2)] ^= 0xff;
  assert.throws(() => brotliDecompressSync(damaged), (e) => e instanceof Error);
});
