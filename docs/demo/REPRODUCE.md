# Reproduce the Studio+ development-build demo

> **This is a development build, not the released v1.7.0.** The features shown here (Creative import and Prepare, workspace checkpoint with Passport, and the Lumina-compatible service client) live on development branches. They are not in the v1.7.0 installer, and nothing here is a release candidate. The UI footer and `desktop/package.json` still say "1.7.0" because no version bump was made on these branches.

Everything runs from source on your own machine, on loopback, with disposable synthetic files. No printer, no Snapmaker Orca, no real Lumina service and no real project is involved or touched.

## Evidence labels (what the demo does and does not show)
- **fixture-tested**: the creative-project readers are checked against synthetic archives built by Studio's own test helper from the tools' published output formats. They are not captured from real tool exports.
- **mock-service-tested**: the Lumina client and the read-only monitoring request are checked against hand-written loopback stand-ins.
- Not shown, not claimed: genuine tool exports, Snapmaker Orca opening or slicing, a real Lumina service, any physical U1 or other hardware.

## Source identity
- Product source for all three journeys: commit `22de80733f254c0a38fbca04986c154848e0bc69` (draft PR #144, branch `integ/demo-20261102`). That commit has no demo drivers.
- The drivers and this recipe are on the follow-up branch `docs/demo-repro-20261102` (a draft PR, not merged). Check out that branch: it adds only documentation, the driver scripts in `tools/demo/studio-plus/`, and `THIRD_PARTY_NOTICES.md` on top of the product commit. Check:
  `git diff --stat 22de80733f254c0a38fbca04986c154848e0bc69 HEAD` lists only `docs/demo/`, `tools/demo/studio-plus/` and `THIRD_PARTY_NOTICES.md`.
- Inherited, unresolved: the review finding on PR #140 about `passport export -o` (a directory-swap race) is still open and is not addressed by this build.

## Prerequisites (tested versions; other versions untested)
| Item | Tested |
|---|---|
| OS | Windows 11 (the driver has Linux/Chromium code paths that are **not** tested) |
| Node.js / npm | 24.22.1 / 11.19.1 |
| Python | 3.13 (backend requires >= 3.13) |
| Browser | Microsoft Edge 156 (any Chromium-family browser via `EDGE_PATH`); used headless, driven over the DevTools protocol |
| Disk / network | a few hundred MB for `node_modules`; network only for `npm ci` and `pip install` |

## Install (about 3-5 minutes)
```bash
git clone https://github.com/DVOpenLabs/snapmaker-studio.git
cd snapmaker-studio
git checkout docs/demo-repro-20261102   # product source 22de807 + docs/tooling; see "Source identity"

# backend (virtual environment recommended)
python -m venv .venv                 # Windows: py -3.13 -m venv .venv
.venv/bin/python -m pip install -e backend        # Windows: .venv\Scripts\python -m pip install -e backend

# desktop (Vite dev server dependencies)
cd desktop && npm ci && cd ..
```

## Run the automated journeys (recommended)
The driver generates the synthetic files in a throwaway folder, starts the engine, the Vite dev server, a headless browser and the stand-ins on ephemeral loopback ports, walks the three journeys through the real UI, saves screenshots and a results file, and then stops only the processes it started.
```bash
# PYTHON must be the interpreter that has the backend installed (a relative path is resolved from your current directory)
PYTHON="$PWD/.venv/bin/python" node tools/demo/studio-plus/run.mjs
# Windows (PowerShell):
#   $env:PYTHON = "$PWD\.venv\Scripts\python.exe"; node tools/demo/studio-plus/run.mjs
```
Options: `run.mjs ac` or `run.mjs b` run one part; `DEMO_OUT=<folder>` chooses where screenshots and `results-*.json` go (default `<temp>/studio-demo-out`); `EDGE_PATH` selects the browser. The exit code is non-zero if any step failed or the page logged an error. The drivers are a smoke check of the outcomes listed below, not a full test suite; observed on-screen text is also recorded in `results-*.json`.

Expected result on the `docs/demo-repro-20261102` branch: Journeys A and C plus the sidebar sweep **18/18** steps, Journey B **12/12** steps, 0 page errors. (Recorded on one Windows machine; no clean-machine claim.)

## What the journeys show (expected on-screen wording)
**A. Prepare a supported creative project and see what changed.** Sidebar "Creative import", inspect `sample-kromacut.3mf`: "Looks like Kromacut", with "What Studio read", "Kept untouched", "Could not interpret" and "Original unchanged". "Prepare a U1 copy": "A new file was written" and "Export verification": Kept identical (5), Changed (1) `Metadata/project_settings.config`, Dropped (0), Added (0). The DitherForge Bambu-path sample prepares; the generic-path sample is refused with reasons and writes nothing; an unknown-origin file and a missing file are refused.
**B. Track artifact identity and preview recovery (read-only).** "Recovery" lists exactly the files that will be tracked (original and prepared copy) and why no sliced file is tracked; "Checkpoint this workspace" saves revision 1; "Sample data (not your workspace)" is a separate section. "Passport": "Use this job's files", "Build passport". After the original is replaced and the prepared copy deleted on disk, "Check the files again" marks the original "Invalidated / Bytes changed" and the prepared copy "Invalidated / File not found" because its declared parent changed. The recovery preview shows "changed" and "missing" labelled "Matched by filename only (unverified)". A missing file is a status; it is not byte-verified. Opening another project clears the old passport with a notice. Passport state lives in memory while the app is open, not across a restart. The monitoring stand-in sees only a read-only `GET`, and every file is unchanged after previews.
**C. A Lumina-compatible service you configure yourself, with an explicit format.** Sidebar "Lumina service": the banner says "Tested only against a synthetic stand-in service. No real Lumina installation has been exercised." The format starts on "Choose a format"; after "Check service" and choosing `png`, "Generate" saves a new file and shows its name, size and SHA-256, marked "(not verified)". A format the service did not produce, a non-local address, a stopped service and a missing image are all refused.

## Manual walk-through (no driver)
```bash
python -I tools/demo/studio-plus/make_samples.py <empty-folder>      # synthetic inputs
python -I tools/demo/studio-plus/lumina_standin.py                   # prints {"url": "http://127.0.0.1:<port>"}; Ctrl+C to stop
# engine (POSIX shell syntax; run from <empty-folder>'s parent or any throwaway folder), with throwaway data folders
# and absolute paths: REPO is your checkout, PY the interpreter that has the backend installed
SNAPSTUDIO_DATA_DIR=<tmp>/data SNAPSTUDIO_ORCA_DATA_DIR=<tmp>/orca PYTHONPATH="$REPO/backend" "$PY" -m snapstudio_api   # prints {"port":..., "token":...}
cd "$REPO/desktop" && npx --no-install vite --port <free port> --strictPort --host localhost
# open http://localhost:<vite port>/?api=<engine port>:<token>
```
Then follow journeys A, B and C above using the files in `<empty-folder>`. These commands mirror what the driver runs; the manual form has not been separately timed.

## Safety and cleanup
- All inputs are disposable synthetic files in a throwaway `demo-*` folder under your temp directory. The driver writes only there and to `DEMO_OUT`; it reads the repository's own code and dependencies (and Vite may write its usual cache under `desktop/node_modules`). The original of each journey is replaced or deleted only inside the throwaway folder.
- The driver stops only the child processes it started and have not already exited (engine, Vite, stand-ins, headless browser), and removes its throwaway folder on exit or interrupt. Screenshots and results stay in `DEMO_OUT`, which you can delete. If you kill the driver forcibly, check for a leftover headless browser (it listens on a loopback debugging port).
- Studio keeps its usual rules in this build: it does not slice, never starts a print, writes new copies instead of modifying originals, and has no account or telemetry. The Lumina client sends one image to a service you configure and run, and refuses non-local addresses; the Lumina client and Printer Hub only talk to addresses on your own network, and the Lumina client refuses non-local addresses.

## Remaining manual dependencies and limits
- Needs Node, Python 3.13 and a Chromium-family browser; network is needed only to install dependencies (`npm ci`, `pip install`). The driver starts Vite with `npx --no-install` and the browser with background networking disabled.
- Windows is the only tested OS; the Linux/macOS code paths in the driver (and SIGTERM cleanup of the Vite shell on Linux) are untested.
- The driver was written and run on one Windows machine and verified from a fresh checkout directory, not on a clean machine.
- Upstream credits and licence identifiers for the formats and APIs read are in `THIRD_PARTY_NOTICES.md`.
