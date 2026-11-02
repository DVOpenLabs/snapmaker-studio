#!/usr/bin/env node
// Studio+ development-build demo driver: Journey B - prepare, checkpoint, passport, changed/missing, read-only recovery preview
//
// Starts, on loopback only: the Studio engine from source, the Vite dev server, a headless Chromium-family browser
// driven over the Chrome DevTools Protocol, and (where needed) stand-ins for a Lumina-compatible service and a
// printer. Every input is a disposable synthetic file generated into a throwaway folder; the driver writes only
// there and to DEMO_OUT, touches no real project, and involves no printer or release artifact. It reads the
// repository's own code and dependencies, and the engine may read the bundled profile folders of an installed
// Snapmaker Orca (read-only; the driver never launches Orca). It kills only the processes it started.
// See docs/demo/REPRODUCE.md.
//
// Env: DEMO_REPO (repo root; default: this checkout), DEMO_OUT (screenshots + results; default: <tmp>/studio-demo-out),
//      PYTHON (python executable; default: "py -3.13" on Windows, "python3" elsewhere), EDGE_PATH (browser binary).
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, readdirSync, rmSync, appendFileSync } from "node:fs";
import http from "node:http";
import net from "node:net";
import { tmpdir } from "node:os";
import { createHash } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(process.env.DEMO_REPO || join(here, "..", "..", ".."));
const outRoot = resolve(process.env.DEMO_OUT || join(tmpdir(), "studio-demo-out")); mkdirSync(outRoot, { recursive: true });
const shots = join(outRoot, "shots-b"); mkdirSync(shots, { recursive: true });
const work = mkdtempSync(join(tmpdir(), "demo-"));
const inputs = join(work, "inputs"); mkdirSync(inputs);
const dataDir = join(work, "data");
const PYTHON = process.env.PYTHON ? [/[\\/]/.test(process.env.PYTHON) ? resolve(process.env.PYTHON) : process.env.PYTHON] : process.platform === "win32" ? ["py", "-3.13"] : ["python3"];
const [PYCMD, ...PYARGS] = PYTHON;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sha = (buf) => createHash("sha256").update(buf).digest("hex");
const children = [];
const results = [];
const log = (name, ok, detail) => { results.push({ name, ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  :: " + String(detail).slice(0, 400) : ""}`); };
const cleanup = () => { for (const c of children) { try { if (c.exitCode !== null || c.signalCode !== null) continue; if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(c.pid), "/T", "/F"], { stdio: "ignore" }); else c.kill("SIGTERM"); } catch { /* gone */ } } };
process.on("exit", cleanup);
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { cleanup(); try { rmSync(work, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 }); } catch { /* temp only */ } process.exit(130); });
const py = (args, opts = {}) => spawnSync(PYCMD, [...PYARGS, ...args], { encoding: "utf8", timeout: 60000, ...opts });

// ---- fixtures (synthetic, same helper the tests use) -------------------------------------------------------
const gen = py(["-I", "-c", `
import sys, pathlib
sys.path.insert(0, ${JSON.stringify(join(repo, "backend", "tests", "fixtures", "creative"))})
from zip_factory import make_3mf, make_ditherforge, make_ditherforge_bambu, make_kromacut
d = pathlib.Path(sys.argv[1])
(d / "sample-kromacut.3mf").write_bytes(make_kromacut())
(d / "sample-ditherforge-bambu.3mf").write_bytes(make_ditherforge_bambu(extra={"Metadata/plate_1.json": b"{}"}))
(d / "sample-ditherforge-generic.3mf").write_bytes(make_ditherforge(extra={"Metadata/plate_1.json": b"{}"}))
(d / "sample-plain.3mf").write_bytes(make_3mf(settings={"layer_height": "0.2"}, members={"Metadata/custom.bin": b"synthetic-opaque"}))
`, inputs], { env: { ...process.env } });
if (gen.status !== 0) { console.error(gen.stderr); process.exit(2); }
writeFileSync(join(inputs, "synthetic-image.png"), Buffer.from("synthetic-image-bytes-not-a-real-picture"));
writeFileSync(join(inputs, "synthetic-sliced.gcode"), "; synthetic sliced stand-in, not produced by any slicer\n");
const origSha = Object.fromEntries(readdirSync(inputs).map((f) => [f, sha(readFileSync(join(inputs, f)))]));

