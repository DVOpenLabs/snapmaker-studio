// node --test tools/acceptance/engine-startup.test.mjs
// Failure modes of the harness's engine start, driven by fake executables (this node binary running tiny scripts).
// Outcomes are decided by events, not sleeps; the only timer is the short handshake timeout injected below.
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { basename, join, resolve } from "node:path";
import { startEngine, boundedTail, resolveTimeout, DEFAULT_TIMEOUT_MS, stopTree } from "./engine-startup.mjs";

// Hard per-test ceiling: a regression (a child that is never stopped) fails the test instead of hanging node --test.
const HARD_MS = 15000;
const dir = mkdtempSync(join(tmpdir(), "engine-startup-test-"));
const script = (name, body) => { const p = join(dir, name); writeFileSync(p, body); return p; };
const run = (command, args, timeoutMs = 5000) =>
  startEngine({ command, args, cwd: dir, env: process.env, repoRoot: resolve(dir, ".."), timeoutMs });
const alive = (pid) => { try { process.kill(pid, 0); return true; } catch { return false; } };

test("happy path: the handshake is parsed and the child keeps running until stopped", { timeout: HARD_MS }, async () => {
  const s = script("ok.mjs", 'console.log(\'{"port": 4321}\'); setInterval(() => {}, 1000);');
  const { child, handshake } = await run(process.execPath, [s]);
  try { assert.equal(handshake.port, 4321); assert.ok(alive(child.pid)); } finally { child.kill(); }
});

test("a missing executable fails fast with a clear message", { timeout: HARD_MS }, async () => {
  await assert.rejects(run(join(dir, "no-such-python"), []), (e) => {
    assert.match(e.message, /engine executable not found: no-such-python/);
    assert.ok(!e.message.includes(dir), "no absolute path in the message");
    return true;
  });
});

test("an early exit is reported with its code and a bounded stderr tail", { timeout: HARD_MS }, async () => {
  const s = script("early.mjs", `console.error("x".repeat(50000)); console.error("Traceback: boom in ${dir.replaceAll("\\", "/")}/engine.py"); process.exit(3);`);
  let pid;
  await assert.rejects(startEngine({ command: process.execPath, args: [s], cwd: dir, env: process.env, repoRoot: dir, timeoutMs: 5000, onSpawn: (c) => { pid = c.pid; } }), (e) => {
    assert.match(e.message, /exited before reporting its port \(code 3\)/);
    assert.match(e.message, /Traceback: boom in <repo>\/engine\.py/);
    assert.ok(e.message.length < 2200, `message is bounded (${e.message.length})`);
    assert.ok(!e.message.includes(dir));
    return true;
  });
  assert.equal(alive(pid), false);
});

test("a handshake timeout stops the child this call started, by PID", { timeout: HARD_MS }, async () => {
  const s = script("hang.mjs", "setInterval(() => {}, 1000);");
  let pid;
  try {
    await assert.rejects(startEngine({ command: process.execPath, args: [s], cwd: dir, env: process.env, repoRoot: dir, timeoutMs: 400, onSpawn: (c) => { pid = c.pid; } }), (e) => {
      assert.match(e.message, /did not report its port within 400 ms/);
      return true;
    });
    for (let i = 0; i < 50 && alive(pid); i++) await new Promise((r) => setTimeout(r, 100));
    assert.equal(alive(pid), false, "the hung child is gone");
  } finally {
    if (pid && alive(pid)) stopTree(pid); // never leave an orphan if the module regressed
  }
});

test("boundedTail keeps the end and hides the repo folder", () => {
  const t = boundedTail("a".repeat(5000) + " " + join(dir, "f.py"), dir);
  assert.ok(t.length <= 1500);
  assert.match(t, /<repo>/);
});

test("a home path straddling the cut is redacted before truncating", () => {
  const user = basename(homedir());
  const t = boundedTail("z".repeat(100) + join(homedir(), "x.py") + "b".repeat(1490), dir);
  assert.ok(!t.toLowerCase().includes(user.toLowerCase()), "no user name in the tail");
});

test("a home path is redacted whatever its letter case", () => {
  const user = basename(homedir());
  const t = boundedTail(`File "${homedir().toLowerCase()}\\a.py" and ${homedir().replaceAll("\\", "/").toUpperCase()}/b.py`, dir);
  assert.ok(!t.toLowerCase().includes(user.toLowerCase()), t);
  assert.match(t, /~/);
});

test("a .cmd shim as the interpreter gives a clear message", { skip: process.platform !== "win32", timeout: HARD_MS }, async () => {
  const shim = script("python.cmd", "@echo off\r\n");
  await assert.rejects(run(shim, []), /\.cmd\/\.bat shim.*python\.exe/);
});

test("the engine timeout setting must be a positive whole number", { timeout: HARD_MS }, async () => {
  assert.equal(resolveTimeout(undefined), DEFAULT_TIMEOUT_MS);
  assert.equal(resolveTimeout(""), DEFAULT_TIMEOUT_MS);
  assert.equal(resolveTimeout("250"), 250);
  for (const bad of ["-5", "0", "abc", "1.5", "NaN", "1e3x"]) assert.throws(() => resolveTimeout(bad), /positive whole number/, bad);
  await assert.rejects(run(process.execPath, ["-e", "0"], -1), /positive whole number/);
});
