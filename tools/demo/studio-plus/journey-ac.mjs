#!/usr/bin/env node
// Studio+ development-build demo driver: Journeys A and C (+ sidebar sweep) - Creative import/Prepare and the Lumina-compatible service client
//
// Starts, on loopback only: the Studio engine from source, the Vite dev server, a headless Chromium-family browser
// driven over the Chrome DevTools Protocol, and (where needed) stand-ins for a Lumina-compatible service and a
// printer. Every input is a disposable synthetic file generated into a throwaway folder; nothing outside that
// folder is read or modified, no real project is touched, and no Orca, printer or release artifact is involved.
// It kills only the processes it started. See docs/demo/REPRODUCE.md.
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
const shots = join(outRoot, "shots-ac"); mkdirSync(shots, { recursive: true });
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
  appendFileSync(join(outRoot, "screen-text-ac.log"), `\n## ${name}\n${t}\n`);
};
const step = async (name, fn) => { try { const d = await fn(); log(name, true, d); return d; } catch (e) { log(name, false, e.message); return undefined; } };

await cdp("Page.enable"); await cdp("Runtime.enable");
await cdp("Emulation.setDeviceMetricsOverride", { width: 1280, height: 2400, deviceScaleFactor: 1, mobile: false });
await cdp("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "dark" }] });
await cdp("Page.addScriptToEvaluateOnNewDocument", { source: `try{localStorage.setItem('theme','dark');localStorage.setItem('mode','advanced');}catch(e){}` });
rmSync(join(outRoot, "screen-text-ac.log"), { force: true });

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
const saveEnabled = `[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Save sample checkpoint' && !b.disabled)`;

// ======================================== Journey A: Creative -> Prepare ========================================
const outDirFor = () => join(dataDir, "creative-prepared");
const listOut = () => (existsSync(outDirFor()) ? readdirSync(outDirFor()).sort() : []);
const inspect = async (file, waitFor_) => {
  await fill("Project file path", file);
  await clickText("Inspect project");
  await waitText(waitFor_, waitFor_, 100);
};
const prepare = async (waitFor_) => { await clickText("Prepare a U1 copy"); await waitText(waitFor_, waitFor_, 150); };
const verifyArchive = (srcName, outName) => {
  const r = py(["-I", join(here, "verify_archive.py"), join(inputs, srcName), join(outDirFor(), outName)]);
  if (r.status !== 0) throw new Error("archive verify failed: " + r.stderr);
  const i = r.stdout.indexOf("SETTINGS_DIFF"); const v = JSON.parse(r.stdout.slice(0, i)); v.settings_diff = JSON.parse(r.stdout.slice(i + 14)); return v;
};
const outputsAfter = {};
await step("A0 nav: sidebar -> Creative import", async () => { await navTo("Creative import", "/creative", byLabel("Project file path")); return `engine still reachable via sidebar navigation (path ${await pathNow()})`; });
await step("A1 Kromacut: inspect", async () => { await inspect("sample-kromacut.3mf", "Looks like Kromacut"); await shot("A1-kromacut-inspection.png"); return (await bodyText()).includes("Original unchanged") ? "report shows Original unchanged" : "no 'Original unchanged' text"; });
await step("A2 Kromacut: Prepare -> export verification", async () => {
  const before = listOut(); await prepare("Export verification"); await shot("A2-kromacut-prepare-result.png");
  const after = listOut(); const added = after.filter((n) => !before.includes(n));
  if (added.length !== 1) throw new Error("expected exactly one new output, got " + JSON.stringify(added));
  outputsAfter.kromacut = added[0];
  const v = verifyArchive("sample-kromacut.3mf", added[0]);
  writeFileSync(join(outRoot, "A-kromacut-archive.json"), JSON.stringify(v, null, 1));
  const unchanged = sha(readFileSync(join(inputs, "sample-kromacut.3mf"))) === origSha["sample-kromacut.3mf"];
  if (!unchanged) throw new Error("ORIGINAL CHANGED");
  if (!v.output_zip_ok) throw new Error("output zip not valid");
  if (v.source_stats.paint_color_attrs !== v.output_stats.paint_color_attrs) throw new Error(`paint attrs ${v.source_stats.paint_color_attrs} -> ${v.output_stats.paint_color_attrs}`);
  if (v.source_stats.triangles !== v.output_stats.triangles) throw new Error("triangle count differs");
  return `out=${added[0]}; changed=${v.changed.join("|")}; dropped=${v.dropped.join("|") || "-"}; added=${v.added.join("|") || "-"}; paint ${v.source_stats.paint_color_attrs}->${v.output_stats.paint_color_attrs}; tri ${v.output_stats.triangles}; original sha unchanged`;
});
await step("A3 DitherForge Bambu-path: inspect + Prepare", async () => {
  await inspect("sample-ditherforge-bambu.3mf", "Looks like DitherForge"); await shot("A3-ditherforge-bambu-inspection.png");
  const before = listOut(); await prepare("Export verification"); await shot("A4-ditherforge-bambu-prepare-result.png");
  const added = listOut().filter((n) => !before.includes(n));
  if (added.length !== 1) throw new Error("expected exactly one new output, got " + JSON.stringify(added));
  const v = verifyArchive("sample-ditherforge-bambu.3mf", added[0]);
  writeFileSync(join(outRoot, "A-ditherforge-bambu-archive.json"), JSON.stringify(v, null, 1));
  if (sha(readFileSync(join(inputs, "sample-ditherforge-bambu.3mf"))) !== origSha["sample-ditherforge-bambu.3mf"]) throw new Error("ORIGINAL CHANGED");
  if (v.source_stats.paint_color_attrs !== v.output_stats.paint_color_attrs) throw new Error(`paint attrs ${v.source_stats.paint_color_attrs} -> ${v.output_stats.paint_color_attrs}`);
  return `out=${added[0]}; dropped=${v.dropped.join("|") || "-"}; added=${v.added.join("|") || "-"}; paint ${v.source_stats.paint_color_attrs}->${v.output_stats.paint_color_attrs}`;
});
await step("A5 DitherForge generic-path: honest refusal, nothing written", async () => {
  await inspect("sample-ditherforge-generic.3mf", "Looks like DitherForge");
  await fill("Project format", "ditherforge"); await sleep(300);
  const before = listOut(); await prepare("No copy was written"); await shot("A5-ditherforge-generic-refused.png");
  if (listOut().length !== before.length) throw new Error("a file was written for the generic path");
  const t = await bodyText();
  return "refused; output folder unchanged (" + before.length + " files); mentions: " + ["inspect", "generic", "part"].filter((k) => t.toLowerCase().includes(k)).join(",");
});
await step("A6 failure: unknown-origin Prepare refused", async () => {
  await fill("Project format", "auto");
  await inspect("sample-plain.3mf", "Origin unknown"); const before = listOut();
  await prepare("No copy was written"); await shot("A6-unknown-prepare-refused.png");
  if (listOut().length !== before.length) throw new Error("a file was written"); return "refused, nothing written";
});
await step("A7 failure: missing file path", async () => {
  await fill("Project file path", "does-not-exist.3mf"); await clickText("Inspect project");
  await waitText("That path is not a local file Studio can read", "missing-file message", 100);
  const t = (await mainText()).replace(/\s+/g, " "); await shot("A7-missing-file.png");
  if (/Looks like/.test(t)) throw new Error("an origin was reported for a missing file: " + t.slice(0, 200));
  return "refused: That path is not a local file Studio can read.";
});
await step("A8 failure: engine API refuses out-of-folder traversal / bad out_dir", async () => {
  const r = await post("/creative/prepare", { path: join(inputs, "sample-kromacut.3mf"), out_dir: join(work, "nonexistent-folder") });
  if (r.status < 400 && r.body?.prepared) throw new Error("prepare accepted a non-existent out_dir");
  return `status ${r.status}: ${JSON.stringify(r.body).slice(0, 140)}`;
});

// ============ sidebar transition sweep (smoke): Creative -> Passport -> Recovery -> Lumina ===============
await step("S nav sweep: Creative import -> Passport -> Recovery -> Creative import (engine stays connected, no page error)", async () => {
  await navTo("Passport", "/passport", byLabel("Original file path"));
  await navTo("Recovery", "/recovery", saveEnabled);
  await navTo("Creative import", "/creative", byLabel("Project file path"));
  return "4 sidebar transitions";
});

// ============================ Journey C: Lumina -> explicit format -> loopback service -> file ===================
const luminaOut = join(dataDir, "lumina-output");
const readMock = () => JSON.parse(readFileSync(mockLog, "utf8"));
await step("C0 nav: sidebar -> Lumina service", async () => { await navTo("Lumina service", "/lumina", byLabel("Service address")); await shot("C0-lumina-empty.png"); return "ok"; });
await step("C1 no format chosen: generate is not offered", async () => {
  await fill("Service address", svc.url); await fill("Image file path", "synthetic-image.png"); await fill("LUT name", "Default");
  const sel = await evaluate("(() => { const s=[...document.querySelectorAll('select')].find(x => (x.getAttribute('aria-label')||'')==='Output format'); return s ? {value:s.value, options:[...s.options].map(o=>o.value+'|'+o.textContent.trim())} : null; })()");
  const genDisabled = await evaluate("[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Generate' && b.disabled)");
  await shot("C1-lumina-no-format.png");
  if (!sel || sel.value !== "" || !sel.options.includes("|Choose a format")) throw new Error("format select does not start on 'Choose a format': " + JSON.stringify(sel));
  if (!genDisabled) throw new Error("Generate is available before a format is chosen");
  if (!(await bodyText()).includes("Studio does not guess the format")) throw new Error("the 'does not guess the format' message is missing");
  return "Output format select = " + JSON.stringify(sel) + "; Generate disabled";
});
await step("C2 Check service (loopback stand-in)", async () => { await clickText("Check service"); await waitText("answered Studio's identity check"); await shot("C2-lumina-service-checked.png"); return "checked"; });
let genOk;
await step("C3 explicit format png -> Generate -> returned bytes and identity", async () => {
  await fill("Output format", "png"); await sleep(300);
  const before = existsSync(luminaOut) ? readdirSync(luminaOut) : [];
  await clickText("Generate"); await waitText("A new png file was saved", "success", 150); await shot("C3-lumina-result-png.png");
  const added = readdirSync(luminaOut).filter((n) => !before.includes(n));
  if (added.length !== 1) throw new Error("expected one new file: " + JSON.stringify(added));
  const bytes = readFileSync(join(luminaOut, added[0])); const fileSha = sha(bytes);
  const m = readMock(); const expect = m.artifacts.pngfile;
  if (fileSha !== expect[1]) throw new Error(`sha mismatch file ${fileSha} vs stand-in ${expect[1]}`);
  const ui = await bodyText(); if (!ui.includes(fileSha) && !ui.includes(fileSha.slice(0, 12))) throw new Error("UI does not show the file's sha256 (full or prefix)");
  const imgSha = origSha["synthetic-image.png"];
  if (!m.uploads.some((u) => u.contains_input_image_bytes)) throw new Error("stand-in did not receive the exact input bytes: " + JSON.stringify(m.uploads));
  genOk = { file: added[0], sha: fileSha, requests: m.requests.map((r) => r.join(" ")).join(", "), uploads: m.uploads };
  return `new file ${added[0]} sha256 matches the stand-in artifact (${fileSha.slice(0, 16)}...); size ${bytes.length}; uploads seen by stand-in: ${JSON.stringify(m.uploads)}; input image sha256 ${imgSha}; stand-in multipart upload contains the exact input image bytes: ${m.uploads.some((u) => u.contains_input_image_bytes)}; stand-in requests: ${genOk.requests}`;
});
await step("C4 failure: format the service did not produce -> refused, nothing saved", async () => {
  const before = readdirSync(luminaOut).length;
  await fill("Output format", "3mf"); await clickText("Generate"); await waitText("Nothing was saved", "refusal", 150); await shot("C4-lumina-format-not-produced.png");
  if (readdirSync(luminaOut).length !== before) throw new Error("a file was saved on refusal"); return "refused; folder unchanged";
});
await step("C5 failure: non-local service address refused before anything is sent", async () => {
  await fill("Service address", "http://224.0.0.1:8000"); await fill("Output format", "png"); await clickText("Generate");
  await waitText("not on your own network", "refusal", 150); await shot("C5-lumina-non-local.png"); return "refused";
});
await step("C6 failure: service not running (closed loopback port)", async () => {
  const dead = await freePort(); await fill("Service address", `http://127.0.0.1:${dead}`); await clickText("Check service"); await sleep(3000);
  await shot("C6-lumina-service-down.png"); const t = (await mainText()).replace(/\s+/g, " ");
  const i = t.search(/The connection failed/); if (i < 0) throw new Error("no connection-failed message: " + t.slice(-220)); return t.slice(Math.max(0, i - 60), i + 40);
});
await step("C7 failure: missing image", async () => {
  await fill("Service address", svc.url); await fill("Image file path", "no-such-image.png"); await clickText("Generate"); await sleep(1800);
  await shot("C7-lumina-missing-image.png"); const t = (await mainText()).replace(/\s+/g, " "); const i = t.search(/not found|choose a file/i);
  if (i < 0) throw new Error("no clear message: " + t.slice(-200)); return t.slice(i - 20, i + 120);
});

// ------------------------------------------------------------------------------------------------------------
identity.finished = new Date().toISOString(); identity.page_errors = pageErrors.slice(0, 10);
identity.input_files_unchanged_after_run = Object.fromEntries(Object.entries(origSha).map(([f, h]) => [f, sha(readFileSync(join(inputs, f))) === h]));
writeFileSync(join(outRoot, "results-ac.json"), JSON.stringify({ identity, results, printer_requests: mockRequests, lumina: genOk }, null, 1));
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} steps passed; page errors: ${pageErrors.length}`);
socket.close(); printer.close(); cleanup();
try { rmSync(work, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 }); } catch { /* temp only */ }
process.exit(failed.length || pageErrors.length ? 1 : 0);
