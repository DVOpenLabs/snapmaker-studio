#!/usr/bin/env node
// Packaged-app check of the read-only project viewer under REAL WebKitGTK: the extracted Linux .deb's app binary,
// driven over WebDriver by tauri-driver + WebKitWebDriver. Linux only. Started by run-viewer-webkit.sh.
//
//   node viewer-webkit.mjs --app <app-binary> --project <copy of a .3mf> --out <folder> [--driver <tauri-driver>]
//
// Nothing here talks to a printer. The page's own view of the world is what is judged (WebDriver script results), not
// what this script expects. Home folder paths and the user name are scrubbed from everything written.
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, userInfo } from "node:os";
import { join } from "node:path";

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const APP = arg("--app");
const PROJECT = arg("--project");
const OUT = arg("--out", "./webkitgtk-evidence");
const DRIVER = arg("--driver", `${homedir()}/.cargo/bin/tauri-driver`);
const NATIVE = arg("--native-driver", "/usr/bin/WebKitWebDriver");
if (!APP || !PROJECT) { console.error("--app and --project are required"); process.exit(64); }
mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sha = (p) => createHash("sha256").update(readFileSync(p)).digest("hex");

// SCRUB_HOME / SCRUB_USER carry the real values when the runner changed HOME or runs as a mapped root user.
const scrub = (s) => {
  let t = String(s);
  for (const h of [process.env.SCRUB_HOME, homedir()]) if (h && h !== "/") t = t.split(h).join("~");
  for (const u of [process.env.SCRUB_USER, userInfo().username]) if (u && u !== "root") t = t.split(u).join("<user>");
  return t;
};
const scrubDeep = (v) => JSON.parse(scrub(JSON.stringify(v)));

/* ---------- processes ---------- */
const children = [];
let cleaned = false;
function cleanup() {
  if (cleaned) return;
  cleaned = true;
  for (const c of children) { try { process.kill(-c.pid, "SIGTERM"); } catch { try { c.kill("SIGTERM"); } catch { /* gone */ } } }
}
process.on("exit", cleanup);
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { cleanup(); process.exit(130); });

let driverLog = "";
let driverExit = null;
const driver = spawn(DRIVER, ["--native-driver", NATIVE, "--port", "4444"], { stdio: ["ignore", "pipe", "pipe"], detached: true });
children.push(driver);
driver.stdout.on("data", (d) => { driverLog += d; });
driver.stderr.on("data", (d) => { driverLog += d; });
driver.on("error", (e) => { driverExit = `could not start: ${e.message}`; });
driver.on("exit", (code, signal) => { driverExit = `exited early (code ${code}, signal ${signal})`; });

function failStartup(reason) {
  const text = scrub(`${reason}${driverExit ? ` — tauri-driver ${driverExit}` : ""}\n--- driver output (last 1500) ---\n${driverLog.slice(-1500) || "(none)"}`);
  console.error("FAIL  startup: " + text);
  writeFileSync(join(OUT, "results.json"), JSON.stringify({ startupFailure: text, results: [] }, null, 2));
  cleanup();
  process.exit(2);
}
let ready = false;
for (let i = 0; i < 50 && !ready && !driverExit; i++) { try { ready = (await fetch("http://127.0.0.1:4444/status")).ok; } catch { await sleep(200); } }
if (!ready) failStartup("tauri-driver did not answer on 127.0.0.1:4444 within 10 s");

