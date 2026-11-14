# Browser harness for the 3D project view

These are the scripts behind the numbers and screenshots in `../README.md` and `../results.json`. They are not part of the app
or its test suite. They need Windows (they start the engine with `py` and stop their own processes with `taskkill`), Microsoft
Edge, and `playwright-core` (run `npm ci` in `tools/acceptance`, or point `PLAYWRIGHT_FROM` at a folder whose `node_modules` has
it). Nothing is sent off the machine and no printer is contacted: the scripts block the app's own printer polling and any
request that is not to localhost.

Environment (all optional): `P3B_OUT` (results and screenshots, default a folder under the system temp directory),
`P3B_FIXTURES` (copies of the fixtures, default also under temp), `P3B_PYTHON` (default `py`), `PLAYWRIGHT_FROM`,
`P3B_BASE_REF` (a commit-ish whose main chunk is built to report the size change; optional). Fixtures are copied to
`P3B_FIXTURES` first so the originals are never opened, and each run hashes them before and after. Screenshots are of the 3D
view panel only, which never shows a file path; keep `P3B_FIXTURES` somewhere neutral if you capture more of the page.

## Producing evidence for a commit

Do this on a **clean checkout of the exact commit** you want the evidence to be about (the evidence folder itself is committed
afterwards):

1. `npm ci` in `desktop`, then `py mkfx.py` (four synthetic projects: 100,000 triangles, three part roles, two plates, inches).
2. `node shots.mjs`: screenshots (light, dark, wide, narrow, no WebGL, lost context).
3. `node behave.mjs`: interaction check, create/dispose loop, real panel mounts under StrictMode, memory, the large scene.
4. `node heap.mjs` and `node heap2.mjs`: JS heap growth per viewer and per mount.
5. `node real-engine.mjs`: the real client against the real engine (sessions, credentials, cancel, ordering, expiry, limit).
6. `npm run build` in `desktop`, then `node csp.mjs`: the production build served with the app's real Tauri CSP.
7. `node collect-results.mjs`: runs the type check, the unit tests and the build, reads the files above from `P3B_OUT`, records
   the commit and whether the tree was clean outside the evidence folder, writes `../results.json`, and copies the screenshots.
8. `node make-readme-tables.mjs`: regenerates the Measurements block of `../README.md` from `../results.json`.
   `node make-readme-tables.mjs --check` fails if the block is out of date.

Every script exits non-zero on a caught failure, a stuck mount, or a changed original file; `collect-results.mjs` also fails
when a check fails.

`behave.mjs` sets the real viewport up the way `defaultViewport.ts` does (create, then `setTool("probe")`); the adapter itself is
covered by `defaultViewport.test.ts`. The create/dispose loop and the app mounts use the real adapter. The control run differs
only in using the viewport's own default tool.
