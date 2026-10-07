# Evidence record — what each lesson rests on

The guide describes **Snapmaker Studio v1.5.0** (tag `v1.5.0`; the interface in `main` at the time of writing is the
same, apart from the Help / Get Started links added with this guide). Every button label in the lessons was read from the
running interface or from the source that renders it. "UI" below means the label or behaviour was observed in the running
app during capture (`tools/capture.mjs`, a real Studio engine with disposable data and example files); "Source" means it
was read from the named file because it cannot be reached without a printer or the installed shell.

## Method

* Studio's real engine (`snapstudio_api`) and its real web UI were started with a throwaway data folder, no printer, no
  provider (except a made-up Spoolman on loopback for Project Materials) and example files from `/examples`.
* Labels, statuses and file names quoted in the lessons were copied from page text captured during those runs.
* The screenshot that needs the desktop shell (`handoff.png`, where Studio looks for Snapmaker Orca) was captured from an
  **installed** copy of the v1.5.0 release installer inside the repository's isolated test harness.
* Where older help text or comments disagreed with the running product, the product won (see "Conflicts resolved").
* Nothing was connected to a printer, nothing was sliced, and Snapmaker Orca was never launched by the capture.

## Lessons

| # | Lesson | Verified in the UI | Verified in source / docs | Screenshots |
|---|---|---|---|---|
| 1 | Install and open | Home screen, sidebar items, `v1.5.0` in the status bar, footer "Local-only · nothing leaves your network" | `docs/windows-install.md`, `docs/linux-install.md` (SHA256 check, SmartScreen, `sudo apt install ./….deb`, `snapmaker-studio-desktop`, data folder), `docs/RELEASE_METADATA.md` (hashes live there only) | `home` |
| 2 | Open your first model | Opening `sample_cube.stl` lands on the Workspace; status line, verdict "Can prepare a U1 copy", "What's in this design" (20 × 20 × 20 mm, 0 colors, 0 parts, filament estimate); STL note "does not include creator slicer settings"; damaged 3MF → Compatibility says "Studio could not open this file as a 3MF project." | `desktop/src/routes/Cockpit.tsx` (drag-and-drop wording) | `workspace-stl` |
| 3 | Understand "This print" | This print page: title, stages "1. Before slicing", "2. Prepared", "3. After slicing", "Nothing prepared yet.", "Pick up sliced jobs automatically", "Printer not found / STUDIO CAN'T TELL"; Advanced sidebar list | `desktop/src/lib/nav.ts` (Simple vs Advanced items, "More tools"), `routes/Cockpit.tsx` | `this-print-top`, `this-print-lower`, `nav-advanced` |
| 4 | Read the checks | Compatibility Doctor: placement finding, "Found 5 invalid-value issue(s) and 2 warning(s).", NEEDS ATTENTION / HEADS UP labels, "Do this:" lines, "Technical detail"; This print: STUDIO CAN'T TELL / LOOKS RIGHT; the line "“Studio can't tell” means…" | `desktop/src/components/PreflightCard.tsx` wording as rendered | `compat-top`, `compat-findings` |
| 5 | Fix placement and prepare | "Hangs 55.0 mm past the right edge."; **Move onto the plate (saves a copy)** writes `demo_offplate_foreign_placed_U1.3mf` next to the original; success text; opening that copy and pressing **Prepare U1 copy** writes `…_placed_U1_SnapmakerU1.3mf` plus a `.orig.3mf`; the three preparation modes. The engine re-assessed both new files: no object off the plate | `backend/snapstudio_core/plate_placement.py` (`prepare_placed_copy` moves only placement; refuses when one move cannot fix it), `convert.py` (`.orig.3mf` backup), `desktop/src/components/PlacementCard.tsx` | `workspace-3mf`, `move-result`, `handoff` |
| 6 | Review what changed | "What survived preparing this copy" (14 kept · 2 changed), "What Studio changed (2)", "What stayed the same (14)", "Changes Studio made", "Before and after", "Return to the original", "Kept from the original file", "Optional recommendations (not applied)" | `tools/acceptance/checks.mjs` (label "What Studio could not carry over") | `fidelity` |
| 7 | Plan colours and materials | "6 colours, 4 toolheads — possible without repainting.", the three groups, "Load the colours in the order the project lists them.", painted-colour box; Project Materials candidates, **Use this preset**, **Choose an installed preset**, **Keep project's filament**, **Review & prepare**, **Prepare with these choices**, **Back to choices** | `desktop/src/routes/PlateRemap.tsx` and `lib/plateRemapWizard.ts` (**Plate N** buttons, **Preview changes**, "Create remapped copy — original stays unchanged"), `docs/RELEASE_NOTES.md` v1.5.0 (user-preset wording) | `colours-overview`, `colours-painted`, `pm-recs`, `pm-review` |
| 8 | Open it in Snapmaker Orca | **Open in Snapmaker Orca** shown by the installed app; "What now?"; the "Next:" line | `desktop/src/components/OrcaHandoff.tsx`, `lib/orca.ts` (button states and the three error messages) | `handoff` |
| 9 | Bring the sliced job back | After slicing page: "Pick up sliced jobs automatically", "Open the G-code your slicer produced", **Check this job**, "Ready to send?", the "Studio can't check this" findings, "What the printer will actually do" (sliced by / for / prints from / layers / time / filament / file) | `tools/fixtures.py` writes the example job (values mirror `tools/acceptance/run.ps1`) | `after-empty`, `after-result`, `after-facts` |
| 10 | Connect your printer | Printer Hub: "Connect to your U1", **Connect**, **Auto-detect my U1**, "Controls are off until the printer is connected and reachable."; Settings → Printer; Ready now page text; "Printer not found" help text incl. Advanced Mode under Settings → Maintenance | `desktop/src/lib/printerControl.ts` and `components/PrinterControls.tsx` (Pause/Resume immediate; Cancel print, Emergency stop, Start this print confirm; **Upload sliced gcode**) | `printer-hub`, `settings-printer`, `ready-now` |
| 11 | Additional tools | Cost & Pricing, Scale Doctor (STL export only), Print Quality symptoms, My designs, Batch prepare, Find Models (approved sites), Settings → Materials provider | `desktop/src/routes/*.tsx` | `cost`, `scale`, `print-quality`, `projects`, `batch`, `find-models`, `settings-top` |
| 12 | When something goes wrong | Help page: update check wording, "Show me what it contains", "Save it to a file", redaction statement | `docs/windows-install.md` (updating, data kept), `.github/ISSUE_TEMPLATE/` | `help-updates` |

