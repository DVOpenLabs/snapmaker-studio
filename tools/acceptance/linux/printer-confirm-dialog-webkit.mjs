#!/usr/bin/env node
// Integrated check of the printer-action confirmation prompt in the REAL Studio app on Linux: the packaged Tauri
// build, its WebKitGTK web view, driven over WebDriver by tauri-driver. Linux only.
//
//   node tools/acceptance/linux/printer-confirm-dialog-webkit.mjs --app /usr/bin/snapmaker-studio-desktop --out <folder>
//
// Intended to be started by printer-confirm-dialog-webkit.sh, which runs it as an ordinary user inside a network
// namespace that has ONLY a loopback interface, so nothing here can reach a real printer or any other machine.
//
// What it starts, all stopped again at the end: tauri-driver (WebDriver), the app under it (with its own engine
// sidecar, a throwaway HOME and data folder), and a loopback Moonraker look-alike on 127.0.0.1:7125 that records the
// requests it receives. Printer calls are mocked; the app is the real one.
//
// It writes one JSON record per check to <out>/results.json and screenshots (taken with the app's own window grab via
// WebDriver) to <out>/*.png. Each check is judged on what the page reports through WebDriver, not on what the
// script expects to have happened.
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import http from "node:http";
import { join } from "node:path";

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const APP = arg("--app", "/usr/bin/snapmaker-studio-desktop");
const OUT = arg("--out", "./webkit-dialog-evidence");
const DRIVER = arg("--driver", `${process.env.HOME}/.cargo/bin/tauri-driver`);
const NATIVE = arg("--native-driver", "/usr/bin/WebKitWebDriver");
mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---------- the loopback printer ---------- */
const calls = [];          // requests since the last deliberate reset between scenarios
const allCalls = [];       // every request the look-alikes received, in order, never reset
const seenHosts = new Set();
const printers = {
  "127.0.0.1": { state: "printing", up: true, delayMs: 700 },
  "127.0.0.2": { state: "printing", up: true, delayMs: 0 },
};
const servers = [];
for (const host of Object.keys(printers)) {
  const printer = printers[host];
  const server = http.createServer((req, res) => {
    const send = (code, body) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
    seenHosts.add(req.socket.localAddress || host);   // the address the connection really arrived on
    if (!printer.up) { res.destroy(); return; }
    const path = (req.url || "").split("?")[0];
    if (req.method === "POST") {
      calls.push({ host, method: "POST", path: req.url });
      allCalls.push({ host, method: "POST", path: req.url });
      const finish = () => send(200, { result: "ok" });
      return printer.delayMs ? setTimeout(finish, printer.delayMs) : finish();
    }
    if (path === "/printer/objects/query") {
      return send(200, { result: { status: {
        print_stats: { state: printer.state, filename: "example.gcode", print_duration: 100, total_duration: 120, info: { current_layer: 3, total_layer: 40 } },
        heater_bed: { temperature: 60, target: 60 }, virtual_sdcard: { progress: 0.2 }, display_status: {}, gcode_move: { speed_factor: 1, extrude_factor: 1 },
      } } });
    }
    if (path === "/server/info") return send(200, { result: { klippy_state: "ready", moonraker_version: "look-alike" } });
    return send(200, { result: {} });
  });
  server.on("clientError", () => {});
  server.listen(7125, host);
  servers.push(server);
}
const callsMatching = (needle, host) => calls.filter((c) => c.path.includes(needle) && (!host || c.host === host)).length;

/* ---------- processes ---------- */
const children = [];
let cleaned = false;
function cleanup() {
  if (cleaned) return;
  cleaned = true;
  for (const c of children) { try { process.kill(-c.pid, "SIGTERM"); } catch { try { c.kill("SIGTERM"); } catch { /* gone */ } } }
  for (const s of servers) { try { s.close(); } catch { /* gone */ } }
}
process.on("exit", cleanup);
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { cleanup(); process.exit(130); });

let driverLog = "";
let driverExit = null;
const driver = spawn(DRIVER, ["--native-driver", NATIVE, "--port", "4444"], { stdio: ["ignore", "pipe", "pipe"], detached: true });
children.push(driver);
driver.stdout.on("data", (d) => { driverLog += d; });
driver.stderr.on("data", (d) => { driverLog += d; });
driver.on("error", (e) => { driverExit = `could not start ${DRIVER}: ${e.message}`; });
driver.on("exit", (code, signal) => { driverExit = `exited early (code ${code}, signal ${signal})`; });

