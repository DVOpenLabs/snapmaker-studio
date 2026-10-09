// node --test tools/acceptance/engine-startup.test.mjs
// Failure modes of the harness's engine start, driven by fake executables (this node binary running tiny scripts).
// Outcomes are decided by events, not sleeps; the only timer is the short handshake timeout injected below.
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { startEngine, boundedTail } from "./engine-startup.mjs";

const dir = mkdtempSync(join(tmpdir(), "engine-startup-test-"));
const script = (name, body) => { const p = join(dir, name); writeFileSync(p, body); return p; };
const run = (command, args, timeoutMs = 5000) =>
  startEngine({ command, args, cwd: dir, env: process.env, repoRoot: resolve(dir, ".."), timeoutMs });
const alive = (pid) => { try { process.kill(pid, 0); return true; } catch { return false; } };

test("happy path: the handshake is parsed and the child keeps running until stopped", async () => {
  const s = script("ok.mjs", 'console.log(\'{"port": 4321}\'); setInterval(() => {}, 1000);');
  const { child, handshake } = await run(process.execPath, [s]);
  try { assert.equal(handshake.port, 4321); assert.ok(alive(child.pid)); } finally { child.kill(); }
});

test("a missing executable fails fast with a clear message", async () => {
  await assert.rejects(run(join(dir, "no-such-python"), []), (e) => {
    assert.match(e.message, /engine executable not found: no-such-python/);
    assert.ok(!e.message.includes(dir), "no absolute path in the message");
    return true;
  });
});

test("an early exit is reported with its code and a bounded stderr tail", async () => {
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

test("a handshake timeout stops the child this call started, by PID", async () => {
  const s = script("hang.mjs", "setInterval(() => {}, 1000);");
  let pid;
  await assert.rejects(startEngine({ command: process.execPath, args: [s], cwd: dir, env: process.env, repoRoot: dir, timeoutMs: 400, onSpawn: (c) => { pid = c.pid; } }), (e) => {
    assert.match(e.message, /did not report its port within 400 ms/);
    return true;
  });
  for (let i = 0; i < 50 && alive(pid); i++) await new Promise((r) => setTimeout(r, 100));
  assert.equal(alive(pid), false, "the hung child is gone");
});

test("boundedTail keeps the end and hides the repo folder", () => {
  const t = boundedTail("a".repeat(5000) + " " + join(dir, "f.py"), dir);
  assert.ok(t.length <= 1500);
  assert.match(t, /<repo>/);
});
