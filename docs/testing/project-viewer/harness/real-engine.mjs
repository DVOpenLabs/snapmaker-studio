// Runs the REAL scene client (src/lib/scene.ts, in Edge, over real loopback HTTP) against the REAL engine process, on the
// repository example projects only. It records plainly what was covered and what was not in real-engine-results.json.
//
// Covered: session + start + status + result round trip; cancel round trip on a large project; a late start for an abandoned
// request delivered AFTER a newer one (replayed by hand against the real /scene/start route); SESSION_EXPIRED after a fresh
// engine process (same port, new token); SESSION_LIMIT; job credentials (status/result need the session's client_id).
// Not covered here: see "notCovered" in the output. No printer is contacted.
import { start, stage, spawnEngine, stopEngine, launch, loopbackOnly, cleanup, sleep, sha, OUT_DIR, FIXTURES, freePort } from "./harness.mjs";
import { writeFileSync } from "node:fs";
import { join } from "node:path";

const P = await freePort();
const { UI, handshake, backend: engineA } = await start({ enginePort: P });
const files = {
  showcase: stage("demo_u1_showcase.3mf", FIXTURES),
  cube: stage("sample_cube_U1.3mf", FIXTURES),
  offbed: stage("demo_offplate_foreign.3mf", FIXTURES),
  grid: join(FIXTURES, "grid-100k.3mf"), // made by mkfx.py: the largest scene, so a cancel can land while it works
};
const before = Object.fromEntries(Object.entries(files).map(([k, p]) => [k, sha(p)]));
const browser = await launch();
const failures = [];
const log = (m) => console.error(`[real-engine] ${m}`);
const expect = (ok, what) => { if (!ok) failures.push(what); return ok; };
const scenarios = {};
let engineB = null;

const wire = [];
const entries = new WeakMap();
const compact = (e) => `${e.route}${e.body?.seq !== undefined ? ` seq=${e.body.seq}` : ""}${e.body?.job_id ? ` ${e.body.job_id.slice(0, 6)}` : ""} -> ${e.status ?? "no answer"}${typeof e.reply?.error === "string" ? ` ${e.reply.error}` : typeof e.reply?.state === "string" ? ` ${e.reply.state}` : ""}`;

