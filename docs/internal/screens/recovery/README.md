# Recovery screenshots

Captured with `capture.mjs` (real engine, this checkout's vite dev UI, headless Edge) using synthetic data only. Run from the repo root: `ACCEPTANCE_DIR=<folder with node_modules/playwright-core> node docs/internal/screens/recovery/capture.mjs`. The script also starts a loopback mock on a free non-default port (typed into the Port field) that answers the read-only monitoring GET; the run fails if any other request reaches it. No real printer or private path appears.

- `restore-preview.png`: checkpoint of three synthetic files (the original, its prepared copy and a stand-in sliced file), then the prepared copy and original are changed and the sliced stand-in deleted. Shows two changed files, one missing file, an interrupted job (recorded, not resumed), the Port field set to a non-default value, one read-only status request to the loopback mock, and the "Historical, re-read needed" notice. Filename matches are labelled unverified.
- `passport-invalidated.png`: the Job passport page after the same mutation: both files are Invalidated with their bytes-changed reasons, and the declared derivation says the parent differs. File path inputs are hidden by the script so no local path is shown.
- `after-new-checkpoint.png`: the page after "Save sample checkpoint" from the built-in sample workspace (revision 2, no tracked files).
- `monitoring-unverified.png`: one read-only status request to the mock. Printer state and reported filename are shown with the match to a local file marked unverified, and the camera as unknown.

Evidence: fixture-tested and mock-service-tested only.