/* ---------- a minimal W3C WebDriver client ---------- */
const WD = "http://127.0.0.1:4444";
async function wd(method, path, body) {
  const r = await fetch(WD + path, { method, headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`${method} ${path}: ${JSON.stringify(j.value ?? j).slice(0, 300)}`);
  return j.value;
}
const projectBefore = sha(PROJECT);
let created;
try { created = await wd("POST", "/session", { capabilities: { alwaysMatch: { "tauri:options": { application: APP, args: [PROJECT] } } } }); }
catch (e) { failStartup(`the WebDriver session could not be created: ${e.message}`); }
const S = `/session/${created.sessionId}`;
const exec = (script, ...args) => wd("POST", `${S}/execute/sync`, { script, args });
async function waitFor(fn, what, ms = 60000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { try { const v = await exec(`return (${fn})()`); if (v) return v; } catch { /* not yet */ } await sleep(250); }
  throw new Error("timed out waiting for " + what);
}
const shot = async (name) => { try { writeFileSync(join(OUT, `${name}.png`), Buffer.from(await wd("GET", `${S}/screenshot`), "base64")); return true; } catch { return false; } };

const K = { Shift: "", Control: "", Alt: "", Space: " ", Delete: "", Backspace: "", Enter: "", Escape: "", Left: "", Up: "", Right: "", Down: "" };
const pause = { type: "pause", duration: 0 };

/** Runs one device's actions with the modifier keys held for the whole of it, as W3C ticks so the page sees real events. */
async function withModifiers(mods, deviceId, deviceType, deviceActions, extra = {}) {
  const lead = mods.length;
  const keyActions = [
    ...mods.map((m) => ({ type: "keyDown", value: K[m] })),
    ...deviceActions.map(() => pause),
    ...[...mods].reverse().map((m) => ({ type: "keyUp", value: K[m] })),
  ];
  const devActions = [...Array(lead).fill(pause), ...deviceActions, ...Array(lead).fill(pause)];
  const device = { type: deviceType, id: deviceId, actions: devActions, ...extra };
  await wd("POST", `${S}/actions`, { actions: [{ type: "key", id: "kbd", actions: keyActions }, device] });
}
/** A pointer drag with a mouse button, modifier keys held. */
async function drag({ button = 0, mods = [], from, to, steps = 8 }) {
  const ptr = [{ type: "pointerMove", x: Math.round(from.x), y: Math.round(from.y), origin: "viewport" }, { type: "pointerDown", button }];
  for (let i = 1; i <= steps; i++) ptr.push({ type: "pointerMove", x: Math.round(from.x + ((to.x - from.x) * i) / steps), y: Math.round(from.y + ((to.y - from.y) * i) / steps), origin: "viewport", duration: 20 });
  ptr.push({ type: "pointerUp", button });
  await withModifiers(mods, "mouse", "pointer", ptr, { parameters: { pointerType: "mouse" } });
}
async function wheel(at, dy, mods = []) {
  await withModifiers(mods, "wheel", "wheel", [{ type: "scroll", x: Math.round(at.x), y: Math.round(at.y), deltaX: 0, deltaY: dy, origin: "viewport" }]);
}
async function press(...names) {
  const down = names.map((n) => ({ type: "keyDown", value: K[n] ?? n }));
  const up = [...names].reverse().map((n) => ({ type: "keyUp", value: K[n] ?? n }));
  await wd("POST", `${S}/actions`, { actions: [{ type: "key", id: "kbd", actions: [...down, ...up] }] });
}

/* ---------- checks ---------- */
const results = [];
const check = (name, ok, detail = "") => { const d = scrub(detail); results.push({ name, ok: !!ok, detail: d }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${d ? "  — " + d : ""}`); };
const info = {};

const LIST = `[...document.querySelectorAll('[data-testid="project-scene"] section[aria-labelledby="scene-objects"] li button')]`;
const listState = () => exec(`return ${LIST}.map((b) => ({ text: b.textContent.trim(), pressed: b.getAttribute("aria-pressed"), disabled: b.disabled }))`);
const listText = (s) => JSON.stringify(s.map((r) => r.text));
const canvasRect = () => exec(`const c=document.querySelector('[data-testid="scene-host"] canvas'); if(!c) return null; const r=c.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height,cw:c.width,ch:c.height}`);
const alertCount = () => exec(`return document.querySelectorAll('[data-testid="project-scene"] [role="alert"]').length`);

let fatal = null;
try {
  await wd("POST", `${S}/window/rect`, { width: 1280, height: 1000, x: 0, y: 0 }).catch(() => {});
  info.userAgent = await exec(`return navigator.userAgent`);
  console.log("web view:", info.userAgent);
  check("the page is a real WebKitGTK web view", /AppleWebKit/.test(info.userAgent) && !/Chrome|Edg\//.test(info.userAgent), info.userAgent);

  // WebGL availability inside this WebKitGTK, independent of the app's own viewer.
  info.webgl = await exec(`const out={}; for (const t of ["webgl2","webgl"]) { const c=document.createElement("canvas"); const gl=c.getContext(t); out[t]=!!gl;
    if (gl && !out.renderer) { const e=gl.getExtension("WEBGL_debug_renderer_info"); out.renderer = e ? String(gl.getParameter(e.UNMASKED_RENDERER_WEBGL)) : String(gl.getParameter(gl.RENDERER)); out.vendor = e ? String(gl.getParameter(e.UNMASKED_VENDOR_WEBGL)) : String(gl.getParameter(gl.VENDOR)); out.version = String(gl.getParameter(gl.VERSION)); } }
    return out`);
  console.log("webgl:", JSON.stringify(info.webgl));
  check("WebGL2 context can be created in this WebKitGTK", info.webgl.webgl2 === true, JSON.stringify(info.webgl));
  info.softwareRenderer = /llvmpipe|swiftshader|software|softpipe/i.test(info.webgl.renderer || "");

  // The project was handed to the app on its command line; the view appears once the Doctor has finished.
  // The app opened it (get_launch_file -> session file); the project page is the workspace route.
  await waitFor(`() => document.querySelector("#brand-splash") === null && document.body.innerText.length > 50`, "the app to finish starting", 60000);
  await sleep(2000);
  await exec(`window.history.pushState({}, "", "/workspace"); window.dispatchEvent(new PopStateEvent("popstate"));`);
  try {
    await waitFor(`() => document.querySelector('[data-testid="project-scene"]')`, "the 3D view panel (project opened from the command line)", 90000);
  } catch (e) {
    info.pageAtTimeout = await exec(`return { path: location.pathname, text: document.body.innerText.slice(0, 600) }`);
    throw e;
  }
  info.headingText = await exec(`const h=document.querySelector('[data-testid="project-scene"] h3'); return h ? h.textContent : null`);
  check("the '3D view of this project' panel appears", info.headingText === "3D view of this project", info.headingText);

  await waitFor(`() => document.querySelector('[data-testid="scene-host"] canvas') && document.querySelectorAll('[data-testid="project-scene"] section[aria-labelledby="scene-objects"] li button').length > 0`, "canvas and object list", 90000);
  await sleep(2500); // let the first frames draw
  const rect = await canvasRect();
  info.canvas = rect;
  check("a canvas with a real size is drawn", rect && rect.w >= 100 && rect.h >= 100 && rect.cw > 0 && rect.ch > 0, JSON.stringify(rect));
  const alerts = await exec(`return [...document.querySelectorAll('[data-testid="project-scene"] [role="alert"]')].map((a) => a.textContent.trim().slice(0,120))`);
  check("no graphics-failure alert shows", alerts.length === 0, JSON.stringify(alerts));
  await shot("01-viewer-shown");

  // Informational: a WebGL canvas usually reads back blank outside a frame callback, so this is reported, not judged.
  info.canvasReadback = await exec(`const c=document.querySelector('[data-testid="scene-host"] canvas'); try { const t=document.createElement("canvas"); t.width=c.width; t.height=c.height; const x=t.getContext("2d"); x.drawImage(c,0,0); const d=x.getImageData(0,0,t.width,t.height).data; let nz=0; for (let i=0;i<d.length;i+=4) if (d[i]||d[i+1]||d[i+2]) nz++; return { pixels: d.length/4, nonBlack: nz }; } catch (e) { return { error: String(e) }; }`);

  const list0 = await listState();
  check("the object list has rows", list0.length > 0, JSON.stringify(list0.map((r) => r.text)));
  const cams = await exec(`return [...document.querySelectorAll('[data-testid="project-scene"] [role="group"][aria-label="Camera views"] button')].map((b) => ({ text: b.textContent.trim(), disabled: b.disabled }))`);
  info.cameraButtons = cams;
  check("camera buttons exist and are enabled", cams.length >= 2 && cams.every((b) => !b.disabled), JSON.stringify(cams));
  const firstCam = cams.find((b) => !/Slope/.test(b.text));
  await exec(`[...document.querySelectorAll('[data-testid="project-scene"] [role="group"][aria-label="Camera views"] button')].find((b)=>b.textContent.trim()===arguments[0]).click()`, firstCam.text);
  await sleep(800);
  check("pressing a camera button leaves no alert and the canvas stays", (await canvasRect()) !== null && (await alertCount()) === 0);

  // Selecting an object from the list marks its row.
  const firstEnabled = list0.findIndex((r) => !r.disabled);
  await exec(`${LIST}[arguments[0]].click()`, firstEnabled);
  await sleep(500);
  const afterSelect = await listState();
  check("selecting an object marks its row (aria-pressed)", afterSelect[firstEnabled]?.pressed === "true" && afterSelect.filter((r) => r.pressed === "true").length === 1, JSON.stringify(afterSelect.map((r) => r.pressed)));
  await shot("02-object-selected");

  // Mouse drags with modifiers, wheel and keys must leave the object list unchanged.
  // Each phase also records whether the picture in the canvas changed (so the input is known to have reached the viewer)
  // and how far the page scrolled.
  const hostImage = async () => {
    const el = await wd("POST", `${S}/element`, { using: "css selector", value: '[data-testid="scene-host"]' });
    const png = await wd("GET", `${S}/element/${Object.values(el)[0]}/screenshot`);
    return { sha: createHash("sha256").update(Buffer.from(png, "base64")).digest("hex").slice(0, 16), png };
  };
  const scrolls = () => exec(`const o={window:Math.round(window.scrollY)}; for (const e of document.querySelectorAll("*")) if (e.scrollTop>0) o[e.tagName+"."+String(e.className).slice(0,30)]=Math.round(e.scrollTop); return o`);
  const toHost = async () => { await exec(`document.querySelector('[data-testid="scene-host"]').scrollIntoView({block:"center"})`); await sleep(400); const r = await canvasRect(); return { x: r.x + r.w / 2, y: r.y + r.h / 2 }; };
  const phases = {};
  const listBefore = await listState();
  let driven = 0;

  let center = await toHost();
  const img0 = await hostImage();
  for (const button of [0, 1, 2]) {
    for (const mods of [[], ["Shift"], ["Control"], ["Alt"], ["Shift", "Control"], ["Shift", "Alt"]]) {
      await drag({ button, mods, from: center, to: { x: center.x + 70, y: center.y + 20 } });
      driven++;
    }
  }
  // Space held across a drag.
  await withModifiers(["Space"], "mouse", "pointer", [
    { type: "pointerMove", x: Math.round(center.x), y: Math.round(center.y), origin: "viewport" }, { type: "pointerDown", button: 0 },
    { type: "pointerMove", x: Math.round(center.x - 60), y: Math.round(center.y - 25), origin: "viewport", duration: 40 }, { type: "pointerUp", button: 0 },
  ], { parameters: { pointerType: "mouse" } });
  driven++;
  await sleep(700);
  const img1 = await hostImage();
  phases.drags = { actions: 19, pictureChanged: img0.sha !== img1.sha, scroll: await scrolls(), listUnchanged: listText(await listState()) === listText(listBefore) };
  writeFileSync(join(OUT, "03a-after-drags.png"), Buffer.from(img1.png, "base64"));
  await shot("03a-window-after-drags");

  center = await toHost();
  for (const mods of [[], ["Control"], ["Alt"], ["Shift"]]) { await wheel(center, -200, mods); await wheel(center, 200, mods); driven += 2; }
  await sleep(700);
  const img2 = await hostImage();
  phases.wheel = { actions: 8, pictureChanged: img1.sha !== img2.sha, scroll: await scrolls(), listUnchanged: listText(await listState()) === listText(listBefore) };

  center = await toHost();
  const keys = [["Delete"], ["Backspace"], ["r"], ["s"], ["m"], ["p"], ["c"], ["x"], ["b"], ["f"], ["Enter"], ["Left"], ["Right"], ["Up"], ["Down"], ["Control", "z"], ["Control", "y"], ["Control", "c"], ["Control", "v"], ["Control", "a"], ["Escape"]];
  for (const k of keys) { await press(...k); driven++; }
  await sleep(700);
  await toHost();
  const img3 = await hostImage();
  phases.keys = { actions: keys.length, pictureChanged: img2.sha !== img3.sha, scroll: await scrolls(), listUnchanged: listText(await listState()) === listText(listBefore) };
  writeFileSync(join(OUT, "03b-after-keys.png"), Buffer.from(img3.png, "base64"));
  await shot("03b-window-after-keys");
  info.inputPhases = phases;
  info.inputActionsSent = driven;

  const afterInput = await listState();
  info.listBeforeInput = listBefore.map((r) => r.text);
  info.pressedBeforeInput = listBefore.map((r) => r.pressed);
  info.pressedAfterInput = afterInput.map((r) => r.pressed);
  check("drags with and without modifiers, wheel and key presses leave the object list unchanged", listText(listBefore) === listText(afterInput) && listBefore.length === afterInput.length, `${driven} input actions; rows ${listBefore.length} -> ${afterInput.length}`);
  check("the input reached the viewer: the picture changed after the drags, so 'unchanged' is not vacuous", phases.drags.pictureChanged, JSON.stringify(phases));
  check("after the input run: no alert, canvas still present", (await alertCount()) === 0 && (await canvasRect()) !== null);
  await shot("03-after-input");

  // What the page itself requested (the namespace in run-viewer-webkit.sh is the real isolation; this is the page's view).
  info.resourceHosts = [...new Set(await exec(`return performance.getEntriesByType("resource").map((e) => e.name).filter((n) => !/^(data|blob):/.test(n)).map((n) => { try { return new URL(n).host; } catch { return n; } })`))];
  const nonLoop = info.resourceHosts.filter((h) => h !== "" && !/^(127\.0\.0\.1|localhost|\[::1\]|tauri\.localhost|ipc\.localhost)(:\d+)?$/.test(h));
  check("the page requested nothing from a non-loopback host", nonLoop.length === 0, JSON.stringify({ hostsSeen: info.resourceHosts, nonLoopback: nonLoop }));

  // Leaving the page removes the canvas.
  await exec(`window.history.pushState({}, "", "/help"); window.dispatchEvent(new PopStateEvent("popstate"));`);
  await sleep(1500);
  const gone = await exec(`return { scene: !!document.querySelector('[data-testid="project-scene"]'), canvases: document.querySelectorAll("canvas").length, path: location.pathname }`);
  check("leaving the page removes the viewer and its canvas", !gone.scene && gone.canvases === 0, JSON.stringify(gone));
  await shot("04-after-leaving");
} catch (e) {
  fatal = e;
  check("the run completed without a harness error", false, String(e && e.message || e));
  await shot("failure");
} finally {
  try { await wd("DELETE", S); } catch { /* already closed */ }
  cleanup();
}
const projectAfter = sha(PROJECT);
check("the project file's sha256 is unchanged", projectBefore === projectAfter, `${projectBefore.slice(0, 16)}… -> ${projectAfter.slice(0, 16)}…`);
const failed = results.filter((r) => !r.ok).length;
writeFileSync(join(OUT, "results.json"), JSON.stringify(scrubDeep({ info, results, projectSha256: { before: projectBefore, after: projectAfter }, driverLog: driverLog.slice(-2000) }), null, 2));
console.log(`${results.length - failed}/${results.length} viewer checks passed`);
process.exit(failed || fatal ? 1 : 0);