/** Stops the run with the reason and the driver's own output, and records it where the evidence goes. */
function failStartup(reason) {
  const text = `${reason}${driverExit ? ` — tauri-driver ${driverExit}` : ""}\n--- tauri-driver output (last 1500 chars) ---\n${driverLog.slice(-1500) || "(none)"}`;
  console.error("FAIL  startup: " + text);
  try { writeFileSync(join(OUT, "results.json"), JSON.stringify({ app: APP, startupFailure: text, results: [], calls }, null, 2)); }
  catch (e) { console.error("(could not write results.json: " + e.message + ")"); }
  cleanup();
  process.exit(2);
}

let driverReady = false;
for (let i = 0; i < 50 && !driverReady && !driverExit; i++) {
  try { const r = await fetch("http://127.0.0.1:4444/status"); driverReady = r.ok; } catch { await sleep(200); }
}
if (!driverReady) failStartup(`tauri-driver did not answer on 127.0.0.1:4444 within 10 s (driver ${DRIVER}, native driver ${NATIVE})`);

/* ---------- a minimal W3C WebDriver client ---------- */
const WD = "http://127.0.0.1:4444";
async function wd(method, path, body) {
  const r = await fetch(WD + path, { method, headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`${method} ${path}: ${JSON.stringify(j.value ?? j).slice(0, 300)}`);
  return j.value;
}
let created;
try { created = await wd("POST", "/session", { capabilities: { alwaysMatch: { "tauri:options": { application: APP } } } }); }
catch (e) { failStartup(`the WebDriver session for ${APP} could not be created: ${e.message}`); }
const sid = created.sessionId;
const S = `/session/${sid}`;
const exec = (script, ...args) => wd("POST", `${S}/execute/sync`, { script, args });
const KEY = { Tab: "", Escape: "", Enter: "", Shift: "" };
async function press(...keys) {
  const actions = [];
  for (const k of keys) actions.push({ type: "keyDown", value: KEY[k] ?? k });
  for (const k of [...keys].reverse()) actions.push({ type: "keyUp", value: KEY[k] ?? k });
  await wd("POST", `${S}/actions`, { actions: [{ type: "key", id: "kbd", actions }] });
}
async function waitFor(fn, what, ms = 20000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { try { const v = await exec(`return (${fn})()`); if (v) return v; } catch { /* not yet */ } await sleep(150); }
  throw new Error("timed out waiting for " + what);
}
const shot = async (name) => {
  try { const png = await wd("GET", `${S}/screenshot`); writeFileSync(join(OUT, `${name}.png`), Buffer.from(png, "base64")); } catch { /* evidence only */ }
};

/* ---------- checks ---------- */
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`); };

const FIND = {
  dialog: `document.querySelector("dialog[open]")`,
  cancelPrintButton: `[...document.querySelectorAll("button")].find((b) => /Cancel print/.test(b.textContent))`,
};
const dialogOpen = () => exec(`return !!document.querySelector("dialog[open]")`);
const active = () => exec(`const a=document.activeElement; return a ? (a.textContent||a.tagName).trim().slice(0,40) : null`);
const focusState = () => exec(`const a=document.activeElement; const body = a===document.body||a===document.documentElement;
  const isDialog = a && a.tagName === "DIALOG";   // WebKit lets Tab land on the dialog box itself between its buttons
  return { inside: !!(a && a.closest && a.closest("dialog")), onPage: body, text: body ? "BODY" : isDialog ? "DIALOG" : (a.textContent||a.tagName||"").trim().slice(0,30) }`);
async function openCancelPrompt() {
  await waitFor(`() => ${FIND.cancelPrintButton}`, "the Cancel print button");
  await exec(`(${FIND.cancelPrintButton}).focus()`);
  await press("Enter");
  await waitFor(`() => !!document.querySelector("dialog[open]")`, "the prompt", 5000);
}
const clickYesThreeTimes = () => exec(`const b=[...document.querySelectorAll("dialog button")].find((x)=>/Yes, do it/.test(x.textContent)); b.click(); b.click(); b.click();`);
async function setHostAndConnect(host) {
  await exec(`const i=document.querySelector("input"); const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set;
    set.call(i, arguments[0]); i.dispatchEvent(new Event("input",{bubbles:true}));`, host);
  await sleep(150);
  await exec(`const i=document.querySelector("input"); i.dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",bubbles:true}));`);
}