try {
  const ctx = await browser.newContext({ viewport: { width: 1000, height: 800 }, serviceWorkers: "block" });
  loopbackOnly(ctx, P, []);
  const page = await ctx.newPage();
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (String(u.port) !== String(P) || !u.pathname.startsWith("/scene/") || r.method() !== "POST") return;
    let body = null; try { body = JSON.parse(r.postData() || "null"); } catch {}
    const e = { route: u.pathname.slice(7), body, status: null, reply: null };
    entries.set(r, e); wire.push(e);
  });
  page.on("response", async (r) => {
    const e = entries.get(r.request());
    if (!e) return;
    e.status = r.status();
    try { e.reply = JSON.parse(await r.text()); } catch {}
  });
  log("page");
  await page.goto(`${UI}/help?api=${P}:${handshake.token}`);
  await page.locator("#brand-splash").waitFor({ state: "detached", timeout: 30000 });
  await page.evaluate(async () => {
    const api = await import("/src/api.ts");
    const scene = await import("/src/lib/scene.ts");
    const call = async (base, token, route, body, signal) => {
      const r = await fetch(`${base}/scene/${route}`, { method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": token }, body: JSON.stringify(body), signal });
      let b = null; try { b = await r.json(); } catch {}
      return { status: r.status, body: b };
    };
    window.__h = {
      scene,
      raw: async (route, body) => { const c = await api.engineConnection(); return call(c.base, c.token, route, body); },
      rawAt: (base, token, route, body) => call(base, token, route, body),
      tx: (base, token) => (route, body, signal) => call(base, token, route, body, signal),
    };
  });
  const slice = (mark) => wire.slice(mark);
  const waitFor = async (fn, ms = 8000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(25); } return false; };

  log("1 round trip");
  // ---- 1. round trip -----------------------------------------------------------------------------------------------
  {
    const mark = wire.length;
    const out = await page.evaluate(async (path) => {
      const { loadScene, currentSceneClientId } = window.__h.scene;
      const scene = await loadScene(path, { signal: new AbortController().signal });
      return { schema: scene.schema, nodes: scene.nodes.length, meshes: scene.meshes.length, client: currentSceneClientId() };
    }, files.showcase);
    const w = slice(mark);
    const startE = w.find((e) => e.route === "start");
    const ok =
      expect(out.schema === "scene/1" && out.nodes > 0, "round trip returned a scene") &&
      expect(w[0].route === "session" && w[0].status === 200, "the first call opens a session") &&
      expect(startE?.body.client_id === out.client && startE.body.seq === 1, "start carries the session id and seq 1") &&
      expect(w.filter((e) => e.route === "status" || e.route === "result").every((e) => e.body.client_id === out.client && e.status === 200), "every status and result carries the session client id and is answered 200") &&
      expect(w.at(-1).route === "result" && w.at(-1).status === 200, "ends with a 200 result");
    scenarios.roundTrip = { covered: true, passed: ok, observed: w.map(compact), scene: out };
  }

  log("2 cancel round trip");
  // ---- 2. cancel round trip on a large project ---------------------------------------------------------------------
  {
    const mark = wire.length;
    const out = await page.evaluate(async (path) => {
      const { loadScene } = window.__h.scene;
      const ac = new AbortController();
      return loadScene(path, { signal: ac.signal, onProgress: () => ac.abort() }).then(() => "loaded", (e) => e.name);
    }, files.grid);
    await waitFor(() => slice(mark).some((e) => e.route === "cancel" && e.status !== null));
    const w = slice(mark);
    const startE = w.find((e) => e.route === "start"), cancelE = w.find((e) => e.route === "cancel");
    const job = startE?.reply?.job_id, client = startE?.body.client_id;
    await sleep(600);
    const after = job ? await page.evaluate(([j, c]) => window.__h.raw("status", { job_id: j, client_id: c }), [job, client]) : null;
    const foreign = job ? await page.evaluate(([j]) => window.__h.raw("status", { job_id: j, client_id: "not-this-session" }), [job]) : null;
    const missing = job ? await page.evaluate(([j]) => window.__h.raw("status", { job_id: j }), [job]) : null;
    const ok =
      expect(out === "AbortError", "an aborted load rejects with AbortError") &&
      expect(cancelE && cancelE.status === 200 && cancelE.body.client_id === client && cancelE.body.request_id === startE.body.request_id && cancelE.body.seq === startE.body.seq && Object.keys(cancelE.body).length === 3, "the cancel goes by client_id, request_id and seq and is answered 200") &&
      expect(after?.body?.state === "cancelled", `the cancelled job is cancelled (observed ${after?.body?.state})`) &&
      expect(foreign?.status === 404 && foreign.body.error === "EXPIRED" && missing?.status === 404 && missing.body.error === "EXPIRED", "status with a foreign or missing client id is 404 EXPIRED");
    scenarios.cancelRoundTrip = { covered: true, passed: ok, observed: w.map(compact), jobStateAfterCancel: after?.body?.state, foreignClient: foreign && [foreign.status, foreign.body.error], missingClient: missing && [missing.status, missing.body.error] };
  }

  log("3 abandoned A after B");
  // ---- 3. abandoned A delivered after B, by hand, against the real routes -----------------------------------------
  {
    const mark = wire.length;
    let release = () => {}; const gate = new Promise((r) => { release = r; });
    let armed = true; let held = null;
    await page.route(`http://127.0.0.1:${P}/scene/start`, async (route) => {
      let body = {}; try { body = JSON.parse(route.request().postData() || "{}"); } catch {}
      if (armed && body.path === files.offbed) { held = body; await gate; return route.abort(); } // A never leaves the browser
      return route.fallback();
    });
    await page.evaluate((a) => {
      const ac = new AbortController();
      window.__acA = ac;
      window.__a = window.__h.scene.loadScene(a, { signal: ac.signal }).then(() => "loaded", (e) => e.name);
    }, files.offbed);
    const seen = await waitFor(() => held !== null);
    log(`A held: ${seen}`);
    const aName = await page.evaluate(async () => { window.__acA.abort(); return window.__a; }); // the user leaves A
    log(`A aborted: ${aName}`);
    const bOut = await page.evaluate((b) => window.__h.scene.loadScene(b, { signal: new AbortController().signal }).then((s) => s.schema, (e) => `${e.name}:${e.code}`), files.cube);
    log(`B: ${bOut}`);
    armed = false; // the replays below must not be held again
    const client = (await page.evaluate(() => window.__h.scene.currentSceneClientId()));
    const bStart = slice(mark).filter((e) => e.route === "start").at(-1);
    // A's start now arrives at the real engine, replayed by hand (the browser had already given up on its own request).
    const late = held ? await page.evaluate((b) => window.__h.raw("start", b), held) : null;
    // A start from the same session with a lower seq and a fresh request id: refused. Cancels raise a dead-through mark, so
    // the engine answers CANCELLED_BEFORE_START for any seq at or below it, STALE_START otherwise.
    const lowSeq = await page.evaluate(([c, p]) => window.__h.raw("start", { path: p, request_id: "late-lower-seq-0001", client_id: c, seq: 1 }), [client, files.offbed]);
    // An exact retry (same request id and seq) of a start the engine already processed: observed as recorded below. The client
    // never sends one, because every retry takes a fresh request id and a higher seq.
    const exactRetry = bStart ? await page.evaluate((b) => window.__h.raw("start", b), bStart.body) : null;
    const bJob = bStart?.reply?.job_id;
    const bState = bJob ? await page.evaluate(([j, c]) => window.__h.raw("status", { job_id: j, client_id: c }), [bJob, client]) : null;
    release();
    const ok =
      expect(seen, "A's start was held on its way to the engine") &&
      expect(aName === "AbortError", "A ends with AbortError") &&
      expect(bOut === "scene/1", `B loads (observed ${bOut})`) &&
      expect(late?.status === 409 && ["CANCELLED_BEFORE_START", "STALE_START"].includes(late.body?.error), `A's late start is refused (observed ${late?.status} ${late?.body?.error})`) &&
      expect(lowSeq.status === 409 && ["CANCELLED_BEFORE_START", "STALE_START"].includes(lowSeq.body?.error), `a lower seq is refused (observed ${lowSeq.status} ${lowSeq.body?.error})`) &&
      expect(exactRetry?.status === 200 && exactRetry.body?.job_id === bStart.reply.job_id, `an exact retry of a processed start returns the same job (observed ${exactRetry?.status} ${exactRetry?.body?.job_id ?? exactRetry?.body?.error})`) &&
      expect(bState?.body?.state === "succeeded", `B's job was neither cancelled nor replaced (observed ${bState?.body?.state})`);
    scenarios.abandonedAfterB = {
      covered: true, passed: ok, note: "A's own request was held in the browser and aborted with A, so it never reached the engine; its body was replayed to the real route by hand after B completed. The cancel for A was real.",
      observed: slice(mark).map(compact), lateAStart: late && [late.status, late.body?.error], lowerSeqStart: [lowSeq.status, lowSeq.body?.error], exactRetryOfB: exactRetry && [exactRetry.status, exactRetry.body?.error], bJobState: bState?.body?.state,
    };
  }

  log("4 session expired");
  // ---- 4. SESSION_EXPIRED after a fresh engine process -------------------------------------------------------------
  {
    stopEngine(engineA);
    await sleep(800);
    let b = null;
    for (let i = 0; i < 10 && !b; i++) { try { b = await spawnEngine({ port: P }); } catch { await sleep(500); } }
    expect(b && b.handshake.port === P, "a fresh engine process came up on the same port");
    engineB = b;
    const mark = wire.length;
    const out = await page.evaluate(async ([path, token, port]) => {
      const { loadScene, currentSceneClientId } = window.__h.scene;
      const before = currentSceneClientId();
      const scene = await loadScene(path, { signal: new AbortController().signal, transport: window.__h.tx(`http://127.0.0.1:${port}`, token) });
      return { schema: scene.schema, sessionBefore: before, sessionAfter: currentSceneClientId() };
    }, [files.showcase, b.handshake.token, P]);
    const w = slice(mark);
    const starts = w.filter((e) => e.route === "start");
    const ok =
      expect(out.schema === "scene/1", "the load succeeds against the fresh engine") &&
      expect(out.sessionBefore !== out.sessionAfter, "a new session was opened") &&
      expect(starts.length === 2 && starts[0].status === 409 && starts[0].reply.error === "SESSION_EXPIRED" && starts[1].status === 200 && starts[1].body.seq === 1 && starts[1].body.request_id !== starts[0].body.request_id, "one SESSION_EXPIRED, then ONE restart with seq 1 and a fresh request id") &&
      expect(w.filter((e) => e.route === "session").length === 1, "exactly one new session was opened");
    scenarios.sessionExpiredAfterFreshEngine = { covered: true, passed: ok, observed: w.map(compact) };
  }

  log("5 session limit");
  // ---- 5. SESSION_LIMIT -----------------------------------------------------------------------------------------------
  if (engineB) {
    const base = `http://127.0.0.1:${P}`, token = engineB.handshake.token;
    const opened = await page.evaluate(async ([b, t]) => {
      let n = 0;
      for (let i = 0; i < 80; i++) { const r = await window.__h.rawAt(b, t, "session", {}); if (r.status !== 200) return { n, status: r.status, error: r.body?.error }; n++; }
      return { n, status: 200, error: null };
    }, [base, token]);
    const out = await page.evaluate(async ([path, b, t]) => {
      const { loadScene, resetSceneSession, sceneErrorText } = window.__h.scene;
      resetSceneSession(); // as at app start: no session yet
      const r = await loadScene(path, { signal: new AbortController().signal, transport: window.__h.tx(b, t) }).then(() => ({ loaded: true }), (e) => ({ name: e.name, code: e.code, text: sceneErrorText(e.code) }));
      return r;
    }, [files.showcase, base, token]);
    const ok =
      expect(opened.status === 503 && opened.error === "SESSION_LIMIT", `the real engine refuses sessions past its limit (observed ${opened.status} ${opened.error} after ${opened.n})`) &&
      expect(out.code === "SESSION_LIMIT" && /try again/i.test(out.text), "the client reports SESSION_LIMIT in plain words");
    scenarios.sessionLimit = { covered: true, passed: ok, sessionsOpenedBeforeRefusal: opened.n, clientResult: out };
  }
} catch (e) { failures.push(String(e?.stack ?? e).slice(0, 600)); }
finally { await browser.close(); if (engineB) stopEngine(engineB.backend); cleanup(); }

const unchanged = Object.fromEntries(Object.entries(files).map(([k, p]) => [k, sha(p) === before[k]]));
expect(Object.values(unchanged).every(Boolean), "every example file is unchanged");
const result = {
  engine: "the real engine process (python -m snapstudio_api) on loopback", client: "src/lib/scene.ts running in Edge over real HTTP",
  scenarios, failures, originalFilesUnchanged: unchanged,
  notCovered: [
    "Delivery of an abandoned start that is genuinely in flight at the engine when the browser aborts it: the browser cannot recall a request already on the wire, and a held request was never sent, so that case was replayed by hand against the real route rather than raced.",
    "Idle expiry of a session after its 15-minute TTL (a fresh engine process was used instead).",
    "The packaged Windows Tauri app and the Linux WebKitGTK build (NOT RUN).",
  ],
};
writeFileSync(join(OUT_DIR, "real-engine-results.json"), JSON.stringify(result, null, 2));
console.log(JSON.stringify({ passed: failures.length === 0, failures, scenarios: Object.fromEntries(Object.entries(scenarios).map(([k, v]) => [k, v.passed])) }, null, 1));
process.exit(failures.length ? 1 : 0);
