# Read-only project view (PR 3b)

Studio now shows a 3D, read-only view of the project the user opened, drawn from the engine's `scene/1`
contract (`docs/testing/scene-contract/README.md`). It appears on the project page in Simple mode
(`DesignInsights`) and in Advanced mode (`LiveWorkspace`), after the Doctor has finished, and loads its code only
when first shown.

It shows the objects, the bed, the engine's placement and size notes, a list of what the view cannot tell you,
camera buttons, and a slope view. It never edits, moves, cuts, paints or saves anything.

Everything below was measured on one machine (Windows 11, Microsoft Edge 154 headless through playwright-core, WebGL on
a discrete NVIDIA GPU through ANGLE/Direct3D 11). Raw numbers are in `results.json`; images are in `screenshots/`
(anonymous repository examples and synthetic fixtures only; each image is the panel, so no file path appears).

## What was and was not run

Every number below was measured on the working tree of branch `feat/project-viewer` (base `d0b2257` plus the repair changes, not
yet committed when measured), by running the scripts in `harness/` from this folder. They have to be re-run against the final
commit to make the claim about that commit; `harness/README.md` says how.

| Check | Status |
|---|---|
| `npx tsc --noEmit` | 0 errors |
| `npm run test` (vitest) | 77 files, 913 tests, 0 failed (includes the existing prepare-copy guard) |
| `npm run build` | passes |
| Real-browser run, dev server, real engine, real WebGL, light and dark, wide and narrow | run (this folder) |
| Production build served with the app's real Tauri CSP | run: viewer works, no violation from the viewer |
| **Packaged Windows Tauri via `tools/acceptance/run.ps1`** | **NOT RUN.** The lane installs a rewrapped release installer with an attestation; this branch has no released installer, and building one (frozen sidecar, Tauri bundle, rewrap) was not attempted here. Edge is the same engine family as WebView2, but WebView2 inside the Tauri window was not exercised. |
| **Linux WebKitGTK graphics-enabled lane** | **NOT RUN.** No Linux desktop with a graphics session was available. The existing lane disables compositing, so it would need a graphics-enabled variant. |
| macOS, screen reader, software-rendered or weak GPU, a real printer | not run (a printer is never used) |

Do not read the browser results as proof for the packaged apps. They show the code works in a Chromium browser with
hardware WebGL.

## How read-only is enforced

The vendored SlicerX viewport (`desktop/src/vendor/slicerx/UPDATING.md`) still contains its editing code (move, rotate,
scale, paint, cut, sketch), because its entry class imports and constructs it. That code is **in the bundle**; it was
not removed. Studio cannot reach it:

The boundary is structural, in three places, and a test pins each:

* **`defaultViewport.ts`** is the only file that imports the viewport's factory, and the only place that touches its
  tool: it calls `setTool("probe")` once (a click only reports what is under the cursor), keeps the viewport inside a
  closure, and hands out an inspection port (`InspectionPort`, defined in `readOnlyViewport.ts`) that has no `setTool`, no
  generic `on` and no editing member, only the ten named pass-through calls pinned in the guard test and four named
  subscriptions (pick, select, error, degrade). If anything after creation throws, it disposes the half-built viewport.
  `defaultViewport.test.ts` proves, against a stand-in viewport, that the tool is set once and first, that the adapter
  hands out no `setTool` or `on`, and that a throw from `setTool`, `setTheme` or any of the four subscriptions disposes
  the viewport.
* **`readOnlyViewport.ts`** turns the port into the facade (`ReadOnlyViewport`: show, select, camera preset, slope view,
  theme, onPick, onSelect, onTrouble, dispose). Type-level test: editing calls, `setTool`, a generic `on`, a raw handle
  and an unknown camera preset do not type-check on the facade, and `setTool`, `on` and `setCutPlane` do not type-check on the
  port (`@ts-expect-error` lines in `readOnlyViewport.test.ts`, enforced by `tsc`).