const firstJson = (child, label) => new Promise((ok, fail) => {
  let buf = "";
  child.stdout.on("data", (d) => { buf += d; const m = buf.match(/\{[^{}]*\}/); if (m) { try { ok(JSON.parse(m[0])); } catch { /* keep reading */ } } });
  setTimeout(() => fail(new Error(`${label} did not report in time`)), 60000);
});
const freePort = () => new Promise((ok, fail) => { const p = net.createServer(); p.once("error", fail); p.listen(0, "127.0.0.1", () => { const { port } = p.address(); p.close(() => ok(port)); }); });

// ---- services ------------------------------------------------------------------------------------------------
const mockLog = join(work, "lumina-mock-log.json");
const lumina = spawn(PYCMD, [...PYARGS, "-I", "-c", `
import json, sys, time, hashlib
sys.path.insert(0, ${JSON.stringify(join(repo, "backend"))})
from tests.mocks.lumina_server import LuminaHttpMock, HTTP_ARTIFACTS
IMG = open(sys.argv[2], "rb").read()
with LuminaHttpMock() as mock:
    print(json.dumps({"url": mock.url}), flush=True)
    while True:
        up = [{"type": u.get("type"), "len": len(u.get("bytes") or b""), "contains_input_image_bytes": IMG in (u.get("bytes") or b"")} if isinstance(u, dict) else {"repr": repr(u)[:80]} for u in mock.uploads]
        art = {k: [v[0], hashlib.sha256(v[1]).hexdigest()] for k, v in HTTP_ARTIFACTS.items()}
        open(sys.argv[1], "w").write(json.dumps({"requests": mock.requests, "uploads": up, "artifacts": art}))
        time.sleep(0.25)
`, mockLog, join(inputs, "synthetic-image.png")], { stdio: ["ignore", "pipe", "pipe"] });
children.push(lumina);
const svc = await firstJson(lumina, "lumina stand-in");

