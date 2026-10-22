# Evidence record — what each page rests on

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

## Evidence by original topic

The table keeps the original lesson numbering because that is how the evidence was gathered; see "Where the earlier lesson evidence went" for where each topic lives now.

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
| 10 | Connect your printer | Printer Hub: "Connect to your U1", **Connect**, **Auto-detect my U1**, "Controls are off until the printer is connected and reachable."; Settings → Printer; Ready now page text; "Printer not found" help text incl. Advanced Mode under Settings → Maintenance | `desktop/src/lib/printerControl.ts` and `components/PrinterControls.tsx` (Pause/Resume sent without a confirmation prompt; Cancel print, Emergency stop, Start this print confirm; **Upload sliced gcode**) | `printer-hub`, `settings-printer`, `ready-now` |
| 11 | Additional tools | Cost & Pricing, Scale Doctor (STL export only), Print Quality symptoms, My designs, Batch prepare, Find Models (approved sites), Settings → Materials provider | `desktop/src/routes/*.tsx` | `cost`, `scale`, `print-quality`, `projects`, `batch`, `find-models`, `settings-top` |
| 12 | When something goes wrong | Help page: update check wording, "Show me what it contains", "Save it to a file", redaction statement | `docs/windows-install.md` (updating, data kept), `.github/ISSUE_TEMPLATE/` | `help-updates` |

## Evidence behind the four interactive examples

An example is only included when every option and every piece of feedback rests on real Studio behaviour. None of them
calls the engine, a printer or the network: they move between pictures and text.

| Example | What it teaches | Evidence |
|---|---|---|
| Misplaced, or too big to fit? (stage 3) | An object hanging off the plate can be shifted back; one that is wider or longer than the plate cannot, and Studio refuses rather than guess | Three real captures (`compat-top`, `placement-oversized`, `placement-spread`) from example files built by `tools/fixtures.py`. The refusal text "Moving the objects as one piece would not bring them all on…" and the offered **Move onto the plate (saves a copy)** button were read from the running app; `backend/snapstudio_core/plate_placement.py` confirms Studio only moves placement and refuses when one move cannot fix it |
| Assigning a material is not loading it (stage 3) | Project Materials records a choice for the copy; nothing is loaded, heated or sent | `pm-review` capture; `docs/RELEASE_NOTES.md` v1.5.0; Studio's "never takes control" rule |
| Read the change (stage 4) | Kept / adjusted / not applied / yours to do in Orca | `fidelity` capture: "What survived preparing this copy", "Changes Studio made", "Optional recommendations (not applied)" |
| Unknown is not incompatible (stage 6) | the printer name in the G-code header is a confirmed fact; the finding **Sliced for a different printer** built on an unrecognized name is rated likely, not confirmed (`backend/snapstudio_core/post_slice.py`); "Studio can't check this" is a gap | `job-other-printer` capture of `example_other_printer.gcode` (a synthetic job whose header names another printer), plus `after-result` for the unknowns |

## Where the earlier lesson evidence went

The first version of the guide was twelve numbered lessons. The redesign keeps all of that verified content, regrouped:
lessons 2, 4, 5, 6, 8 and 9 became the six stages of the example path (`path.json`); lessons 1, 3, 7, 10, 11 and 12 became
task pages (`tasks.json`); every warning wording became a page of its own (`problems.json`). Old lesson links
(`#install`, `#read-checks`, `#fix-and-prepare`, …) are mapped to the new pages in `guide.json` → `redirects`, are tested
in the browser run, and also work without JavaScript. Two screenshots no longer used by any page (`this-print-lower`,
`colours-painted`) were removed along with their capture entries.

## Conflicts resolved (product won over old text)

