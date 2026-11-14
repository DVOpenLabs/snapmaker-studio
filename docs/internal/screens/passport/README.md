# Job passport screenshots

Development build, not released software. Captured from the portfolio integration worktree (base integ/phase2 5d4a27b plus the Studio+ tracks). The footer reads "v1.7.0" only because the version number has not been bumped on this branch. Evidence label: fixture-tested (synthetic files, no printer, no real project).

Method: the real engine (`py -3 -m snapstudio_api`, throwaway data folder) and this checkout's own web UI (vite dev server) driven in headless Microsoft Edge through `playwright-core`, the same approach as `docs/internal/screens/prepare-setup/README.md`. Three tiny synthetic text files (`bracket.3mf`, `bracket_u1.3mf`, `bracket_u1.gcode`, a few bytes each, not real 3MF or G-code) were written to a scratch folder, typed into the three path fields, and a passport was built with the recipe and mapping fixtures from `backend/tests/fixtures/passport/`. The scratch folders were deleted afterwards. The browser is Edge, not the Tauri window.

| Image | Shows |
|---|---|
| `chain-intact-recipes-kept-and-lost.png` | Just built: all three files match; both links read "declared by user"; two recipes and two mappings kept; four items listed as not carried over, each with a reason |
| `original-changed-invalidates-chain.png` | The original was replaced by a same-size file with different bytes and the files were checked again: the original, the prepared copy and the sliced output are all Invalidated, the first link is flagged "Declared parent differs", the second link (judged on its own bytes) still matches |
| `prepared-missing-unverified.png` | The original was restored and the prepared copy deleted: the prepared copy and the sliced output are "Not verified" (never "matches"), the summary says 2 of 3 files could not be checked |

Every image was opened and inspected after capture. No path text is visible: the files are typed as relative names and the engine ran with the scratch folder as its working directory. The browser console showed React prop warnings from the existing sidebar and one 404 for a static asset; none from the passport view.