const backend = spawn(PYCMD, [...PYARGS, "-m", "snapstudio_api"], {
  cwd: inputs, stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, SNAPSTUDIO_DATA_DIR: dataDir, SNAPSTUDIO_ORCA_DATA_DIR: join(work, "orca"), PYTHONPATH: join(repo, "backend"), PYTHONUNBUFFERED: "1" },
});
children.push(backend);
const hs = await firstJson(backend, "engine");
const post = async (path, body) => {
  const res = await fetch(`http://127.0.0.1:${hs.port}${path}`, { method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": hs.token }, body: JSON.stringify(body) });
  return { status: res.status, body: await res.json().catch(() => null) };
};

// printer stand-in: records EVERY verb on an ephemeral non-default port; only two GET paths answer.
const mockRequests = [];
const printer = http.createServer((req, res) => {
  const path = new URL(req.url, "http://127.0.0.1").pathname;
  mockRequests.push([req.method, path]);
  res.setHeader("Content-Type", "application/json");
  if (req.method !== "GET") { res.writeHead(405).end("{}"); return; }
  if (path === "/printer/objects/query") res.end(JSON.stringify({ result: { status: { print_stats: { filename: "synthetic-job.gcode", state: "standby" } } } }));
  else if (path === "/server/history/list") res.end(JSON.stringify({ result: { jobs: [] } }));
  else res.writeHead(404).end("{}");
});
await new Promise((ok) => printer.listen(0, "127.0.0.1", ok));
const printerPort = printer.address().port;

const vitePort = await freePort();
const UI = `http://localhost:${vitePort}`;
children.push(spawn(process.platform === "win32" ? "npx.cmd" : "npx", ["--no-install", "vite", "--port", String(vitePort), "--strictPort", "--host", "localhost"], { cwd: join(repo, "desktop"), stdio: "ignore", shell: true }));
for (let i = 0, ready = false; i < 120 && !ready; i++) { try { ready = (await fetch(UI + "/")).ok; } catch { /* not yet */ } if (!ready) await sleep(500); }

const debugPort = await freePort();
const edge = [process.env.EDGE_PATH, "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "/usr/bin/microsoft-edge", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"].filter(Boolean).find(existsSync);
if (!edge) { console.error("No Edge/Chrome/Chromium found. Set EDGE_PATH to a browser binary."); process.exit(2); }
children.push(spawn(edge, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--disable-component-update", "--remote-debugging-address=127.0.0.1",
  `--remote-debugging-port=${debugPort}`, `--user-data-dir=${join(work, "edge-profile")}`, "about:blank"], { stdio: "ignore" }));
let target;
for (let i = 0; i < 80 && !target; i++) { try { target = await fetch(`http://127.0.0.1:${debugPort}/json/new?about:blank`, { method: "PUT" }).then((r) => r.json()); } catch { await sleep(250); } }
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok, fail) => { socket.addEventListener("open", ok, { once: true }); socket.addEventListener("error", fail, { once: true }); });
let cid = 0; const pending = new Map(); const pageErrors = [];
socket.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const { resolve: done, reject } = pending.get(m.id); pending.delete(m.id); m.error ? reject(new Error(m.error.message)) : done(m.result); }
  else if (m.method === "Runtime.exceptionThrown") pageErrors.push(m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text);
});
const cdp = (method, params = {}) => new Promise((resolve, reject) => { const id = ++cid; pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); });
const evaluate = async (expression) => {
  const r = await cdp("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text || "evaluation failed");
  return r.result?.value;
};
const bodyText = () => evaluate("document.body.innerText");
const mainText = () => evaluate("(document.querySelector('main') || document.body).innerText");
const waitFor = async (expr, label, tries = 150) => {
  for (let i = 0; i < tries; i++) { if (await evaluate(expr)) return; await sleep(200); }
  throw new Error(`timed out: ${label}; page says: ${(await mainText()).replace(/\s+/g, " ").slice(0, 300)}`);
};
const waitText = (t, label = t, tries) => waitFor(`document.body.innerText.includes(${JSON.stringify(t)})`, label, tries);
const navigate = async (url) => { await cdp("Page.navigate", { url }); await sleep(300); await waitFor("document.readyState === 'complete'", "load"); };
const nativeSet = (sel, value) => evaluate(`(() => { const e = ${sel}; if (!e) throw Error('missing field'); const proto = e.tagName === 'SELECT' ? HTMLSelectElement.prototype : e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(e, ${JSON.stringify(value)}); e.dispatchEvent(new Event(e.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); return true; })()`);
const fill = (label, value) => nativeSet(`document.querySelector('[aria-label=${JSON.stringify(label)}]') || [...document.querySelectorAll('input,select,textarea')].find(x => x.labels && [...x.labels].some(l => l.textContent.trim().startsWith(${JSON.stringify(label)})))`, value);
const clickText = (text, exact = true) => evaluate(`(() => { const e = [...document.querySelectorAll('button,a,[role=tab]')].find(x => { const t = x.textContent.trim(); return ${exact ? "t === " : "t.includes("}${JSON.stringify(text)}${exact ? "" : ")"}; }); if (!e) throw Error('missing control: ' + ${JSON.stringify(text)}); if (e.disabled) throw Error('control disabled: ' + ${JSON.stringify(text)}); e.click(); return true; })()`);
const hasControl = (text) => evaluate(`[...document.querySelectorAll('button,a')].some(x => x.textContent.trim() === ${JSON.stringify(text)})`);
const pathNow = () => evaluate("location.pathname");
const allowedPathNeedles = () => [tmpdir(), tmpdir().replace(/\\/g, "/"), work, work.replace(/\\/g, "/"), "AppData", "\\Users\\", "/Users/", "/home/"];
const assertNoLocalPath = async () => {
  const text = await bodyText();
  const inputsNow = await evaluate(`[...document.querySelectorAll('input,textarea')].map(e => ({ v: e.value || '', masked: /path/i.test(e.getAttribute('aria-label') || '') && getComputedStyle(e).color === 'rgba(0, 0, 0, 0)' }))`);
  const visible = [text, ...inputsNow.filter((i) => !i.masked).map((i) => i.v)];
  for (const s of visible) if (allowedPathNeedles().some((n) => n && s.includes(n)) || /(^|[^A-Za-z])[A-Za-z]:[\\/]/.test(s)) throw new Error("a local path is visible; refusing to capture");
};
const maskPaths = () => evaluate("(() => { if (!document.getElementById('mask')) { const s=document.createElement('style'); s.id='mask'; s.textContent='input[aria-label*=\"ath\"] { color: transparent !important; }'; document.head.append(s);} return true; })()");
const shot = async (name) => {
  await maskPaths(); await sleep(250); await assertNoLocalPath();
  const png = await cdp("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, fromSurface: true });
  writeFileSync(join(shots, name), Buffer.from(png.data, "base64"));
  const t = (await mainText()).replace(/\s+/g, " ").slice(0, 900);
  appendFileSync(join(outRoot, "screen-text-b.log"), `\n## ${name}\n${t}\n`);
};
const step = async (name, fn) => { try { const d = await fn(); log(name, true, d); return d; } catch (e) { log(name, false, e.message); return undefined; } };

await cdp("Page.enable"); await cdp("Runtime.enable");
await cdp("Emulation.setDeviceMetricsOverride", { width: 1280, height: 2400, deviceScaleFactor: 1, mobile: false });
await cdp("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "dark" }] });
await cdp("Page.addScriptToEvaluateOnNewDocument", { source: `try{localStorage.setItem('theme','dark');localStorage.setItem('mode','advanced');}catch(e){}` });
rmSync(join(outRoot, "screen-text-b.log"), { force: true });

const identity = { repo_head: spawnSync("git", ["-C", repo, "rev-parse", "HEAD"], { encoding: "utf8" }).stdout.trim(), engine_port: hs.port, vite_port: vitePort,
  printer_mock_port: printerPort, lumina_mock_url_is_loopback: /^http:\/\/127\.0\.0\.1:\d+$/.test(svc.url), input_sha256: origSha, started: new Date().toISOString() };
console.log("IDENTITY", JSON.stringify(identity));

// ============================ navigation: real sidebar, not direct route dispatch ================================
await navigate(`${UI}/?api=${hs.port}:${hs.token}`);
await step("nav: app shell loads and shows the Studio+ group", async () => {
  await waitFor("document.body.innerText.includes('Creative import')", "sidebar lists Creative import");
  const t = await bodyText();
  const want = ["Creative import", "Lumina service", "Passport", "Recovery"];
  const missing = want.filter((w) => !t.includes(w));
  await shot("00-app-shell.png");
  if (missing.length) throw new Error("sidebar entries missing: " + missing.join(", "));
  return "sidebar has " + want.join(", ");
});
const byLabel = (l) => `!!document.querySelector('[aria-label=${JSON.stringify(l)}]')`;
const navTo = async (label, expectPath, readyExpr) => {
  await clickText(label, false);
  await waitFor(`location.pathname === ${JSON.stringify(expectPath)}`, `route ${expectPath}`);
  await waitFor(readyExpr, `ready on ${expectPath}`);
};

// ===================== Journey B, entirely through the UI (no API checkpoint, no injected state) ==========================
const outDirFor = () => join(dataDir, "creative-prepared");
const listOut = () => (existsSync(outDirFor()) ? readdirSync(outDirFor()).sort() : []);
const inspect = async (file, waitFor_) => { await fill("Project file path", file); await clickText("Inspect project"); await waitText(waitFor_, waitFor_, 100); };
const prepare = async (waitFor_) => { await clickText("Prepare a U1 copy"); await waitText(waitFor_, waitFor_, 150); };
const projA = join(inputs, "sample-kromacut.3mf"), projB = join(inputs, "sample-ditherforge-bambu.3mf");
const treeHash = () => Object.fromEntries([...readdirSync(inputs).map((f) => join(inputs, f)), ...listOut().map((f) => join(outDirFor(), f))].filter(existsSync).map((p) => [p, sha(readFileSync(p))]));
const saveEnabled = `[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Checkpoint this workspace' && !b.disabled)`;
const trackedText = () => evaluate("document.querySelector('[data-testid=tracked-files]')?.innerText || ''");
const mt = () => mainText().then((t) => t.replace(/\s+/g, " "));
let copyA;

await step("B1 UI: Creative import -> inspect -> Prepare (Kromacut, absolute path)", async () => {
  await navTo("Creative import", "/creative", byLabel("Project file path"));
  await inspect(projA, "Looks like Kromacut");
  const before = listOut(); await prepare("Export verification");
  const added = listOut().filter((n) => !before.includes(n)); if (added.length !== 1) throw new Error("expected one new copy: " + JSON.stringify(added));
  copyA = join(outDirFor(), added[0]); await shot("B1-creative-prepared.png"); return `copy ${added[0]} written`;
});
await step("B2 UI: Recovery lists exactly the files that will be tracked and explains the unavailable one", async () => {
  await navTo("Recovery", "/recovery", saveEnabled); await shot("B2-recovery-tracked-files.png");
  const tracked = await trackedText(); const un = await evaluate("document.querySelector('[data-testid=unavailable-files]')?.innerText || ''");
  if (!/Original project: sample-kromacut\.3mf/.test(tracked) || !/Prepared copy: sample-kromacut_SnapmakerU1\.3mf/.test(tracked)) throw new Error("tracked list wrong: " + tracked);
  if (/Sliced/.test(tracked)) throw new Error("a sliced file is listed as tracked: " + tracked);
  if (!/Sliced output not tracked/.test(un)) throw new Error("no explanation for the unavailable sliced file: " + un);
  const sample = await evaluate("!![...document.querySelectorAll('section')].find(s => s.getAttribute('aria-label') === 'Sample data')");
  return `tracked=[${tracked.replace(/\n/g, "; ")}] unavailable=[${un.replace(/\s+/g, " ")}]; sample-data section separate: ${sample}`;
});
await step("B3 UI: 'Checkpoint this workspace' saves it; preview shows both files unchanged", async () => {
  await clickText("Checkpoint this workspace"); await waitText("Workspace checkpoint saved", "saved notice");
  await waitFor("document.querySelector('[data-testid=restore-preview]')?.innerText.includes('unchanged since the checkpoint')", "preview unchanged");
  const notice = await evaluate("document.querySelector('[data-testid=checkpoint-notice]').innerText");
  const prev = await evaluate("document.querySelector('[data-testid=restore-preview]').innerText").then((t) => t.replace(/\s+/g, " "));
  await shot("B3-recovery-checkpoint-saved.png");
  const same = (prev.match(/unchanged since the checkpoint/g) || []).length;
  if (same !== 2) throw new Error("expected 2 unchanged files: " + prev);
  return `${notice}; preview: ${prev.slice(0, 300)}`;
});
await step("B4 UI: Passport 'Use this job's files' -> Build passport (original + prepared; no sliced invented)", async () => {
  await navTo("Passport", "/passport", byLabel("Original file path"));
  await clickText("Use this job's files");
  const sliced = await evaluate("document.querySelector('[aria-label=\"Sliced output path\"]').value");
  if (sliced !== "") throw new Error("sliced field was filled: " + sliced);
  await clickText("Build passport"); await waitFor("!!document.querySelector('[data-testid=passport-report]')", "passport report");
  const scope = await evaluate("document.querySelector('[data-testid=passport-scope]').innerText").then((t) => t.replace(/\s+/g, " ").slice(0, 200));
  await shot("B4-passport-built-for-project.png"); return scope;
});
await step("B5 UI: Passport -> Recovery -> Passport keeps the fields and the report", async () => {
  await navTo("Recovery", "/recovery", saveEnabled); await navTo("Passport", "/passport", byLabel("Original file path"));
  const kept = await evaluate("!!document.querySelector('[data-testid=passport-report]')");
  const orig = await evaluate("document.querySelector('[aria-label=\"Original file path\"]').value !== ''");
  const ls = await evaluate("JSON.stringify(Object.keys(localStorage))");
  await shot("B5-passport-after-navigation.png");
  if (!kept || !orig) throw new Error(`report kept=${kept} fields kept=${orig}`);
  if (/passport/i.test(ls)) throw new Error("localStorage has a passport key: " + ls);
  return `report and fields kept after navigation; localStorage keys: ${ls}`;
});
const beforeMut = treeHash();
await step("B6 mutate on disk (original replaced, prepared copy deleted); 'Check the files again' on the SAME passport -> invalidated", async () => {
  writeFileSync(projA, Buffer.from("different synthetic file, same name")); rmSync(copyA);
  await clickText("Check the files again");
  await waitFor("document.querySelector('[data-testid=chain-summary]')?.textContent.includes('no longer match what the passport recorded')", "invalidated");
  await shot("B6-passport-invalidated.png"); return (await mt()).slice(0, 380);
});
await step("B7 UI: Recovery preview shows changed original and missing prepared copy", async () => {
  await navTo("Recovery", "/recovery", saveEnabled); await clickText("Refresh restore preview"); await sleep(900);
  const text = await evaluate("document.querySelector('[data-testid=restore-preview]').innerText").then((t) => t.replace(/\s+/g, " "));
  await shot("B7-recovery-changed-missing.png");
  if (!/sample-kromacut\.3mf: changed since the checkpoint/.test(text) || !/sample-kromacut_SnapmakerU1\.3mf: missing from its recorded location/.test(text)) throw new Error("preview wrong: " + text);
  return text.slice(0, 480);
});
await step("B8 no hardware action replayed; file bytes unchanged by preview; mock requests observed", async () => {
  const pre = treeHash(); await clickText("Refresh restore preview"); await sleep(800); const post_ = treeHash();
  if (JSON.stringify(pre) !== JSON.stringify(post_)) throw new Error("recovery preview changed bytes on disk");
  await fill("Configured printer host", "127.0.0.1"); await fill("Configured printer port", String(printerPort));
  await clickText("Read status"); await waitFor("!!document.querySelector('[data-testid=monitor-summary]')", "monitor summary"); await shot("B8-monitoring-read-only.png");
  if (mockRequests.length !== 1 || mockRequests[0][0] !== "GET" || mockRequests[0][1] !== "/printer/objects/query") throw new Error("sentinel: " + JSON.stringify(mockRequests));
  const text = await evaluate("document.querySelector('[data-testid=restore-preview]').innerText");
  return `bytes identical across ${Object.keys(pre).length} files; printer requests=${JSON.stringify(mockRequests)}; job lines: ${(text.match(/Job [^.]*\./g) || []).join(" | ") || "(none recorded)"}`;
});
await step("B9 switch projects in the UI: previous project's passport and fields are not shown", async () => {
  await navTo("Creative import", "/creative", byLabel("Project file path"));
  await inspect(projB, "Looks like DitherForge"); const before = listOut(); await prepare("Export verification");
  if (listOut().length !== before.length + 1) throw new Error("second project's copy not written");
  await navTo("Passport", "/passport", byLabel("Original file path"));
  await waitFor("!!document.querySelector('[data-testid=passport-notice]')", "cleared notice");
  const report = await evaluate("!!document.querySelector('[data-testid=passport-report]')");
  const fields = await evaluate("[...document.querySelectorAll('input')].map(i => i.value).filter(Boolean).length");
  const text = await bodyText(); await shot("B9-passport-after-project-switch.png");
  if (report || fields !== 0) throw new Error(`leak: report=${report} filled fields=${fields}`);
  if (/sample-kromacut/.test(await mainText())) throw new Error("previous project's name is still on the Passport page");
  return "report cleared, fields empty, notice: " + (await evaluate("document.querySelector('[data-testid=passport-notice]').innerText"));
});
await step("B10 Recovery after the switch lists the NEW project's files; saved checkpoint is still the old one", async () => {
  await navTo("Recovery", "/recovery", saveEnabled); await shot("B10-recovery-new-project.png");
  const tracked = await trackedText(); if (!/sample-ditherforge-bambu\.3mf/.test(tracked)) throw new Error("new project not tracked: " + tracked);
  const prev = await evaluate("document.querySelector('[data-testid=restore-preview]')?.innerText || ''").then((t) => t.replace(/\s+/g, " "));
  if (!/revision 1/.test(await mt()) || !/sample-kromacut\.3mf/.test(prev)) throw new Error("the saved checkpoint is not still the earlier one: " + prev.slice(0, 200));
  return `will track: ${tracked.replace(/\n/g, "; ")} | saved checkpoint (unchanged until you save again): ${prev.slice(0, 220)}`;
});
await step("B11 failure: checkpoint with a tracked file deleted after Prepare is reported honestly (not a silent success)", async () => {
  const copyB = listOut().map((n) => join(outDirFor(), n)).find((p) => /ditherforge-bambu/.test(p)); rmSync(copyB);
  await clickText("Checkpoint this workspace"); await sleep(1500);
  const notice = await evaluate("document.querySelector('[data-testid=checkpoint-notice]')?.innerText || ''"); await shot("B11-checkpoint-missing-file.png");
  const prev = await evaluate("document.querySelector('[data-testid=restore-preview]')?.innerText || ''").then((t) => t.replace(/\s+/g, " "));
  if (!/Not verifiable later/.test(notice) || !/ditherforge-bambu_SnapmakerU1\.3mf/.test(notice)) throw new Error("a checkpoint with a missing file was not flagged: " + notice);
  return `notice="${notice}"; preview after: ${prev.slice(0, 300)}`;
});


identity.finished = new Date().toISOString(); identity.page_errors = pageErrors.slice(0, 10);
writeFileSync(join(outRoot, "results-b.json"), JSON.stringify({ identity, results, printer_requests: mockRequests }, null, 1));
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} steps passed; page errors: ${pageErrors.length}`);
socket.close(); printer.close(); cleanup();
try { rmSync(work, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 }); } catch { /* temp only */ }
process.exit(failed.length || pageErrors.length ? 1 : 0);
