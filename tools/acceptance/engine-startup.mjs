// Starts the Studio engine for an acceptance harness and waits, with bounded waits and bounded diagnostics, for the
// one-line JSON handshake ({"port": ...}) it prints on stdout.
//
// Failure modes, each a rejected promise with a short message (never a hang):
//   - the executable cannot be started (missing Python)        -> "engine executable not found: <name>"
//   - the engine exits before the handshake                    -> exit code plus a bounded tail of its stderr
//   - no handshake within timeoutMs                            -> the child this call started is stopped by its PID
// The child is only ever stopped by the PID this module spawned, never by name.
import { spawn, spawnSync } from "node:child_process";
import { homedir } from "node:os";
import { basename, resolve } from "node:path";

export const DEFAULT_TIMEOUT_MS = 60000;
const STDERR_TAIL_BYTES = 1500;
const STDOUT_CAP = 65536;

/** Stop a process tree by the PID this script started. */
export function stopTree(pid) {
  if (!pid) return;
  try {
    if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });
    else process.kill(pid, "SIGKILL");
  } catch { /* already gone */ }
}

/** Last STDERR_TAIL_BYTES of text, with the repo and home folders replaced so no absolute local path is reported. */
export function boundedTail(text, repoRoot) {
  let t = String(text).slice(-STDERR_TAIL_BYTES).trim();
  const roots = [[resolve(repoRoot), "<repo>"], [homedir(), "~"]];
  for (const [root, label] of roots) {
    if (!root) continue;
    for (const form of new Set([root, root.replaceAll("\\", "/")])) t = t.split(form).join(label);
  }
  return t;
}

/**
 * @param {{command: string, args: string[], cwd: string, env: object, repoRoot: string, timeoutMs?: number,
 *          onSpawn?: (child: import("node:child_process").ChildProcess) => void}} o
 * @returns {Promise<{child: import("node:child_process").ChildProcess, handshake: any}>}
 */
export function startEngine({ command, args, cwd, env, repoRoot, timeoutMs = DEFAULT_TIMEOUT_MS, onSpawn }) {
  return new Promise((resolveP, reject) => {
    const child = spawn(command, args, { cwd, env, stdio: ["ignore", "pipe", "pipe"] });
    if (onSpawn) onSpawn(child);
    let buf = "";
    let stderr = "";
    let settled = false;
    const settle = (fn, value, stop) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (stop) stopTree(child.pid);
      fn(value);
    };
    const timer = setTimeout(
      () => settle(reject, new Error(`engine did not report its port within ${timeoutMs} ms; stopped the process this run started (pid ${child.pid})`), true),
      timeoutMs,
    );
    child.once("error", (e) => settle(reject, new Error(e?.code === "ENOENT"
      ? `engine executable not found: ${basename(String(command))} (set PYTHON to a Python 3.13+ interpreter)`
      : `engine could not be started: ${e?.code ?? e?.message}`), true));
    child.once("close", (code, signal) => {
      const tail = boundedTail(stderr, repoRoot);
      settle(reject, new Error(`engine exited before reporting its port (code ${code}${signal ? `, signal ${signal}` : ""})${tail ? `; last stderr:\n${tail}` : ""}`), false);
    });
    child.stderr.on("data", (d) => { stderr = (stderr + d).slice(-STDERR_TAIL_BYTES * 4); });
    child.stdout.on("data", (d) => {
      buf = (buf + d).slice(-STDOUT_CAP);
      const m = buf.match(/\{[^{}]*\}/);
      if (!m) return;
      try { settle(resolveP, { child, handshake: JSON.parse(m[0]) }, false); } catch { /* keep reading */ }
    });
  });
}
