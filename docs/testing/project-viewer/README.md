# Read-only project view (PR 3b)

Studio shows a 3D, read-only view of the project the user opened, drawn from the engine's `scene/1` contract
(`docs/testing/scene-contract/README.md`). It appears on the project page in Simple mode (`DesignInsights`) and in Advanced
mode (`LiveWorkspace`), after the Doctor has finished, and loads its code only when first shown.

It shows the objects, the bed, the engine's placement and size notes, a list of what the view cannot tell you, camera
buttons, and a slope view. It never edits, moves, cuts, paints or saves anything.

**Where the numbers are.** Every measurement in this folder is in `results.json`, written by `harness/collect-results.mjs`
from one run, and the tables in "Measurements" below are generated from it by `harness/make-readme-tables.mjs`; no figure in
this README is typed by hand. `results.json` records the commit the run was taken on. A run is evidence about a commit only
when that line says the tree was clean outside this folder. `harness/README.md` says how to repeat it.

## What was and was not run

| Check | Status |
|---|---|
| Type check, unit tests, build | run by `collect-results.mjs` (see Measurements) |
| Real-browser run: dev server, real engine, real WebGL, light and dark, wide and narrow | run by the harness |
| Production build served with the app's real Tauri CSP | run by the harness |
| The scene client against the **real engine** (sessions, credentials, ordering) | run by `harness/real-engine.mjs` on a working tree that contains the reviewed engine: see "Against the real engine" below for exactly what was and was not covered. |
| **Packaged Windows Tauri via `tools/acceptance/run.ps1`** | **NOT RUN (outstanding).** The lane installs a rewrapped release installer with an attestation; this branch has no released installer, and building one (frozen sidecar, Tauri bundle, rewrap) was not attempted. Edge is the same engine family as WebView2, but WebView2 inside the Tauri window was not exercised. |
| **Linux WebKitGTK graphics-enabled lane** | **NOT RUN (outstanding).** No Linux desktop with a graphics session was available. The existing lane disables compositing, so it would need a graphics-enabled variant. |
| macOS, screen reader, software-rendered or weak GPU, a real printer | not run (a printer is never used) |

Do not read the browser results as proof for the packaged apps. They show the code works in a Chromium browser with
hardware WebGL.

## How read-only is enforced

The vendored SlicerX viewport (`desktop/src/vendor/slicerx/UPDATING.md`) still contains its editing code (move, rotate,
scale, paint, cut, sketch), because its entry class imports and constructs it. That code is **in the bundle**; it was not
removed. Studio cannot reach it. The boundary is structural, in three places, and a test pins each:

* **`defaultViewport.ts`** is the only file that imports the viewport's factory, and the only place that touches its tool:
  it calls `setTool("probe")` once (a click only reports what is under the cursor), keeps the viewport inside a closure, and
  hands out an inspection port (`InspectionPort`, defined in `readOnlyViewport.ts`) that has no `setTool`, no generic `on` and
  no editing member: only the named pass-through calls pinned in the guard test and four named subscriptions (pick, select,
  error, degrade). If anything after creation throws, it disposes the half-built viewport. `defaultViewport.test.ts` proves,
  against a stand-in viewport, that the tool is set once and first, that the adapter hands out no `setTool` or `on`, and that a
  throw from `setTool`, `setTheme` or any of the four subscriptions disposes the viewport.
* **`readOnlyViewport.ts`** turns the port into the facade (`ReadOnlyViewport`: show, select, camera preset, slope view,
  theme, onPick, onSelect, onTrouble, dispose). Type-level test: editing calls, `setTool`, a generic `on`, a raw handle and an
  unknown camera preset do not type-check on the facade, and `setTool`, `on` and `setCutPlane` do not type-check on the port
  (`@ts-expect-error` lines in `readOnlyViewport.test.ts`, enforced by `tsc`).
