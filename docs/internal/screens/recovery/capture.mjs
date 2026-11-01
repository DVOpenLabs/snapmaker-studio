#!/usr/bin/env node
// Captures the recovery and passport screens (real engine + this checkout's Vite UI + headless Edge).
// Every artifact and mock stays on loopback or in a throwaway local folder.
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from "node:fs";
import http from "node:http";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..", "..", "..");
const backendDir = join(repo, "backend");
const out = here;
const external = process.env.SNAPSTUDIO_CAPTURE_EXTERNAL === "1";
const work = external ? process.env.CAPTURE_WORK : mkdtempSync(join(tmpdir(), "recovery-shot-"));
if (!work) throw new Error("CAPTURE_WORK is required in external-service mode");
const files = external ? process.env.CAPTURE_FILES : join(work, "files");
if (!files) throw new Error("CAPTURE_FILES is required in external-service mode");
if (!external) mkdirSync(files);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const children = [];
let mockServer;
const cleanup = () => {
  for (const c of children) {
    try { spawnSync("taskkill", ["/PID", String(c.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* gone */ }
  }
  try { mockServer?.close(); } catch { /* already closed */ }
  if (!external) { try { rmSync(work, { recursive: true, force: true }); } catch { /* temporary data only */ } }
};
process.on("exit", cleanup);

let hs;
if (external) {
  hs = { port: Number(process.env.ENGINE_PORT), token: process.env.ENGINE_TOKEN };
  if (!hs.port || !hs.token) throw new Error("ENGINE_PORT and ENGINE_TOKEN are required in external-service mode");
} else {
  const backend = spawn(process.env.PYTHON || "py", ["-3.13", "-m", "snapstudio_api"], {
    cwd: backendDir, stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, SNAPSTUDIO_DATA_DIR: join(work, "data"), SNAPSTUDIO_ORCA_DATA_DIR: join(work, "orca"),
      PYTHONPATH: backendDir, PYTHONUNBUFFERED: "1" },
  });
  children.push(backend);
  hs = await new Promise((ok, fail) => {
    let buf = "";
    backend.stdout.on("data", (d) => { buf += d; const m = buf.match(/\{[^{}]*\}/); if (m) { try { ok(JSON.parse(m[0])); } catch { /* keep reading */ } } });
    setTimeout(() => fail(new Error("engine did not report its port")), 60000);
  });
}
const post = async (path, body) => {
  const res = await fetch(`http://127.0.0.1:${hs.port}${path}`, { method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": hs.token }, body: JSON.stringify(body) });
  const payload = await res.json();
  if (!res.ok) throw new Error(`${path} returned ${res.status}: ${JSON.stringify(payload)}`);
  return payload;
};

// Reuse the deterministic synthetic tetrahedron and add only an established FOrca key.
if (!external) {
  const built = spawnSync(process.env.PYTHON || "py", ["-3.13", "-c",
    "import sys; from pathlib import Path; from tests.test_crosstrack_journey import _synthetic_project; _synthetic_project(Path(sys.argv[1]))",
    join(files, "synthetic-project.3mf")], {
    cwd: backendDir, env: { ...process.env, PYTHONPATH: backendDir }, encoding: "utf8", timeout: 30000,
  });
  if (built.status !== 0) throw new Error(`could not build synthetic project: ${built.stderr}`);
}
const original = process.env.SOURCE_FILE || join(files, "synthetic-project.3mf");
const prepared = (await post("/convert", { path: original, out_dir: files })).output_path;
const extra = join(files, "synthetic-sliced.gcode");
writeFileSync(extra, "synthetic sliced stand-in");
await post("/recovery/checkpoint", {
  workspace: { name: "Synthetic demo", stage: "review" }, observations: [],
  files: [original, prepared, extra].map((path) => ({ name: path.split(/[\\/]/).at(-1), path })),
  jobs: [{ job_id: "synthetic-job", state: "running" }],
});

// A loopback mock on an ephemeral, non-default port. Only the two documented GET paths answer.
const mockRequests = [];
const mock = http.createServer((req, res) => {
  const path = new URL(req.url, "http://127.0.0.1").pathname;
  mockRequests.push([req.method, path]);
  res.setHeader("Content-Type", "application/json");
  if (req.method !== "GET") { res.writeHead(405).end("{}"); return; }
  if (path === "/printer/objects/query") {
    res.end(JSON.stringify({ result: { status: { print_stats: { filename: "synthetic-job.gcode", state: "standby" } } } }));
  } else if (path === "/server/history/list") {
    res.end(JSON.stringify({ result: { jobs: [] } }));
  } else res.writeHead(404).end("{}");
});
mockServer = mock;
await new Promise((ok) => mock.listen(0, "127.0.0.1", ok));
const monitorPort = mock.address().port;
if (monitorPort === 7125) throw new Error("mock unexpectedly received the default monitoring port");

const vitePort = external ? Number(process.env.VITE_PORT) : await new Promise((ok, fail) => {
  const p = net.createServer(); p.once("error", fail);
  p.listen(0, "127.0.0.1", () => { const { port } = p.address(); p.close(() => ok(port)); });
});
const UI = `http://localhost:${vitePort}`;
if (!external) children.push(spawn("npx.cmd", ["vite", "--port", String(vitePort), "--strictPort", "--host", "localhost"], {
  cwd: join(repo, "desktop"), stdio: "ignore", shell: true,
}));
let ready = false;
for (let i = 0; i < 80 && !ready; i++) { try { ready = (await fetch(UI + "/")).ok; } catch { /* not yet */ } if (!ready) await sleep(500); }
if (!ready) throw new Error("UI did not come up");

const debugPort = external ? Number(process.env.EDGE_DEBUG_PORT) : await new Promise((ok, fail) => {
  const p = net.createServer(); p.once("error", fail);
  p.listen(0, "127.0.0.1", () => { const { port } = p.address(); p.close(() => ok(port)); });
});
if (!external) {
  const edgeCandidates = ["C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"];
  const edge = edgeCandidates.find(existsSync);
  if (!edge) throw new Error("Microsoft Edge was not found");
  children.push(spawn(edge, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--remote-debugging-address=127.0.0.1", `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${join(work, "edge-profile")}`, "about:blank"], { stdio: "ignore" }));
}
const debugUrl = `http://127.0.0.1:${debugPort}`;
let target;
for (let i = 0; i < 80 && !target; i++) {
  try { target = await fetch(debugUrl + "/json/new?about:blank", { method: "PUT" }).then((r) => r.json()); }
  catch { await sleep(250); }
}
if (!target?.webSocketDebuggerUrl) throw new Error("Edge DevTools target did not start");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok, fail) => { socket.addEventListener("open", ok, { once: true }); socket.addEventListener("error", fail, { once: true }); });
let commandId = 0;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const response = JSON.parse(event.data);
  if (response.id && pending.has(response.id)) {
    const { resolve: done, reject } = pending.get(response.id); pending.delete(response.id);
    if (response.error) reject(new Error(response.error.message)); else done(response.result);
  }
});
const cdp = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++commandId; pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params }));
});
const evaluate = async (expression) => {
  const result = await cdp("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "browser evaluation failed");
  return result.result?.value;
};
const waitFor = async (expression, label) => {
  for (let i = 0; i < 100; i++) { if (await evaluate(expression)) return; await sleep(200); }
  throw new Error(`timed out waiting for ${label}`);
};
const navigate = async (url) => { await cdp("Page.navigate", { url }); await waitFor("document.readyState === 'complete'", "page navigation"); };
const fill = async (label, value) => evaluate(`(() => { const e = [...document.querySelectorAll('input')].find(x => x.getAttribute('aria-label') === ${JSON.stringify(label)}); if (!e) throw Error('missing input'); const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; setter.call(e, ${JSON.stringify(value)}); e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); return true; })()`);
const clickText = async (text) => evaluate(`(() => { const e = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === ${JSON.stringify(text)}); if (!e) throw Error('missing button: ' + ${JSON.stringify(text)}); e.click(); return true; })()`);
const screenshot = async (path) => {
  const png = await cdp("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, fromSurface: true });
  writeFileSync(path, Buffer.from(png.data, "base64"));
};
await cdp("Page.enable"); await cdp("Runtime.enable");
await cdp("Emulation.setDeviceMetricsOverride", { width: 1280, height: 1100, deviceScaleFactor: 1, mobile: false });
await cdp("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "dark" }] });

// Build a passport in the real UI, then change both inputs and check it again.
await navigate(`${UI}/passport?api=${hs.port}:${hs.token}`);
await fill("Original file path", original);
await fill("Prepared copy path", prepared);
await clickText("Build passport");
await waitFor("!!document.querySelector('[data-testid=passport-report]')", "passport report");
writeFileSync(prepared, Buffer.concat([readFileSync(prepared), Buffer.from("\nsynthetic mutation")]));
rmSync(original);
writeFileSync(original, "different synthetic file with the same name");
rmSync(extra);                                   // a tracked file that is now missing from its recorded location
await clickText("Check the files again");
await waitFor("document.querySelector('[data-testid=chain-summary]')?.textContent.includes('no longer match what the passport recorded')", "invalidated passport summary");
await evaluate("(() => { const s=document.createElement('style'); s.textContent='input[aria-label*=\\\"path\\\"] { color: transparent !important; }'; document.head.append(s); return true; })()");
await screenshot(join(out, "passport-invalidated.png"));

// Recovery preview uses the pre-mutation checkpoint and the configured non-default port.
await navigate(`${UI}/recovery?api=${hs.port}:${hs.token}`);
await waitFor("!!document.querySelector('[data-testid=restore-preview]')", "recovery preview");
const previewText = await evaluate("document.querySelector('[data-testid=restore-preview]').innerText");
if (!previewText.includes("changed since the checkpoint") || !previewText.includes("missing from its recorded location")) {
  throw new Error(`unexpected recovery preview: ${previewText}`);
}
await fill("Configured printer host", "127.0.0.1");
await fill("Configured printer port", String(monitorPort));
await clickText("Read status");
await waitFor("!!document.querySelector('[data-testid=monitor-summary]')", "monitor response");
const monitorText = await evaluate("document.querySelector('[data-testid=monitor-summary]').innerText");
if (!monitorText.includes("standby") || !monitorText.includes("synthetic-job.gcode")) throw new Error("configured mock port did not return monitoring data");
await screenshot(join(out, "restore-preview.png"));
if (mockRequests.some(([method, path]) => method !== "GET" || path !== "/printer/objects/query")) {
  throw new Error(`monitor sentinel observed an unapproved request: ${JSON.stringify(mockRequests)}`);
}
console.log(JSON.stringify({ monitorPort, mockRequests, previewText }));
socket.close();
mock.close();
process.exit(0);
