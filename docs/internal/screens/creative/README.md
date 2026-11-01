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
| `unsupported-explanation.png` | Unknown tool: what was seen, not supported, what to do |
| `unknown-prepare-refused.png` | Prepare refused for unknown origin, nothing written |
| `kromacut-prepare-refused.png` | Prepare refused by the engine's structure check, with the findings |
| `sindricad-prepare-result.png` | New copy written outside the source folder; kept / changed / dropped / added; original unchanged |

Run: `ACCEPTANCE_DIR=<folder with node_modules/playwright-core> node docs/internal/screens/creative/capture.mjs`.
