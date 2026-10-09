# Vendored SlicerX viewport: provenance and local changes

Source: <https://github.com/slicerx-oss/slicerx> (Apache-2.0), commit
`edb521fe41306dd60d01bda8a0f6bf8aa54fcb29` (committed 2026-10-08, "fix(app): a new open replaces one still
running, with no save prompt"). `@slicerx/viewport` is not published on npm, so the source is vendored.
Attribution: `LICENSE-APACHE` and `NOTICE` (including "Made possible by SlicerX") are kept verbatim from
`packages/ui/viewport/`; the credit is repeated in `THIRD_PARTY_NOTICES.md` and in the 3D view panel.

## What is here

* `viewport/` - every file of `packages/ui/viewport/src/` except upstream `index.ts` (36 files). The upstream
  `viewport.ts` imports the others at module level, so none can be left out without rewriting it.
* `contracts/preview.ts`, `slice.ts`, `settings.ts` - the part of `packages/contracts/src/` the viewport imports
  (SXPV buffer types and constants, `Bed`). `settings.ts` and `slice.ts` are almost all types; the few constants and helpers in them are not used by the viewport.
* `LICENSE-APACHE`, `NOTICE`.
* Studio-authored files (not upstream, no upstream hash): `entry.ts`, `contracts/index.ts`, `error-cause.d.ts`, this file.

NOT vendored: upstream tests (`packages/ui/viewport/test`, so vitest never collects them), bench, demo, `data/`, docs,
`@slicerx/embed`, the engine, profiles and every AGPL-licensed resource of the SlicerX repository.

## Editing code is bundled, and unreachable from Studio

Upstream `viewport.ts` constructs its move, rotate, scale, paint, cut, sketch and push machinery
(`painter.ts`, `paint.ts`, `gizmo.ts`, `cutplane.ts`, `cadtools.ts`, `rings.ts`, `scaling.ts`) in its constructor,
and about 190 lines of it refer to them. They were **not** removed: that would be an extensive rewrite of a pinned file.
They are in the bundle. Studio keeps them inert by construction:

* `src/components/project-scene/readOnlyViewport.ts` is the only importer of the viewport's type, and
  `defaultViewport.ts` the only importer of its factory. The facade never returns the viewport handle, calls
  `setTool("probe")` once (a click only reports what is under the cursor; nothing is selected, dragged or painted) and
  exposes only inspection calls (`readOnly.guard.test.ts` pins the list).
* `readOnlyViewport.test.ts` has a type-level test that editing calls do not type-check on the facade.
* `docs/testing/project-viewer/README.md` records a real-browser run that drives mouse, modifier and keyboard input at
  the viewport and shows no object moved, with a control run (the upstream default tool) that does move it.

Do not describe this code as removed.

## Local changes (every one)

1. **Import path, 7 files.** `from '@slicerx/contracts'` becomes `from '../contracts/index'` in `viewport/palette.ts`,
   `stage.ts`, `summary.ts`, `toolchanger.ts`, `toolpaths.ts`, `types.ts` and `viewport.ts` (one line each).
   Reason: the contracts package is not published and Studio's TypeScript and Vite configuration are not changed to alias it.
2. **`contracts/index.ts`** (new, Studio-authored): `export * from './preview'; export type { Bed } from './slice'`.
3. **`entry.ts`** (new, Studio-authored): re-exports `createViewport` and a handful of types. Replaces upstream `index.ts`,
   which re-exports the editing helpers.
4. **`error-cause.d.ts`** (new, Studio-authored): upstream calls `new Error(message, { cause })`, which the ES2022 lib
   types but this project's ES2020 lib does not (TS2554 at `viewport.ts:292`). The file declares only that constructor
   form. No React, Vite or TypeScript upgrade, no lib or target change.
5. **Line endings:** files are stored with LF, as in the upstream tree and as `.gitattributes` requires.

Nothing else differs; the table below is generated from `git hash-object` of the upstream commit against the vendored files.

## File table

"Upstream blob" is the git blob id at the pinned commit (first 12 hex). "sha256" is of the file as stored here.

| Vendored file | Upstream path | Upstream blob | sha256 (12) | Status |
|---|---|---|---|---|
| `viewport/brim.ts` | `packages/ui/viewport/src/brim.ts` | 479e1e33edfa | fb8a7b864a74 | verbatim |
| `viewport/cadtools.ts` | `packages/ui/viewport/src/cadtools.ts` | 44bff3b6c1cc | 9f82c17e98c9 | verbatim |
| `viewport/camera.ts` | `packages/ui/viewport/src/camera.ts` | 5f4b92397d8e | 32d48e858024 | verbatim |
| `viewport/contour.ts` | `packages/ui/viewport/src/contour.ts` | b245e9e414de | 4a4be2307fda | verbatim |
| `viewport/controls.ts` | `packages/ui/viewport/src/controls.ts` | d50082ebccc5 | 22dc0cbbf6d6 | verbatim |
| `viewport/cutplane.ts` | `packages/ui/viewport/src/cutplane.ts` | 339cf6c39515 | c423d79d8480 | verbatim |
| `viewport/faces.ts` | `packages/ui/viewport/src/faces.ts` | 7648f2e9503f | 22796530c9d3 | verbatim |
| `viewport/firstframe.ts` | `packages/ui/viewport/src/firstframe.ts` | e1eab56a2cda | a7e9d4222ce1 | verbatim |
| `viewport/gantry.ts` | `packages/ui/viewport/src/gantry.ts` | 56dddaaaecf5 | e48191d2d81a | verbatim |
| `viewport/gaps.ts` | `packages/ui/viewport/src/gaps.ts` | eef431a85cf3 | 6e6bfaa3287c | verbatim |
| `viewport/gizmo.ts` | `packages/ui/viewport/src/gizmo.ts` | 00d6dc4215eb | 19472cccc952 | verbatim |
| `viewport/gizmobindings.ts` | `packages/ui/viewport/src/gizmobindings.ts` | 3458538554c3 | 74ed2817883d | verbatim |
| `viewport/gpu.ts` | `packages/ui/viewport/src/gpu.ts` | 08294f84a111 | 458c44e4d0f5 | verbatim |
| `viewport/guides.ts` | `packages/ui/viewport/src/guides.ts` | 234313c6972f | 1348c669721a | verbatim |
| `viewport/headparts.ts` | `packages/ui/viewport/src/headparts.ts` | 9e023b7a8a73 | 3199f9580328 | verbatim |
| `viewport/headpath.ts` | `packages/ui/viewport/src/headpath.ts` | f400e190f8af | b4aaed478599 | verbatim |
| `viewport/heads.ts` | `packages/ui/viewport/src/heads.ts` | 902ef4a53d65 | 3789c7b6f89a | verbatim |
| `viewport/layerheights.ts` | `packages/ui/viewport/src/layerheights.ts` | 8d7c8aa86145 | a4028eda71ad | verbatim |
| `viewport/materials.ts` | `packages/ui/viewport/src/materials.ts` | 53860e313a69 | 7e66c0fcf1a5 | verbatim |
| `viewport/model.ts` | `packages/ui/viewport/src/model.ts` | 6b1ee5cbf4d8 | 40b55e95eb7d | verbatim |
| `viewport/paint.ts` | `packages/ui/viewport/src/paint.ts` | ecfa8be661a9 | 168d45c0d93e | verbatim |
| `viewport/painter.ts` | `packages/ui/viewport/src/painter.ts` | 00cbde84fbc8 | b6df28902cac | verbatim |
| `viewport/palette.ts` | `packages/ui/viewport/src/palette.ts` | 1c03b359dc03 | c490a29b8afe | **patched** (import path) |
| `viewport/post.ts` | `packages/ui/viewport/src/post.ts` | 4f4b5388e138 | 7273ee20d53d | verbatim |
| `viewport/probe.ts` | `packages/ui/viewport/src/probe.ts` | 956d63efa13e | d912fca27139 | verbatim |
| `viewport/purge.ts` | `packages/ui/viewport/src/purge.ts` | 4903d225bf78 | 1745134b0962 | verbatim |
| `viewport/rings.ts` | `packages/ui/viewport/src/rings.ts` | 54a1ceb1f77f | 61f07293728d | verbatim |
| `viewport/scaling.ts` | `packages/ui/viewport/src/scaling.ts` | 4981c9aa9603 | 4c5853161dcd | verbatim |
| `viewport/stage.ts` | `packages/ui/viewport/src/stage.ts` | 4f2c7df9d316 | 372f0ad9a17c | **patched** (import path) |
| `viewport/strikes.ts` | `packages/ui/viewport/src/strikes.ts` | 2437eb5d8802 | 15cd9cbb2807 | verbatim |
| `viewport/summary.ts` | `packages/ui/viewport/src/summary.ts` | c00093cf95f0 | 1d5c85536c8a | **patched** (import path) |
| `viewport/toolchanger.ts` | `packages/ui/viewport/src/toolchanger.ts` | c77bde8a45f6 | be49903b63ad | **patched** (import path) |
| `viewport/toolhead.ts` | `packages/ui/viewport/src/toolhead.ts` | 3c4f42934cc7 | 74b6e31d0859 | verbatim |
| `viewport/toolpaths.ts` | `packages/ui/viewport/src/toolpaths.ts` | 168619855730 | f11427862bf6 | **patched** (import path) |
| `viewport/types.ts` | `packages/ui/viewport/src/types.ts` | 3e41e01471f1 | 59bd8def8c22 | **patched** (import path) |
| `viewport/viewport.ts` | `packages/ui/viewport/src/viewport.ts` | 192b487a6879 | b791a0e21e55 | **patched** (import path) |
| `contracts/preview.ts` | `packages/contracts/src/preview.ts` | 9a5ee2453416 | 8a8713b8e330 | verbatim |
| `contracts/slice.ts` | `packages/contracts/src/slice.ts` | 84d8f8a5aecd | d396019b7dbd | verbatim |
| `contracts/settings.ts` | `packages/contracts/src/settings.ts` | 6660497098be | 20c6047ea2d1 | verbatim |
| `LICENSE-APACHE` | `packages/ui/viewport/LICENSE-APACHE` | 6b1af957a1a6 | 73e6451273ce | verbatim |
| `NOTICE` | `packages/ui/viewport/NOTICE` | fc9730069d4c | 2dca0c6b058d | verbatim |

## Dependencies and licences

* `three` 0.186.1 (MIT), pinned exactly in `desktop/package.json`; the viewport imports `three` and
  `three/addons/controls/OrbitControls.js` (same package). `@types/three` 0.186.0 (MIT, development only; there is
  no 0.186.1 of it) is pinned exactly.
* No other runtime dependency is added. The viewport's own devDependencies (playwright-core, vite, vitest, typescript)
  are not used. `@types/three` pulls type packages only (`@dimforge/rapier3d-compat`, `@tweenjs/tween.js`,
  `@types/stats.js`, `@types/webxr`, `fflate`, `meshoptimizer`); none are bundled.
* The vendored source contains no network access, workers, `eval`, `new Function` or blob URLs (checked with a source
  search), so the Content-Security-Policy in `src-tauri/tauri.conf.json` is unchanged.

## How to update

1. Fetch the new commit and diff `packages/ui/viewport/src` and the three `packages/contracts/src` files above against
   this tree. Re-apply the seven import-path edits, regenerate the table, update the commit id here and in
   `THIRD_PARTY_NOTICES.md`.
2. Keep `three` and `@types/three` pinned to the version the viewport declares; edit `package-lock.json` by hand
   (see the lockfile guard) and prove it with `npm ci`.
3. Run `npm run test`, `npx tsc --noEmit`, `npm run build`, then the browser checks in
   `docs/testing/project-viewer/README.md`. The read-only guard tests must still pass; if a new upstream default turns
   an editing tool on under `probe`, the interaction check fails.