## Conflicts resolved (product won over old text)

| Where | Old text | What the product does | Action |
|---|---|---|---|
| In-app **Help** | Find Models: "No downloads yet." | v1.4.0 added Model Connect: you download with the site's own button and Studio adds supported downloads to your Library | Help text corrected (`desktop/src/routes/Help.tsx`) |
| In-app **Get Started** | "Download manually from the source site (v1 doesn't import for you)." | same as above | Corrected (`desktop/src/routes/BeginnerWorkflow.tsx`) |
| `docs/PRINTER_COMPATIBILITY.md` | "describes v1.3.1, the current release" | v1.5.0 is current | Not copied into the guide; not edited here |
| Dashboard "Start your first print" | lists "Source Check" as a step | Source Check is a tab inside Compatibility | Guide follows the real flow instead |

## Gaps, stated plainly

* **No connected-printer screenshots.** No printer was contacted. Lesson 10 shows Printer Hub before a printer answers and
  says so. Live-state wording comes from the app's own text and from the source.
* **No Snapmaker Orca screenshots.** The maintainer's own Orca was running during capture, so no second Orca instance was
  started. Lesson 8 describes Orca's side in general terms (printer, filaments, Arrange, **Slice plate**, export) and tells
  readers that Orca's menu wording can differ by version.
* **Plate Color Remap** controls are documented from `PlateRemap.tsx`, not from a screenshot.
* **Linux** was not captured: all screenshots are from Windows-hosted runs. The guide cites the Linux install guide's own
  verification statement.
* **Project Materials on a user-made preset**: the guide repeats the release's limitation (Orca may keep the project's
  values); it does not claim otherwise.
* The example **sliced job** is a tiny synthetic file written for the guide; its numbers (12 layers, 4 min, 0.36 g) are not
  from a real print.

## Product observations made while capturing (not changed by this work)

These are recorded for the maintainer; none is described in the guide as working a particular way.

1. On **This print**, after a copy is prepared, the "What survived preparing this copy" and "Changes Studio made" cards
   appear twice (once from the stage itself, once inside the Orca handoff panel).
2. For a **damaged 3MF**, the Workspace still says "Checked — here's what we found. Press Prepare U1 copy when you're set."
   and offers **Prepare U1 copy**, while Compatibility says "Studio could not open this file as a 3MF project." The guide
   tells readers to trust Compatibility.
3. **Project Materials** with a damaged 3MF shows "project materials failed (500)" under the card.

## Verification run (this commit)

| Check | Result |
|---|---|
| `node tools/build.mjs` (content, screenshots, alt text, hotspot positions and overlaps, walkthrough circle numbers, privacy lint) | built 12 lessons, 29 screenshots, no problems |
| `node tools/check.mjs` (links, ids, alt text, no third-party requests, strict-CSP readiness, WCAG contrast of every colour pair in both themes) | 49/49 |
| `node tools/e2e.mjs` (Edge, desktop 1280 px and phone 390 px, dark and light, plus a no-JavaScript run; strict Content-Security-Policy; every deep link, Next/Back/browser history, saved position, Start again, theme, mobile menu, image viewer focus handling, every hotspot, every walkthrough, overflow, console errors) | 727/727 |
| Desktop: `npm run test` · `tsc --noEmit` · `npm run build` | 731 passed (725 + 6 new for the Help / Get Started link) · clean · built |
| Backend: `pytest` | 2805 passed, 13 skipped |
| `node tools/check.mjs --online` (external links answer) | not run during capture: it needs the network and the guide is not deployed yet |
| `.github/workflows/guide-ci.yml` on GitHub-hosted Linux Chrome | written, not yet run |

Finished-guide screenshots are in `evidence/screenshots/` (desktop and phone, both themes, viewer, walkthrough, no-JavaScript).

### Live deployment (2026-10-07)

Published with GitHub Pages from `main` by `.github/workflows/guide-pages.yml` after PR #79 passed all checks, including `guide-ci.yml` on Linux Chrome. `node tools/e2e.mjs --url https://dvopenlabs.github.io/snapmaker-studio/` against the live site: **727/727** (every lesson deep link, assets, hotspots, walkthroughs, viewer, desktop and phone, both themes, no-JavaScript). Screenshots of the live site: `evidence/live/`. Pages cannot set response headers, so the strict Content-Security-Policy in `deploy/security-headers.txt` is not applied there; the guide makes no network requests of its own.