let fatal = null;
try {
  await wd("POST", `${S}/window/rect`, { width: 1280, height: 900, x: 0, y: 0 }).catch(() => {});
  const ua = await exec(`return navigator.userAgent`);
  const versions = await exec(`return { engine: navigator.userAgent, dialog: typeof HTMLDialogElement, showModal: typeof HTMLDialogElement.prototype.showModal }`);
  console.log("web view:", ua);
  check("the page is a real WebKitGTK web view with native <dialog>.showModal()", /AppleWebKit/.test(ua) && versions.showModal === "function", ua);

  // The saved printer address has to be the loopback one BEFORE the app first looks at it (its default is U1.local).
  await exec(`localStorage.setItem("theme","dark"); localStorage.setItem("u1Host","127.0.0.1");`);
  await exec(`location.reload()`);
  await sleep(2500);
  await exec(`window.history.pushState({}, "", "/printers"); window.dispatchEvent(new PopStateEvent("popstate"));`);
  await waitFor(`() => ${FIND.cancelPrintButton}`, "printer controls for the loopback printer", 30000);
  check("printer controls appear for the loopback printer while it is printing", true);

  /* identity, focus, containment, Escape, restoration */
  await openCancelPrompt();
  const info = await exec(`const d=document.querySelector("dialog[open]"); const lab=document.getElementById(d.getAttribute("aria-labelledby")); const desc=document.getElementById(d.getAttribute("aria-describedby"));
    const r=d.getBoundingClientRect(); return { role:d.getAttribute("role"), title: lab&&lab.textContent, desc: desc&&desc.textContent, rect:{x:r.x,y:r.y,w:r.width,h:r.height}, vw:innerWidth, vh:innerHeight }`);
  check("opens as an alertdialog named by its title", info.role === "alertdialog" && info.title === "Cancel this print?", `${info.role} / ${info.title}`);
  check("the warning and the printer are in its description", /resume a cancelled print/.test(info.desc || "") && /Printer: 127\.0\.0\.1/.test(info.desc || ""), (info.desc || "").slice(0, 120));
  check("initial focus is on Cancel", (await active()) === "Cancel", await active());
  check("the prompt is centered in the window", Math.abs(info.rect.x + info.rect.w / 2 - info.vw / 2) < 60 && Math.abs(info.rect.y + info.rect.h / 2 - info.vh / 2) < 60, JSON.stringify(info.rect) + ` in ${info.vw}x${info.vh}`);
  await shot("dialog-open");

  const trail = [];
  let reachedBackground = false;
  for (let i = 0; i < 6; i++) { await press("Tab"); const s = await focusState(); trail.push(s.text); if (!s.inside && !s.onPage) reachedBackground = true; }
  for (let i = 0; i < 6; i++) { await press("Shift", "Tab"); const s = await focusState(); trail.push(s.text); if (!s.inside && !s.onPage) reachedBackground = true; }
  check("six Tabs forward and six Shift+Tabs backward never focus a control on the page behind the prompt", !reachedBackground, trail.join(" | "));
  check("the prompt's own buttons are the only controls focus visited", trail.every((t) => ["Cancel", "Yes, do it", "DIALOG", "BODY", "HTML"].includes(t)), [...new Set(trail)].join(", "));
  const behind = await exec(`const b=document.querySelector("input"); const r=b.getBoundingClientRect(); return document.elementFromPoint(r.x+4, r.y+4)===b`);
  check("the connect field behind the prompt cannot be clicked", !behind);

  await press("Escape");
  await sleep(400);
  check("Escape closes the prompt", !(await dialogOpen()));
  check("Escape sent nothing to the printer", callsMatching("cancel") === 0);
  check("focus returns to the Cancel print button", (await active() || "").startsWith("Cancel print"), await active());

  /* exactly once, even with Escape pressed twice while the request runs */
  await openCancelPrompt();
  await clickYesThreeTimes();
  await press("Escape");
  await press("Escape");
  await sleep(250);
  check("Escape pressed twice while the request is running leaves the prompt on screen", await dialogOpen());
  await waitFor(`() => !document.querySelector("dialog[open]")`, "the prompt to close after the request", 10000);
  check("three rapid confirms send exactly one cancel request", callsMatching("cancel") === 1, JSON.stringify(calls.filter((c) => /cancel/.test(c.path))));
  check("the prompt closes when the request finishes", true);

  /* the printer stops answering while the prompt is open */
  printers["127.0.0.1"].state = "printing"; calls.length = 0;
  await openCancelPrompt();
  printers["127.0.0.1"].up = false;
  await waitFor(`() => !document.querySelector("dialog[open]")`, "the prompt to be withdrawn", 30000);
  check("the prompt is withdrawn when the printer stops answering", true);
  check("nothing was sent to the printer that went away", calls.length === 0);

  /* the print finishes while the prompt is open */
  printers["127.0.0.1"].up = true; printers["127.0.0.1"].state = "printing";
  await openCancelPrompt();
  printers["127.0.0.1"].state = "complete";
  await waitFor(`() => !document.querySelector("dialog[open]")`, "the prompt to be withdrawn", 30000);
  check("the prompt is withdrawn when the print finishes", true);
  check("no cancel was sent for a print that had already ended", callsMatching("cancel") === 0);
  await sleep(300);
  check("focus lands on the card heading after the Cancel button disappeared", /Printer controls/i.test(await active() || ""), await active());

  /* the person points the app at a different printer while the prompt is open */
  printers["127.0.0.1"].state = "printing"; calls.length = 0;
  await openCancelPrompt();
  await setHostAndConnect("127.0.0.2");
  await waitFor(`() => !document.querySelector("dialog[open]")`, "the prompt to be withdrawn after a printer change", 20000);
  check("the prompt is withdrawn when the printer address changes", true);
  check("nothing was sent to either printer", callsMatching("cancel") === 0 && callsMatching("M112") === 0, JSON.stringify(calls));

  /* emergency stop asks first too */
  await setHostAndConnect("127.0.0.1");
  await waitFor(`() => [...document.querySelectorAll("button")].some((b) => /^Emergency stop$/.test(b.textContent.trim()))`, "Emergency stop", 20000);
  await exec(`[...document.querySelectorAll("button")].find((b)=>/^Emergency stop$/.test(b.textContent.trim())).focus()`);
  await press("Enter");
  await waitFor(`() => !!document.querySelector("dialog[open]")`, "the emergency stop prompt", 5000);
  const text = await exec(`return document.querySelector("dialog[open]").innerText`);
  check("emergency stop asks first and names the printer", /Printer: 127\.0\.0\.1/.test(text) && callsMatching("M112") === 0, text.replace(/\n/g, " | ").slice(0, 120));
  await press("Escape");
  await sleep(400);
  check("dismissing emergency stop sends nothing", !(await dialogOpen()) && callsMatching("M112") === 0);
  await shot("dialog-closed");

  // Now actually confirm it. Three rapid presses of "Yes, do it" must still send exactly one M112, to the printer shown.
  await exec(`[...document.querySelectorAll("button")].find((b)=>/^Emergency stop$/.test(b.textContent.trim())).focus()`);
  await press("Enter");
  await waitFor(`() => !!document.querySelector("dialog[open]")`, "the emergency stop prompt again", 5000);
  const before = callsMatching("M112");
  await clickYesThreeTimes();
  await waitFor(`() => !document.querySelector("dialog[open]")`, "the emergency stop prompt to close after it was sent", 15000);
  await sleep(500);
  const stops = calls.filter((c) => /M112/.test(c.path));
  check("confirming emergency stop sends exactly one M112, to the printer named in the prompt",
    before === 0 && stops.length === 1 && stops[0].host === "127.0.0.1" && stops[0].method === "POST", JSON.stringify(stops));
  check("nothing was sent to the other printer", calls.every((c) => c.host === "127.0.0.1"), JSON.stringify(calls.map((c) => c.host)));

  // The network namespace is what keeps everything off a real printer; this records that the look-alikes only ever
  // saw connections on their own loopback addresses, and that something did connect (an empty set would prove nothing).
  check("every connection the look-alike printers received arrived on a loopback address",
    seenHosts.size > 0 && [...seenHosts].every((h) => ["127.0.0.1", "127.0.0.2"].includes(h)), JSON.stringify([...seenHosts]));
} catch (e) {
  fatal = e;
  check("the run completed without a harness error", false, String(e && e.message || e));
  await shot("failure");
} finally {
  try { await wd("DELETE", S); } catch { /* already closed */ }
  cleanup();
}
const failed = results.filter((r) => !r.ok).length;
writeFileSync(join(OUT, "results.json"), JSON.stringify({ app: APP, results, callsSinceLastReset: calls, allPosts: allCalls, driverLog: driverLog.slice(-2000) }, null, 2));
console.log(`${results.length - failed}/${results.length} integrated WebKitGTK checks passed`);
process.exit(failed || fatal ? 1 : 0);