* **`readOnly.guard.test.ts`** scans ALL of `src/` (not just the view's folder; vendor and tests excluded, about 140
  files). It fails when any file other than those named below mentions the vendor tree in any quoted string (import,
  re-export, dynamic `import()`, `?raw`, alias, relative path), when a dynamic `import()` has a computed argument, when any
  editing member name (`setTool`, `setCutPlane`, `setTransforms`, `setPaint*`, ...) appears in any spelling that keeps the name
  (call, bracket access, destructuring, alias, string), when `.arrange(` is used, or when `createViewport` is named
  outside the adapter. Allowed: `readOnlyViewport.ts` (a type import of the vendor entry), `defaultViewport.ts` (the value
  import of it, with exactly one `setTool("probe")`) and `credits.ts` (the vendored NOTICE and LICENSE-APACHE as plain text).
  **Mutation tests** feed the scan a bypass in `components/project-scene/sub/`, in `routes/`, in `lib/`, a computed and a
  literal dynamic import, a re-export, bracket access, destructuring, an alias, a value import in the facade, a second or
  different `setTool`, and extra imports in `credits.ts`; each must fail, and does. I also dropped real bypass files into
  `project-scene/sub/` and `routes/` on disk, ran the guard, saw it fail naming both files, and deleted them.
  Limit: a source scan cannot see a member name built at run time ("set" + "Tool"); code review covers that.
* UI test: no button in the panel is named move, rotate, scale, paint, cut and so on, and the panel has no input.
* Real input: on the real viewport set up the way the adapter sets it up (create, `setTool("probe")`; the adapter itself is
  covered by the unit tests above), a script sends left, right and middle drags with no modifier and
  with Shift, Control, Alt, Shift+Control and Shift+Alt, Space+drag, double click, wheel (also with each modifier) and 21
  key presses (Delete, Backspace, R, S, M, P, C, X, B, F, Enter, arrows, Control+Z/Y/C/V/A, Escape). The viewport
  emitted only `camera` (185) and `pick` (4) events. The center of each object, read through the viewport's own hit test
  before and after, was identical (`b0` 109.5, 109, 10 and `b1` 149.5, 109, 10).
  **Control run:** the same input on the same viewport with its upstream default tool did move an object (center
  109.5, 109, 10 moved to about 193-194, 87.5-87.7, 10 in each of the runs I made, a little different every time because the drag is timed by real input: 193.279, 87.669 in one run, 194.189, 87.52 in another, 193.588, 87.618 in the last, which is the one in `results.json`; 11 `transform` events each time), so the check is able to detect movement and is not vacuous.
  Screenshots before and after were not byte identical in either run (adaptive quality and effects settle over time), so
  pixel equality is not claimed; the geometry check above is the evidence.
* Original files: every fixture was hashed before and after all runs (including a 100,000-triangle project): unchanged.
  The engine only reads the file (backend tests in the PR 3a folder compare bytes and modification time as well).

## What the view claims, and does not

* Highlighting comes only from engine findings keyed to node ids. A finding naming an unknown node, or any finding when
  the scene cannot prove placement, stays a project-level note and highlights nothing.
* Highlighting is off, with the reason in words, when a source unit is not millimeters, the project has more than one
  plate, any object's placement is unknown (STL files, models with no build item), or the bed outline fell back.
  Screenshots: `wide-dark-inch`, `wide-dark-two-plates`, `wide-dark-stl`.
* Position claims say "Placement". The word "fits" is never produced (a test scans every finding and limitation string,
  and also for "ready", "guarantee", "100%", "safe", "best", "clean"). The slope label is exactly
  "Geometric slope visualization - review supports in Orca."
* The physical bed edge and the 0.5 mm policy margin are told apart: the engine measures past the margin line, so the
  note says how far past the bed edge, or that the object is inside the bed but within the margin. The margin is also
  drawn as a faint inner outline, and the bed outline turns orange only for a placement note.
* The view is advisory. It does not say anything prints, and its footer points to Snapmaker Orca for placement and
  supports.

## Lifecycle evidence (real WebGL)

