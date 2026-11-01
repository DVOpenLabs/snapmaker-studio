# Assemblies screenshots

Evidence label: fixture-tested. Development build, not released software; the footer reads "v1.7.0" only because
the version number has not been bumped on this branch. The Assemblies entry is not in the sidebar in these images
because the shared navigation is not part of this package; the page was opened at `/assemblies`.

Real UI (vite dev server) against the real local engine (`py -m snapstudio_api`, throwaway data folder), headless
Edge, driven by `capture.mjs` in this folder. All figures come from the synthetic sample the page loads with
"Load sample assembly" (made-up names, ids and grams; no printer, no provider, no library, no real model).
Re-run: `ACCEPTANCE_DIR=<folder holding node_modules/playwright-core> node docs/internal/screens/assemblies/capture.mjs`.

| Image | Shows |
|---|---|
| `shortage.png` | Fresh readings. The road spool (150 g left) is short against 240 g stated by six tiles; tiles t4, t5, t6 run short by 90 g. The water spool is unknown: tile 5 states no grams for it, so its total need is "125 g or more". Tile 6 is at 98 percent scale, flagged as a seam-scale difference. Part "Pier" has no tile. |
| `stale-supply.png` | The same assembly with both readings dated a day ago. Both spools read "Reading too old"; no shortage is claimed. |
| `unknown-no-reading-unbound-role.png` | No spool readings and no spool chosen for the water role. The road spool is unknown (no reading); every water slot is listed as having no spool chosen. |