| Where | Old text | What the product does | Action |
|---|---|---|---|
| In-app **Help** | Find Models: "No downloads yet." | v1.4.0 added Model Connect: you download with the site's own button and Studio adds supported downloads to your Library | Help text corrected (`desktop/src/routes/Help.tsx`) |
| In-app **Get Started** | "Download manually from the source site (v1 doesn't import for you)." | same as above | Corrected (`desktop/src/routes/BeginnerWorkflow.tsx`) |
| `docs/PRINTER_COMPATIBILITY.md` | "describes v1.3.1, the current release" | v1.5.0 is current | Not copied into the guide; not edited here |
| Dashboard "Start your first print" | lists "Source Check" as a step | Source Check is a tab inside Compatibility | Guide follows the real flow instead |

## Gaps, stated plainly

* **No connected-printer screenshots.** No printer was contacted. The printer task shows Printer Hub before a printer answers and
  says so. Live-state wording comes from the app's own text and from the source.
* **No Snapmaker Orca screenshots.** The maintainer's own Orca was running during capture, so no second Orca instance was
  started. The Orca stage describes Orca's side in general terms (printer, filaments, Arrange, **Slice plate**, export) and tells
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

## Verification run (redesign, local, before review)

| Check | Result |
|---|---|
| `node tools/build.mjs` (content, screenshots, alt text, hotspot positions and overlaps, every link target, every example answer, privacy lint) | 6 stages, 27 tasks, 23 warnings, 4 examples, 30 screenshots, 56 searchable pages, no problems |
| `node tools/check.mjs` (links, ids, alt text, no third-party requests, no inline script or style, WCAG contrast of every colour pair in both themes) | 49/49 |
| `node tools/e2e.mjs` (Edge, desktop 1280 px and phone 390 px, dark and light, strict Content-Security-Policy, plus a no-JavaScript run): home order and the folding map, no collisions in the workflow map (also with a wide fallback font), every page by deep link, every old lesson link, search (results, excerpt, empty state, suggestions, `/` shortcut), task and warning filters, all four examples including a deliberate wrong answer, viewer focus handling, numbered notes, keyboard-only paths, theme switch, wide fallback font, overflow, console errors | 1462/1462 |
| `.github/workflows/guide-ci.yml` on GitHub-hosted Linux Chrome | not yet run (needs the pull request) |
| `node tools/check.mjs --online` | not run (needs the network) |
| Desktop / backend test suites | not run: this change touches only `site/guide/` and the capture tooling, not Studio itself |

Screenshots of the finished redesign, desktop and phone, both themes: `evidence/redesign/`. The earlier `evidence/screenshots/`
and `evidence/live/` show the previous, lesson-based guide.

### Earlier deployment (2026-10-07)

The lesson-based guide was published with GitHub Pages from `main` by `.github/workflows/guide-pages.yml` after PR #79 passed all
checks, including `guide-ci.yml` on Linux Chrome; its live run was 727/727. Pages cannot set response headers, so the strict
Content-Security-Policy in `deploy/security-headers.txt` is not applied there; the guide makes no network requests of its own.
The redesign replaces this version when its pull request merges: `main` publishes `site/guide/public` through `guide-pages.yml`.

## Editorial review (2026-10-07)

All English text was reviewed in two independent passes, then reread after the corrections: Claude Opus (`claude-opus-5-5`) and Codex Sol (`gpt-5.6-sol`), identities confirmed from the Opus transcript's `message.model` field and the Codex rollout. Corrections were limited to guide copy (American spelling, grammar, unclear or ambiguous wording, stale lesson references, a few sentences that contradicted documented behavior). Quoted product labels and messages were left as the app shows them.

### Product copy issues found (not changed here; for the maintainer)

