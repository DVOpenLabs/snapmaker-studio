# Creative import screenshots

Captured by `capture.mjs` (real engine process, vite dev UI, headless Edge). All archives are synthetic, built by `backend/tests/fixtures/creative/zip_factory.py`; file names are relative, no local paths. Evidence: `fixture-tested`.

| File | Shows |
| --- | --- |
| `fullspectrum-recipes.png`, `forca-expected-and-unknown.png`, `unknown-origin.png` | Earlier inspections (settings-key readers; unknown origin) |
| `ditherforge-inspection.png` | DitherForge facts, read / not-read lists |
| `kromacut-inspection.png` | Kromacut facts; kromacut.config kept and flagged not interpreted |
| `sindricad-inspection.png` | SindriCAD bodies, palette, per-face paint |
| `format-chooser-ambiguous.png` | Ambiguous markers: prompt to choose, explanation (report is the one made before the choice) |
| `format-chooser-choice.png` | SindriCAD chosen: coverage panel |
| `format-chooser-manual-only.png` | ImageMap chosen: manual-only coverage, no identifying marker |
| `unsupported-explanation.png` | Kromacut chosen on a plain 3MF (wrong shape): the actionable refusal text |
| `unknown-prepare-refused.png` | Prepare refused for unknown origin, nothing written |
| `kromacut-prepare-result.png` | Kromacut copy written (root-model component objects now accepted); kept / changed / dropped / added; original unchanged |
| `ditherforge-bambu-inspection.png`, `ditherforge-bambu-prepare-result.png` | DitherForge Bambu-path file: inspection, then copy written; `plate_1.json` listed as dropped; paint 3 of 3 |
| `ditherforge-generic-prepare-refused.png` | DitherForge generic-path file with the format chosen: coverage panel states the Prepare limit; refusal lists the part-id findings; nothing written |
| `sindricad-prepare-result.png` | New copy written outside the source folder (file name and a generic location label only); kept / changed / dropped / added; original unchanged |

Run: `ACCEPTANCE_DIR=<folder with node_modules/playwright-core> node docs/internal/screens/creative/capture.mjs`.
