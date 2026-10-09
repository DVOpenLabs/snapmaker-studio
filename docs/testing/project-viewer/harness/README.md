# Browser harness for the 3D project view

These are the scripts behind the numbers and screenshots in `../README.md` and `../results.json`. They are not part of
the app or its test suite. They need Windows (they start the engine with `py` and stop their own processes with
`taskkill`), Microsoft Edge, and `playwright-core` (run `npm ci` in `tools/acceptance`, or point `PLAYWRIGHT_FROM` at a
folder whose `node_modules` has it). Nothing is sent off the machine and no printer is contacted: the scripts block the
app's own printer polling and any request that is not to localhost.

Environment (all optional): `P3B_OUT` (results and screenshots, default a folder under the system temp directory),
`P3B_FIXTURES` (copies of the fixtures, default also under temp), `P3B_PYTHON` (default `py`), `PLAYWRIGHT_FROM`.
Fixtures are copied to `P3B_FIXTURES` first so the originals are never opened, and each run hashes them before and after.
Screenshots are of the 3D view panel only, which never shows a file path; keep `P3B_FIXTURES` somewhere neutral if you capture more of the page.

1. `py mkfx.py` writes four synthetic projects (100,000 triangles, three part roles, two plates, inches) to `P3B_FIXTURES`.
2. `node shots.mjs` captures the screenshots (light, dark, wide, narrow, no WebGL, lost context).
3. `node behave.mjs` runs the interaction check, the 50-cycle and 75-mount lifecycle checks, memory and the large scene.
4. `node heap.mjs` and `node heap2.mjs` measure JS heap growth per viewer and per mount.
5. `npm run build` in `desktop`, then `node csp.mjs` serves the production build with the app's real Tauri CSP.

`behave.mjs` sets the real viewport up the way `defaultViewport.ts` does (create, then `setTool("probe")`); the adapter
itself is covered by `defaultViewport.test.ts`. The control run differs only in using the viewport's own default tool.
Each run writes `*-results.json` to `P3B_OUT`.