1. Settings → Printer hint says send, pause, resume and cancel "run only when you confirm"; the code sends Pause and Resume without a confirmation prompt (`PrinterControls.tsx`). The guide follows the code.
2. Mixed British and American spelling in the app: "Colours and toolheads", "6 colours, 4 toolheads", "Load the colours…", "Colour changed to Red" versus "Colors & Materials" and "Plate Color Remap".
3. Unresolved plural placeholders: "1 object(s) moved…", "Found 5 invalid-value issue(s) and 2 warning(s).", "1 thing(s) are worth settling…".
4. "Moving the objects as one piece would not bring them all on…" lacks a destination ("onto the plate").
5. "Upload sliced gcode" should read "G-code" like the rest of the app.
6. Cost Doctor says "true cost to make" for an estimate built on user assumptions.
7. "Not proven separable — reserve a toolhead each" is jargon for beginners.
8. Capitalization varies for one feature ("This print"/"This Print", "Batch prepare"/"Batch Prepare", "After slicing"/"After Slicing").
9. The page text for a missing file starts in lowercase and has no final period ("that file does not exist").
10. Existing observation 2 above (damaged 3MF still shows "Checked — here's what we found…").

## Pre-publication factual review (2026-10-07)

Before publishing the corrected copy, Astra (`gpt-6-astra`) checked the guide's behavioral claims against the engine and desktop code, independently of the editorial review by Fable (`claude-fable-5-1`). It first confirmed six overclaims (Pause/Resume wording, "carries over only what it can verify", "Unverified … not an error", "Nothing is wrong with the job", "confirmed only from the file", "Kept needs no action") and found one more: an unrecognized printer name is rated *likely*, not *confirmed*, by the engine. After those were corrected, it returned five residual blockers. Their resolution:

| Blocker | Corrected wording (now in the guide) | Code and tests it rests on |
|---|---|---|
| R01 — "Not checked" does not always mean "copied unchecked" | *Anything it has no reader for … is listed here as well, because Studio cannot say what happened to it. Some of that data is copied as it was but never checked; some, such as PrusaSlicer settings Orca does not use, is left out.* | `backend/snapstudio_core/fidelity.py` (unsupported rows are grouped with removed rows), `backend/snapstudio_core/prusa.py`, `desktop/src/lib/fidelity.ts` (`statusLabel`); `guideClaims.test.ts` requires the guide to use the app's label |
| R02 — "could not check" is not only an unexplained change | *Studio could not verify this item. It may be an unexplained change, or something Studio could not compare.* Compare with the original in Orca and report anything unexplained | `fidelity.py` (unverified rows), `desktop/src/lib/fidelity.ts` (`fidelityHeadline`); `guideClaims.test.ts` takes the advice from the app and requires the guide to repeat it |
| R03 — "Kept" does not mean Orca uses it | *Kept means the value reached the copy, not that Orca uses it: read any note on the row.* | `backend/snapstudio_core/target_reachability.py`, `desktop/src/lib/fidelity.ts`, `fidelity.test.ts` |
| R04 — confirmed evidence can come from you; offline unknowns can be filled by your own confirmation | *Studio has direct evidence: it read this in your file or from your printer, or you confirmed it yourself.* Offline unknowns stay unknown *unless you confirmed it yourself, such as a nozzle size* | `backend/snapstudio_core/post_slice.py`, `backend/snapstudio_api/service.py` (saved nozzle confirmations), `test_preflight.py` |
| R05 — a missing Move button has several causes | *Either every object already fits, or one move cannot fix the layout (Studio also never moves multi-plate projects).* | `backend/snapstudio_core/plate_placement.py` (assessment unavailable, multi-plate refusal); `backend/tests/test_guide_claims.py` runs the placement example through the engine |

Two further notes from that review were also applied: the watch-folder wording now says it looks only while **After Slicing** or **This print** is open (the poll has no focus or visibility gate, `desktop/src/components/OrcaRoundTrip.tsx`), and the exercise record above now states that the printer name in the header is the confirmed fact while the mismatch finding is *likely*.

New regression checks: `backend/tests/test_guide_claims.py` (engine-derived placement and printer-name facts), `desktop/src/lib/guideClaims.test.ts` (printer-action policy, prompt text and fidelity labels from app code), and a wording tripwire in `tools/build.mjs`. They establish that the guide agrees with current engine and app code on those points. They do not establish prose quality, physical printer behavior, Snapmaker Orca behavior, or that a paraphrase of a past overclaim cannot return. They were checked to fail against the earlier wording.