* **`readOnly.guard.test.ts`** scans every non-test, non-vendor file in `src/` (not just the view's folder). It fails when any
  file other than those named below mentions the vendor tree in any quoted string (import, re-export, dynamic `import()`,
  `?raw`, alias, relative path), when a dynamic `import()` has a computed argument, when any editing member name (`setTool`,
  `setCutPlane`, `setTransforms`, `setPaint*`, ...) appears in any spelling that keeps the name (call, bracket access,
  destructuring, alias, string), when `.arrange(` is used, or when `createViewport` is named outside the adapter (inside it,
  only its import and one call expression are allowed: a re-export, alias or second call fails). Allowed: `readOnlyViewport.ts`
  (a type import of the vendor entry), `defaultViewport.ts` (the value import of it, with exactly one `setTool("probe")`) and
  `credits.ts` (the vendored NOTICE and LICENSE-APACHE as plain text). **Mutation tests** feed the scan a bypass in
  `components/project-scene/sub/`, in `routes/`, in `lib/`, a computed and a literal dynamic import, a re-export, bracket
  access, destructuring, an alias, a value import in the facade, a second or different `setTool`, extra imports in
  `credits.ts`, and a re-export, alias or second call of `createViewport` in the adapter; each must fail, and does. Real bypass
  files were also dropped into `project-scene/sub/` and `routes/` on disk; the guard was run, failed naming both files, and the
  files were deleted. Limit: a source scan cannot see a member name built at run time ("set" + "Tool"); code review covers that.
* **`vendor.integrity.test.ts`** checks the vendored tree against its own record in `UPDATING.md`: every verbatim file is
  byte-for-byte upstream (git blob id), each of the seven patched files carries the modification notice after the upstream
  header and, with the notice removed and the import path put back, is byte-for-byte upstream, no other file has a notice, and
  every sha256 in the table is current.
* UI test: no button in the panel is named move, rotate, scale, paint, cut and so on, and the panel has no input.
* Real input: on the real viewport set up the way the adapter sets it up (create, `setTool("probe")`; the adapter itself is
  covered by the unit tests above), a script sends left, right and middle drags with no modifier and with Shift, Control, Alt,
  Shift+Control and Shift+Alt, Space+drag, double click, wheel (also with each modifier) and a fixed list of key presses
  (Delete, Backspace, R, S, M, P, C, X, B, F, Enter, arrows, Control+Z/Y/C/V/A, Escape). The object centers, read through the
  viewport's own hit test before and after, must be identical. **Control run:** the same input on the same viewport with its
  upstream default tool does move an object, so the check is able to detect movement and is not vacuous. The control's final
  position differs a little from run to run because the drag is timed by real input. Results are in Measurements.
* Original files: every fixture is hashed before and after each run (including a large project) and must be unchanged. The
  engine only reads the file (backend tests in the PR 3a folder compare bytes and modification time as well).

## What the view claims, and does not

* Highlighting comes only from engine findings keyed to node ids. A finding is object-level only when it names exactly one
  target and that target is a known node. A finding with several targets (even in one object), an unknown id, or any finding
  when the scene cannot prove placement, stays a project-level note and highlights and selects nothing.
* Highlighting is off, with the reason in words, when a source unit is not millimeters, the project has more than one plate,
  any object's placement is unknown (STL files, models with no build item), or the bed outline fell back. Screenshots:
  `wide-dark-inch`, `wide-dark-two-plates`, `wide-dark-stl`.
* Position claims say "Placement". The word "fits" is never produced (a test scans every finding and limitation string, and
  also for "ready", "guarantee", "100%", "safe", "best", "clean"). The slope label is exactly
  "Geometric slope visualization - review supports in Orca."
* The physical bed edge and the policy margin are told apart: the engine measures past the margin line, so the note says how
  far past the bed edge, or that the object is inside the bed but within the margin. The margin is also drawn as a faint inner
  outline, and the bed outline turns orange only for a placement note. The legend appears only when highlighting is on, and
  takes the margin from the scene.
* The view is advisory. It does not say anything prints, and its footer points to Snapmaker Orca for placement and supports.
* A mirrored instance (negative-determinant world matrix) keeps its triangle order. An earlier version also reversed the
  triangles, which turned the faces inward a second time: a downward ray through a mirrored cube hit the bottom face instead
  of the top. `sceneModel.test.ts` builds a real reflection matrix, puts it on a three.js mesh and raycasts it: the top face is
  hit, and a control with the triangles reversed hits the bottom, so the test can fail.

## Talking to the engine

`scene.ts` starts a job, follows it, and returns the scene. What it relies on, and what it does not:

* **Ordering of overlapping starts is the engine's job, within one session.** The client opens ONE session lazily per app run
  (`POST /scene/session`, answered with `client_id` and a time to live) and opens another after `SESSION_EXPIRED`. Every start
  carries that `client_id` and a `seq` that is strictly increasing within the session, starting at 1. The agreed engine rules:
  a start whose `seq` is not higher than the highest seen is refused (`STALE_START`; this includes an exact retry of a start
  already processed, so every retry uses a fresh request id and the next `seq`); a start for a cancelled request or `seq` is
  refused (`CANCELLED_BEFORE_START`); an unknown or idle-expired session is refused (`SESSION_EXPIRED`); more sessions than the
  engine allows is `503 SESSION_LIMIT`. `/scene/cancel` takes `{client_id, request_id, seq}` and keeps that `seq` dead for the
  session; on an expired session it answers `SESSION_EXPIRED`, which the client ignores (best effort).
* The client sends that cancel immediately when a view is abandoned (unmount, path change, StrictMode's first mount), whether
  or not the start has been answered or even delivered. It is best effort, bounded, never awaited and never holds up the next
  start. A load abandoned before it learned the session, or before it took its `seq`, sent nothing and has nothing to cancel.
* An abandoned start that reaches the engine after a newer one therefore cannot cancel or replace it, and one that reaches the
  engine after its session expired meets an unknown session: its answer is dropped and it triggers nothing. This is proved
  against a stand-in engine that implements the rules above, with every delivery order controlled by hand (no timers):
  `scene.test.ts`, "sessions" and "job credentials". The real engine is then driven through the cases it can be driven through, below; that run does not repeat every ordering in these tests, and its limits are listed there.
* **Job credentials.** `/scene/status` and `/scene/result` carry the session's `client_id` along with the `job_id`; a job that
  belongs to a session is visible only to the same session. A foreign, missing or unknown `client_id` all answer
  `404 EXPIRED` (no leak), which the client reports as expired. Cancel by `{client_id, request_id, seq}` cancels the job only when
  its `seq` is exactly that `seq`, and raises a mark below which every start of the session is refused. After an admitted start
  is rejected (503 `WORKER_WEDGED`, 422 `UNSUPPORTED_FORMAT`, a missing file) the client's next try always uses a fresh request id
  and a higher `seq`. `replaced_job_id` is set only for a job of the same session.
* **The guarantee is per session only.** A start from another session (another Studio window, or a client that did not use
  this session) replaces the running job as it always did. Sessions do not make one engine serve two windows at once.
* **Residual, stated plainly.** After `SESSION_EXPIRED` the client opens a new session, starts `seq` again at 1, and restarts
  ONCE with a fresh request id; a second expiry is shown ("Studio lost its connection to the engine for the 3D view. Try
  again."). `SESSION_LIMIT` is shown with Try again and never retried; it reads "The engine is serving as many 3D views as it allows. Close another Studio window, then try again." Separately, if a wanted request still comes
  back cancelled or refused as superseded, the client starts it ONCE more with a fresh request id and the next `seq`. Both
  restarts are resilience only; neither is what makes the ordering correct.
* **An engine that stops answering cannot stall the view.** Every call has a limit (start 15 s, status and result 30 s) and
  ends with an `AbortError` (the caller left) or `TIMEOUT` ("Reading the project took too long", with a **Try again** button).
  The limit is a race, so a transport that ignores its abort signal still releases the caller. A timeout also cancels the
  request by id.
* `/scene/start` answers only job id, request id, state, revision and the id of a job it replaced; it carries no stage,
  progress or error. `scene.ts` models that as `JobStart`. A request id the engine still holds can come back already failed; the
  reason is then fetched from `/scene/status`, so the user sees the real message and not a generic one.
* `STALE_START`, `CANCELLED_BEFORE_START`, `SESSION_EXPIRED` and `SESSION_LIMIT` have plain wording. For an abandoned generation they never reach the screen:
  answers for a generation that is no longer current, or a path that changed, are dropped (`sceneController.test.ts`, including
  A, then B, then A).

## Against the real engine

`harness/real-engine.mjs` runs the real client (`src/lib/scene.ts`, in Edge, over real loopback HTTP) against the real engine
process, using the repository example projects and one synthetic large project. Its output is `real-engine-results.json`
(collected into `results.json` by `collect-results.mjs`). What it covers, each with assertions on the wire:

* **Round trip:** session, start (seq 1, with the session's client id), status polls and result, every status and result carrying
  the client id and answered 200.
* **Cancel round trip:** a load of the large project is abandoned right after its start is answered; the cancel goes by
  `{client_id, request_id, seq}` and is answered 200; the job is then `cancelled`. Status for that job with a foreign client id,
  and with none, is `404 EXPIRED`.
* **Abandoned A after B:** A's start is held in the browser on its way out, A is abandoned (the cancel is real), B loads, and A's
  start body is then replayed by hand to the real `/scene/start` route: it is refused (`CANCELLED_BEFORE_START`), a start with a
  lower seq is refused, B's job is neither cancelled nor replaced, and an exact retry of B's start returns B's same job (the
  client never sends one).
* **`SESSION_EXPIRED` after a fresh engine process:** the engine is stopped and a new process started on the same port; the
  client's next start is answered `SESSION_EXPIRED`, one new session is opened, and the restart (seq 1, fresh request id) loads.
  **Qualification:** the harness hands the client a transport that carries the restarted engine's NEW token. This proves session
  recovery once credentials are available; it does not prove how the real app rediscovers a restarted engine's token, which was
  not exercised.
* **Abandoned A replayed after its session expired:** against that fresh engine, A's late start (old session id) is answered
  `SESSION_EXPIRED` twice, a cancel for the dead session is `SESSION_EXPIRED`, a status call with the dead id is `404 EXPIRED`, and
  the replay opens no session: nothing is revived.
* **`SESSION_LIMIT`:** sessions are opened until the real engine refuses; a load then fails with `SESSION_LIMIT` in plain words,
  the client having sent exactly one session request and nothing else (no retry, no start).

**Not covered, plainly:** a start that is genuinely in flight at the engine when the browser aborts it (the browser cannot recall
a request already on the wire, and a held request was never sent, so the late delivery was replayed by hand rather than raced);
the idle expiry of a session after its time to live (a fresh engine process was used instead); the packaged Windows and Linux
apps (below).

## Lifecycle on real WebGL

* One canvas and one viewer per effect; disposal removes the canvas, unregisters listeners and observers, and releases the GL
  context. The real adapter is exercised in a loop of create and dispose, and the real panel is mounted and unmounted under
  React StrictMode, with some mounts waiting for the view and some unmounted while still loading. Numbers are in Measurements.
* An earlier version of this check found two real defects, both fixed and tested: when React unmounts a route it removes the DOM
  before passive cleanup runs, and three.js then fails to remove a document-level keydown listener, so the controller now
  disposes the viewer with its canvas attached; and two scene starts sent back to back could be handled by the engine in the
  opposite order (the session contract above is the fix for that).
* No WebGL: the context-creation failure is caught; the object list and notes stay, the camera buttons are disabled, and
  **Retry 3D view** builds a new canvas. A lost context (forced with `WEBGL_lose_context`) shows the same panel with a different
  message and Retry builds a different canvas. Screenshots: `wide-dark-no-webgl`, `narrow-light-no-webgl`,
  `wide-dark-context-lost`.
* Keyboard: every control is a real `<button>`; the object rows toggle with Space; Enter was pressed on a camera button in the
  run (no failure, not asserted); focus rings come from the shared button style. A click on the model in the 3D view selects
  its row in the list (`wide-dark-picked-by-click`).

## Memory

Creating and disposing the vendored viewport retains JS heap each time, even with an empty plate, and the figure is the same
through Studio's facade, so it is not caused by Studio's view code. With WebGL turned off (so everything of Studio's except the
viewer runs), mounting the panel grows the heap by far less than with the viewer. GPU contexts are released. The growth is
inside the vendored viewport and three.js; the cause was not isolated. A user opening many projects in one session would see
slow growth. It is not addressed here, to avoid patching the pinned source. Figures are in Measurements.

## CSP and licensing

* `src-tauri/tauri.conf.json` is unchanged. The vendored source has no network, worker, `eval`, `new Function` or blob use
  (source search). The production build is served with the real CSP header (`script-src 'self'`, no inline script); the only
  violation is the existing Google Fonts `@import` in `index.css`, which the CSP already blocked before this change.
* three (MIT) and the SlicerX viewport (Apache-2.0, "Made possible by SlicerX") are in `THIRD_PARTY_NOTICES.md`; provenance and
  every local patch are in `desktop/src/vendor/slicerx/UPDATING.md`. Seven vendored files differ from upstream: only the import
  path of the contracts module, plus a prominent "MODIFIED BY SNAPMAKER STUDIO" notice placed after the unchanged upstream
  header.
* **Credits and licenses inside the installed app.** The panel shows "Made possible by SlicerX: https://slicerx.app/support"
  (the link as text, not a clickable link, so nothing navigates the app window away) and a **Licenses for the 3D view** section
  holding SlicerX's NOTICE, the Apache License 2.0 text and the three.js MIT text. They are imported as text into the lazily
  loaded 3D view chunk (`project-scene/credits.ts`), so every installed copy carries them with no installer or
  `tauri.conf.json` change. A test checks they are on screen. `THIRD_PARTY_NOTICES.md` is not shipped by the installer; shipping
  the files as Tauri bundle resources would need a `bundle.resources` entry in `src-tauri/tauri.conf.json`
  (`../../THIRD_PARTY_NOTICES.md`, `../src/vendor/slicerx/LICENSE-APACHE`, `../src/vendor/slicerx/NOTICE`). That change was
  deliberately not made here (it is outside this PR's scope and untested against the installer lanes).
* Screenshot pairs that are byte-identical are the same state reached two ways, by design: `wide-dark-selected` and
  `wide-dark-picked-by-click` (a row chosen from the list, and a click on the model), and `wide-dark-offbed` and
  `csp-production` (the development page and the production build served with the real CSP).

## Known limits

* Object names are "Object 1, 2, ..." in file order; the scene contract carries no display names.
* The extreme-narrow screenshot (390 px window) is cramped because the app shell's sidebar leaves very little room; the app's
  own default window (820 px) is the realistic minimum and renders cleanly (`narrow-*`).
* The harness blocks the app's own `/printer/status` and `/printer/capabilities` polling so no printer is contacted; those calls
  are not from the 3D view.
* Not covered by the scene or this view: material colors, painted regions, multi-plate geometry checks, orientation advice.

## Reproduce

The scripts are in `harness/` (see `harness/README.md`): engine and dev server on free ports, Edge through playwright-core, the
repository examples (`demo_offplate_foreign.3mf`, `sample_cube_U1.3mf`, `sample_cube.stl`) and four synthetic projects made with
`backend/tests/scene_fixtures.py` (three roles, two plates, inches, 100,000 triangles) by `harness/mkfx.py`.

## Measurements

<!-- measurements:begin (generated by harness/make-readme-tables.mjs from results.json; do not edit by hand) -->

Measured at commit `1836fd0dfdcc747b2f5281b5b048c0a44f7354e2` (clean outside this evidence folder, which is committed afterwards), 2026-10-09T20:08:45.127Z.
Machine: Windows (win32), Microsoft Edge 154.0.4258.62 headless, hardware WebGL: yes.

**Checks**

| Check | Result |
| --- | --- |
| `npx tsc --noEmit` | 0 errors |
| `npm run test` (vitest) | 78 files, 937 tests, 937 passed, 0 failed |
| `npm run build` | passes |

**Bundle** (gzip at level 9)

| Chunk | Bytes | gzip bytes |
| --- | --- | --- |
| Main chunk | 711,409 | 190,530 |
| Lazy 3D view chunk | 908,016 | 251,765 |
| Main chunk at `58d193a93c5b` (baseline) | 710,447 | 190,139 |
| Main chunk change | 962 | 391 |

**Input on the real viewport** (a fixed list of drags, modifiers, wheel and key presses; see `behave.mjs`)

| Run | Events seen | Object centers before | Object centers after | Objects stayed put |
| --- | --- | --- | --- | --- |
| Inspection (probe tool) | camera 187, pick 4 | b0 (109.5, 109, 10), b1 (149.5, 109, 10) | b0 (109.5, 109, 10), b1 (149.5, 109, 10) | yes |
| Control (the viewport's own default tool) | camera 187, pick 2, select 2, transform 11 | b0 (109.5, 109, 10), b1 (149.5, 109, 10) | b1 (149.5, 109, 10), b0 (193.054, 87.706, 10) | no |

Before and after screenshots of the inspection run byte-identical: no (adaptive quality and effects settle over time, so pixel equality is not claimed).

**Lifecycle on real WebGL**

| Measure | Create and dispose cycles (real adapter) | Real panel mounts under StrictMode |
| --- | --- | --- |
| Cycles planned / completed | 50 / 50 | 75 / 75 (50 waited for the view, 25 unmounted while loading) |
| Stuck cycle | none | none |
| WebGL contexts created | 100 | 102 |
| WebGL contexts still live at the end | 0 | 1 |
| Peak canvases in the page at once | 1 | - |
| Canvases left connected | 0 after the cycles | 1 at the end, 1 before |
| Live contexts on a detached canvas | 0 | 0 |
| Listeners on detached canvases | - | 0 |
| Listeners left | 0 | 22 on connected targets |
| Live resize/intersection observers | 0 | 2 |
| Panel still works afterwards | - | yes |
| A click on the model selects its row; Space toggles it | - | yes; yes |
| Seconds for all cycles | - | 26.976 |

Listeners left on connected targets, by kind: HTMLDetailsElement:toggle 1, HTMLInputElement:invalid 2, canvas:webglcontextlost 2, canvas:webglcontextrestored 1, canvas:webglcontextcreationerror 1, canvas:pointerdown 2, canvas:pointercancel 2, canvas:contextmenu 1, canvas:wheel 2, document:keydown 1, document:visibilitychange 1, canvas:pointermove 1, canvas:pointerup 1, canvas:keydown 1, canvas:keyup 1, canvas:blur 1, canvas:dblclick 1.

**Memory** (JS heap after forced garbage collection)

| Measure | Repetitions | Growth per repetition |
| --- | --- | --- |
| Create and dispose, raw-empty | 40 | 108,187 bytes |
| Create and dispose, raw-plate | 40 | 115,943 bytes |
| Create and dispose, facade | 40 | 120,971 bytes |
| Mount the panel, WebGL on | 40 | 262,658 bytes |
| Mount the panel, WebGL off | 40 | 10,852 bytes |

In the app: 16.8 MB with the view shown, 37.4 MB after all mounts with the panel unmounted.

**Large scene** (about 100,000 triangles)

| Measure | Value |
| --- | --- |
| Seconds from pressing Open to a working view | 7.199 |
| JS heap before / after | 9.9 MB / 19.2 MB |

**Scene client against the real engine** (assertions on the wire; see "Against the real engine")

| Scenario | Passed |
| --- | --- |
| `roundTrip` | yes |
| `cancelRoundTrip` | yes |
| `abandonedAfterB` | yes |
| `sessionExpiredAfterFreshEngine` | yes |
| `sessionLimit` | yes |

**Production build with the app's Content-Security-Policy**

| Measure | Value |
| --- | --- |
| Production build | yes |
| Canvases while the view works | 1 |
| Policy violations | `style-src-elem https://fonts.googleapis.com/css2` |

**Original files** hashed before and after every run: offbed unchanged, grid unchanged, normal unchanged, stl unchanged, showcase unchanged, roles unchanged, plates unchanged, inch unchanged, csp unchanged.

**Screenshots**

| Screenshot | Page overflows sideways | Canvases | Console errors |
| --- | --- | --- | --- |
| `wide-dark-offbed` | no | 1 | none |
| `wide-light-offbed` | no | 1 | none |
| `wide-dark-normal` | no | 1 | none |
| `wide-dark-selected` | no | 1 | none |
| `wide-dark-slope` | no | 1 | none |
| `wide-dark-roles` | no | 1 | none |
| `wide-dark-stl` | no | 1 | none |
| `wide-dark-two-plates` | no | 1 | none |
| `wide-dark-inch` | no | 1 | none |
| `narrow-dark-offbed` | no | 1 | none |
| `narrow-light-offbed` | no | 1 | none |
| `xnarrow-dark-offbed` | no | 1 | none |
| `wide-dark-no-webgl` | no | 0 | THREE.WebGLRenderer: THREE.WebGLRenderer: Error creating WebGL context. |
| `narrow-light-no-webgl` | no | 0 | THREE.WebGLRenderer: THREE.WebGLRenderer: Error creating WebGL context. |
| `wide-dark-context-lost` | no | 0 | none |

The two `no-webgl` rows record the context-creation error that the test provokes on purpose (WebGL is switched off in those runs); the other rows record no console error.

<!-- measurements:end -->