* **Facade, 50 create/dispose cycles** (each with a fresh canvas): 0 connected canvases left, 0 viewer-created canvases
  with a live context, 0 listeners left (all `addEventListener` calls counted, including `once`), 0 live observers,
  never more than one canvas in the page. This runs the real adapter (`createSceneViewer`). Contexts created: 100 (two per
  viewer, one is transient); still live at the end: 0.
* **App, the real panel mounted and unmounted 75 times under React StrictMode** (50 waited until the 3D view was
  working, 25 unmounted while still loading): 1 connected canvas at the end (the live one), 0 listeners on detached
  canvases, 1 live context, 2 live observers (the one live viewer's), 22 listeners on connected targets (19 are the one
  live viewer's; 2 are `invalid` listeners of unrelated input elements; 1 is the credits `<details>` toggle; counts by type in `results.json`); the panel still
  worked afterwards. 51 viewers were actually created over the 75 mounts (the rest unmounted before the scene arrived).
* A first version of this check found two real defects, both fixed and now tested: (1) when React unmounts a route it
  removes the DOM before passive cleanup runs, and three.js then fails to remove a document-level keydown listener
  (18 leaked in 75 cycles); the controller now disposes the viewer with its canvas attached. (2) Two scene starts sent
  back to back (StrictMode) could be handled by the engine in the opposite order, so the newer view's job came back
  "cancelled" after about 23 cycles; starts now leave one at a time, in order, and a start whose caller gave up is never sent.
  After the fixes three full runs showed no stuck view.
* Closing a view aborts the browser requests and sends an authenticated `/scene/cancel`. The start/start/cancel/status/
  result sequence under StrictMode was observed on the wire, with no `BUSY`.
* **An engine that stops answering cannot stall the view.** Every engine call has a limit (start 15 s, status and result
  30 s) and ends with an `AbortError` (the caller left) or `TIMEOUT` (shown as "Reading the project took too long" with a
  **Try again** button). The limit is a race, so a transport that ignores its abort signal still releases the caller. A start
  that was abandoned may still have made a job, so before the next start is sent it is asked for again with the same
  request id (the engine returns the same job) and cancelled; that clean-up is bounded to 3 s and never replaces a newer
  job. Tests: a start that never resolves times out and the next start works; an abort releases the caller at once; a status
  answer that never comes gives `TIMEOUT` and cancels the job; at controller level, a start that never answers shows the
  failed state with Retry, and Retry then shows the view.
* Stale answers are dropped by generation and path (`sceneController.test.ts`, including A, then B, then A).
* No WebGL: the context-creation failure is caught; the object list and notes stay, the camera buttons are disabled, and
  **Retry 3D view** builds a new canvas. A lost context (forced with `WEBGL_lose_context`) shows the same panel with a
  different message and Retry builds a different canvas. Screenshots: `wide-dark-no-webgl`, `narrow-light-no-webgl`,
  `wide-dark-context-lost`.
* Keyboard: every control is a real `<button>`; the object rows toggle with Space (asserted); Enter was pressed on a camera button in the run
  (no failure, not asserted); focus rings come from the shared button style. A click on the model in the 3D view selects its
  row in the list (`wide-dark-picked-by-click`).

## Mirrored objects

A mirrored instance (negative-determinant world matrix) keeps its triangle order. An earlier version also reversed the
triangles, which turned the faces inward a second time: a downward ray through a mirrored cube hit the bottom face (Z 0)
instead of the top (Z 20). `sceneModel.test.ts` now builds a real reflection matrix, puts it on a three.js mesh and
raycasts it: the top face is hit, and a control with the triangles reversed hits the bottom, so the test can fail.

## The start answer

`/scene/start` answers only job id, request id, state, revision and the id of a job it replaced (`scene_jobs.py`); it carries
no stage, progress or error. `scene.ts` models that as `JobStart`, and the tests use that body shape. A request id the engine
still holds can come back already failed; the reason is then fetched from `/scene/status`, so the user sees the real
message (for example "larger than the 3D view can show") and not a generic one.

## Memory and size

* Bundle: the main chunk grew by 962 bytes (396 gzipped) for the mount code; the lazy viewer chunk is 906,904 bytes,
  249,939 gzipped (`gzip -9`); the earlier prototype measured 887,866 and 245,773. The growth since the first version is the license texts and the structural facade. Baseline built from `58d193a` with the same Vite.
* Large scene: a 99,458-triangle project took 5.1 s from pressing Open to a working view (including the Doctor run and the
  engine job) and the page's JS heap grew from 10.4 MB to 20.1 MB (`large-100k`).
* **Finding, not fixed:** creating and disposing the vendored viewport retains about 108 KB of JS heap each time, even
  with an empty plate (empty viewport 108 KB, with plate 116 KB, through Studio's facade 121 KB; forced GC each time,
  linear over 150 cycles). GPU contexts are released. In the app, 75 mounts (51 viewers created) grew the heap from 17.5 MB to 38.9 MB. Mounting the panel 40 more times
  with WebGL turned off (so everything of Studio's except the viewer runs) grew it by 11 KB per mount; with the
  viewer it was 264 KB per mount. So the growth is almost all inside the vendored viewport and three.js; the cause
  was not isolated. A
  user opening many projects in one session would see slow growth. Not addressed here to avoid patching the pinned source.

## CSP and licensing

* `src-tauri/tauri.conf.json` is unchanged. The vendored source has no network, worker, `eval`, `new Function` or blob use
  (source search). The production build was served with the real CSP header (`script-src 'self'`, no inline script): the
  viewer ran and the only violation was the existing Google Fonts `@import` in `index.css`, which the CSP already blocked
  before this change.
* three 0.186.1 (MIT) and the SlicerX viewport (Apache-2.0, "Made possible by SlicerX") are in `THIRD_PARTY_NOTICES.md`;
  provenance and every local patch are in `desktop/src/vendor/slicerx/UPDATING.md`.
* **Credits and licenses inside the installed app.** The panel shows "Made possible by SlicerX: https://slicerx.app/support"
  (the link as text, not a clickable link, so nothing navigates the app window away) and a **Licenses for the 3D view**
  section holding SlicerX's NOTICE, the Apache License 2.0 text and the three.js MIT text. They are imported as text into the
  lazily loaded 3D view chunk (`project-scene/credits.ts`), so every installed copy carries them with no installer or
  `tauri.conf.json` change. A test checks they are on screen. `THIRD_PARTY_NOTICES.md` is not shipped by the installer;
  shipping the files as Tauri bundle resources would need a `bundle.resources` entry in `src-tauri/tauri.conf.json`
  (`../../THIRD_PARTY_NOTICES.md`, `../src/vendor/slicerx/LICENSE-APACHE`, `../src/vendor/slicerx/NOTICE`). That change
  was deliberately not made here (it is outside this PR's file ownership and untested against the installer lanes).
* The legend about red and amber marks, and the margin figure, come from the scene (`bed.edge_margin_mm`) and appear only
  when highlighting is on.
* Screenshot pairs that are byte-identical are the same state reached two ways, by design: `wide-dark-selected` and
  `wide-dark-picked-by-click` (a row chosen from the list, and a click on the model), and `wide-dark-offbed` and
  `csp-production` (the development page and the production build served with the real CSP).

## Known limits

* Object names are "Object 1, 2, ..." in file order; the scene contract carries no display names.
* The extreme-narrow screenshot (390 px window) is cramped because the app shell's sidebar leaves about 100 px; the
  app's own default window (820 px) is the realistic minimum and renders cleanly (`narrow-*`).
* The harness blocked the app's own `/printer/status` and `/printer/capabilities` polling so no printer was contacted;
  those calls are not from the 3D view.
* Not covered by the scene or this view: material colors, painted regions, multi-plate geometry checks, orientation advice.

## Reproduce

The scripts are in `harness/` (see `harness/README.md`): engine and dev server on free ports, Edge through playwright-core,
the repository examples (`demo_offplate_foreign.3mf`, `sample_cube_U1.3mf`, `sample_cube.stl`) and four synthetic projects made with
`backend/tests/scene_fixtures.py` (three roles, two plates, inches, 100,000 triangles) by `harness/mkfx.py`.
