# Recovery screenshots

Captured with `capture.mjs` (real engine, this checkout's vite dev UI, headless Edge) using synthetic data only. Run from the repo root: `ACCEPTANCE_DIR=<folder with node_modules/playwright-core> node docs/internal/screens/recovery/capture.mjs`. The script also starts a loopback mock on 127.0.0.1:7125 that answers the two read-only monitoring GETs. No real printer or private path appears.

- `restore-preview.png`: checkpoint of three synthetic files, then one edited and one deleted. Shows one unchanged, one changed, one missing file, an interrupted job (recorded, not resumed), and the "Historical, re-read needed" notice. Filename matches are labelled unverified.
- `after-new-checkpoint.png`: the page after "Save sample checkpoint" from the built-in sample workspace (revision 2, no tracked files).
- `monitoring-unverified.png`: one read-only status request to the mock. Printer state and reported filename are shown with the match to a local file marked unverified, and the camera as unknown.

Evidence: fixture-tested and mock-service-tested only.
