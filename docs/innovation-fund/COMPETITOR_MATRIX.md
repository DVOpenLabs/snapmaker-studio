# Competitor & ecosystem matrix

> **Superseded for competitive purposes by
> [PHASE1_POSITION.md](PHASE1_POSITION.md)**, which reassesses the Phase 1
> entries (41 when it was written; the Fund page now shows 66–67). This file remains the deeper
> per-project reference — licences, capability detail, interoperability — and is
> still accurate on those points.

**Compiled 2026-08-22** from the projects' own repositories, licence files, release
notes and documentation, plus the published Innovation Fund project list. Every
row states what was verified and from where. Anything that could not be confirmed
from a primary source is marked **UNVERIFIED** rather than guessed.

This document exists to answer one question honestly: *given all of these, why
should Snapmaker Studio exist?* The answer is in
[DIFFERENTIATION_STRATEGY.md](DIFFERENTIATION_STRATEGY.md); this file is the
evidence behind it.

## Snapshot 2026-10-04 — verified capabilities only

Read from each project's own repository or site on 2026-10-04. UNKNOWN means not stated
in a primary source; nothing here is inferred. Studio does not slice; it audits and
prepares around the slicer.

| Project | What it verifiably is | Slices | Reads the printer | Audits a file | Shows what a conversion lost | Stars |
|---|---|---|---|---|---|---:|
| makerworld-to-snapmaker-u1 | Browser extension: MakerWorld profile to U1 3MF, auto-fixes, error report | no | no | error report only | not stated | 48 |
| Bambu2Orca | Client-side Bambu/Creality/Anycubic 3MF converter, keeps paint | no | UNKNOWN | UNKNOWN | UNKNOWN | no repo found |
| bambu-to-snapmaker-u1 | Docker web converter, YAML filament rules, diff view (PolyForm Noncommercial licence) | no | no | diff view | partial (diff) | 22 |
| bl2u1 | Flask converter, keeps paint, pads to 4 filaments (stale since April) | no | no | no | no | 75 |
| btu | Go CLI: slot planning from paint, verifies a temp 3MF; `--replace` overwrites the source | no | no | own-output check | partial | 2 |
| Nozzle Buddy | Web converter between 10 slicers | no (not stated) | no | not stated | UNKNOWN | no repo |
| proofprint-u1 | Browser G-code preflight, heuristic score, read-only Moonraker status | no | status only | **yes, G-code level** | no | 5 |
| u1hub | Self-hosted fleet dashboard; Convert to U1 beside the original; opt-in LLM pre-flight | no | **yes** | partial, LLM-based | not stated | 66 |
| orca-auto | Headless Orca automation, queues to U1, reads spools | **yes** | **yes** (spools) | no | no | 2 |
| ChromaMatter | Colour editor plus an unofficial Orca fork | fork does | no | own export only | no | 6 |
| SnapCentral | Education/model-info site demo | no | no | no | no | no software |
| Adaptive Manufacturing Planner | Orca-fork branch: bead-width planning, synthetic benchmarks | **yes** | no | no | no | 0 |

Two cautions that follow from the table. Others do compare a file against the printer
(u1hub, with an LLM) and others do audit files (proofprint-u1, on G-code), so neither
is claimed as Studio's alone. And the ChromaMatter entry's Fund-page address is a
`chatgpt.site` host that could not be independently tied to its author (its GitHub repo
matches).

---

## 1. The Phase 1 field

The Fund's own category counts for the Phase 1 projects (41 when this section was written)
(source: <https://www.snapmaker.com/innovation-fund>):

| Fund category | Projects |
|---|---|
| Software | 20 |
| Hardware Mod | 7 |
| 3D Model Editor | 6 |
| Firmware | 5 |
| 3MF Converter | 2 |
| App | 1 |

Grouped by what they actually *do* rather than by the form they were submitted in:

| Functional cluster | Approx. count | Comment |
|---|---|---|
| Slicer forks / OrcaSlicer modifications | ~8 | The most contested space. "Slicing Engine" is the most common secondary tag (16/41). |
| CAD and colour/texture model editors | ~10 | Includes three separate image→layered-colour tools. |
| Bambu/MakerWorld → U1 format converters | ~5 | Two are near-identical browser tools. |
| Fleet dashboards / monitoring / mobile control | ~6 | |
| Hardware filament-capacity mods | ~4 | |
| **Pre-print validation and risk diagnostics** | **1** | Snapmaker Studio. |
| **Cost / material-consumption estimation** | **0** | |
| **Beginner onboarding, education, accessibility** | **0** | |
| Print-failure detection by camera/vision | 0 | |

The two facts that matter most for positioning: the crowded clusters are all
*doing* things to a file or a machine, and the empty clusters are all *explaining*
things to a person.

---

## 2. Detailed teardown

Licence column is the decisive one for us: Studio is MIT, so an AGPL or GPL
project can be interoperated with over a documented interface but **never** read
for code. Every entry below was inspected for behaviour and interface only.

### Snapmaker Orca — the official slicer

| | |
|---|---|
| Source | <https://github.com/Snapmaker/OrcaSlicer> |
| Purpose | Snapmaker's OrcaSlicer fork; the sanctioned slicer for the U1 |
| Target user | Every U1 owner |
| Licence | **AGPL-3.0** (inherited Slic3r → PrusaSlicer → Bambu Studio) — **copy-unsafe for MIT** |
| Stack | C++ / CMake / wxWidgets |
| Activity | ~26,100 commits, 232★, 97 forks, 86 open issues — actively maintained by the vendor |
| Killer feature | Ships the official U1 machine/process/filament profile set |
| What it does better | It slices. Studio does not and will not. |
| Weakness Studio addresses | It slices; it does not explain. No pre-print risk analysis, no plain-language diagnosis. Its "out of bounds" message names no object and no reason. |
| Interop | Studio prepares a file and hands it over as a single command-line argument. One way, no control. |

### FOrcaSlicer — per-head nozzle sizes

| | |
|---|---|
| Source | <https://github.com/jiyang1018/FOrcaSlicer> |
| Purpose | Snapmaker Orca fork unlocking a different nozzle size per toolhead, plus a shell-over-core colour mode |
| Licence | **AGPL-3.0** — **copy-unsafe for MIT**; behaviour reference only |
| Activity | 21 releases, 19★, last push 2026-08-14 |
| Killer feature | Per-head nozzle diameter and per-feature extruder assignment. Its README reports a gear plate going from 8 h 39 m to 5 h 15 m |
| Install friction | Separate application; unsigned macOS build; **Snapmaker account login on first run** |
| Weakness | Self-described "research preview… not yet independently bed-tested at this release". Its own issue #8 documents fork drift against upstream Snapmaker Orca |
| What Studio learns | The U1's four heads *can* carry different nozzle diameters. Studio detects when a project already uses mixed nozzle sizes and names this fork as the tool that exploits it |
| What Studio must not do | Build a slicer. Per-feature extruder assignment is toolpath generation |

### OrcaSlicer ImageMap — printing a texture

| | |
|---|---|
| Source | <https://github.com/sentientstardust-dev/OrcaSlicer-ImageMap> (GitLab mirror: `sentient_stardust/orcaslicer-imagemap`) |
| Licence | **AGPL-3.0** — **copy-unsafe for MIT** |
| Activity | 33 releases, 119★, last push 2026-08-01 |
| Killer feature | Prints a raster image into a surface using per-layer overhang modulation with one tool change per layer; converts between image textures, vertex colours and painted 3MF regions |
| Weakness | Explicit "use at your own risk" beta disclaimer; issue tracking split across GitLab and GitHub |
| What Studio learns | Texture data in a model is real, usable information that most slicers discard. Studio detects `3D/Textures/` parts and names this fork |

### makerworld-to-snapmaker-u1 — the closest functional competitor

| | |
|---|---|
| Source | <https://github.com/Dragon2203/makerworld-to-snapmaker-u1> |
| Purpose | Browser extension that converts a MakerWorld project to a U1 project at the moment of download, preserving the creator's own print profile |
| Licence | **MIT shell, but** `LICENSE-POLYFORM` + `THIRD_PARTY_NOTICES.md` state that conversion logic *and bundled reference profiles* derive from a **PolyForm-Noncommercial-1.0.0** project — **treat as copy-unsafe** |
| Activity | 12 releases, 21★, last push 2026-08-06 |
| Killer feature | It converts at the point of choice, in the page, before a file exists locally — and reads the creator's selected profile from the page, which a desktop app never sees |
| Weakness | Couples to the MakerWorld DOM: three of the last four releases fixed MakerWorld UI regressions. One domain pair only. No Chrome Web Store listing. It has no mechanism to check its own output; like Studio, it asks users to review the result in Snapmaker Orca before printing |
| **Parity status** | Its documented conversion rules are implemented independently in Studio — see §3 |

### U1 Print Hub (u1hub) — the closest Printer Hub competitor

| | |
|---|---|
| Source | <https://github.com/dlgambill/u1hub> |
| Licence | **MIT** — compatible; the only project here that is legally safe to read |
| Activity | 11 releases, **51★** (the highest of the GitHub-hosted Fund entries measured), last push 2026-08-17 |
| Killer feature | Scan a spool's NFC/QR tag with a phone and bind it to a printer slot in one motion; "what can I print now" spool matching |
| Protocol knowledge it documents | The U1 answers **Moonraker on port 80** as well as Klipper's standard 7125; per-head filament colours live in the `print_task_config` object; toolhead mapping uses the firmware's own `SET_PRINT_EXTRUDER_MAP` / `SET_PRINT_FILAMENT_CONFIG` macros; object skipping uses standard Klipper `exclude_object` |
| Safety posture worth benchmarking | Its tunnel refuses to start without a password gate; smart-plug off is hard-blocked while printing; its diagnostics bundle scrubs tokens and aliases IPs *before writing the file* |
| What it does better | Cross-machine fleet state, phone access, printer-to-printer copies, persistent queue, physical spool binding |
| Weakness | Non-U1 printer support is beta and verified only against a mock; plain HTTP on LAN; single fixed port |
| Studio's relationship to it | **Complementary, not competing.** Studio is pre-print; the Hub is at-and-after print. Studio's registry names it as the next step for an already-sliced project |

### Snapmaker U1 Toolkit

| | |
|---|---|
| Source | <https://github.com/bbolinger/snapmaker-u1-toolkit> |
| Licence | **MIT** |
| Activity | 317 commits, 17★, last push 2026-07-30 |
| Killer feature | A human approval gate: a print starts only after an operator approves it against a fresh photo of the bed, with a cancellable grace window |
| Weakness | Command-line only; Telegram is a hard requirement for the headline flow; profile logic parses G-code comments rather than reading geometry |
| Philosophical neighbour | Its stance — "AI can prepare, explain and preview, but cannot start prints unilaterally" — is the closest thing in the ecosystem to Studio's own rule that Studio never takes autonomous control |

### SnapmakerU1 Extended Firmware — the ecosystem's centre of gravity

| | |
|---|---|
| Source | <https://github.com/paxx12-snapmaker-u1/SnapmakerU1-Extended-Firmware> |
| Licence | **GPL-3.0** — **copy-unsafe for MIT** |
| Activity | **934★, 111 forks, 85 open issues**, pushed 2026-08-22 — by far the most momentum of any project in this space |
| Adds | SSH, Mainsail as an alternative front end, Moonraker JWT auth, USB camera + WebRTC/RTSP with hardware acceleration, timelapse, OpenRFID, Spoolman, Tailscale, a Prometheus exporter on :9101, Home Assistant integration, TMC autotune, adaptive mesh levelling |
| Detection | **No documented version marker.** Practical probes (a `/firmware-config/` route, the Prometheus port, extra Klipper macros) are all config-gated and default-off, so a negative result does **not** prove stock firmware |
| Consequence for Studio | Studio must speak plain Moonraker so it works identically on stock and extended firmware, must never require the custom firmware, and must never *claim* extended firmware is absent — only that it did not detect it |

### Snapmaker U1 Config (JNP-1)

| | |
|---|---|
| Source | <https://github.com/JNP-1/Snapmaker-U1-Config> |
| Licence | **None declared** — all rights reserved. More restrictive than GPL. **Do not copy any value from it** |
| Activity | 27★, dormant since 2026-03-28 |
| Content | A single tuned `printer.cfg`: 25,000 mm/s² acceleration, 800 mm/s tool changes, sensorless homing, input shaper values |
| Risk it illustrates | Overwriting `printer.cfg` is a destructive, un-versioned operation for a novice — exactly the class of action Studio refuses to perform |

### Klipper / Moonraker / Fluidd / Mainsail — the substrate

| | |
|---|---|
| Licences | All **GPL-3.0**. Snapmaker publishes its forks: `Snapmaker/u1-klipper`, `Snapmaker/u1-moonraker`, `Snapmaker/u1-fluidd` |
| What they already own | Live temperature charts, G-code console, file browser, bed-mesh visualisation, macro panels, print history, webcam, timelapse, power control, multi-printer switching |
| Rule this sets for Studio | **Do not rebuild the control panel.** Read-only capability detection and monitoring are complementary; a second dashboard is not |
| Capability oracle | `GET /printer/objects/list` is the honest source of what a machine can do — `exclude_object`, `bed_mesh`, `extruder1..n`, `filament_switch_sensor`, `input_shaper` and every `gcode_macro` |

### OctoPrint

| | |
|---|---|
| Licence | **AGPL-3.0** |
| Architectural difference | A *print host* that owns the serial link, with capability data from a user-entered printer profile. Moonraker is an *API layer* over Klipper, where capability data derives from the parsed `printer.cfg` — i.e. closer to ground truth |
| Relevance | Notable that Snapmaker Orca's own U1 machine profile declares `host_type: "octoprint"` |

---

## 3. Conversion-rule parity with the closest converter

The MakerWorld converter is the nearest functional competitor for the *prepare*
step. Its documented rules were re-implemented independently in Studio's engine
from the published symptoms and the 3MF/profile schemas — no code and no profile
data was copied, which matters because its internals are PolyForm-Noncommercial.

| Documented rule | Studio status | Where |
|---|---|---|
| Enable Exclude Object (keeps adaptive bed mesh + per-object handling) | **Implemented** | `orca_import.py` |
| Suppress the automatic brim Snapmaker Orca would add | **Implemented, and narrower** — only overrides `auto_brim`; a brim the creator explicitly chose is intent and is kept | `orca_import.py` |
| Tree/organic support + variable layer height → hybrid | **Implemented** | `orca_import.py` |
| Filament array validity: empty adaptive volumetric-speed entries, `filament_self_index`, `filament_flush_temp` | **Implemented**; self-index is rebuilt positionally rather than padded from a neighbour | `orca_import.py` |
| Negative `raft_first_layer_expansion` → U1 default | **Implemented**, sourced from Studio's own U1 profile rather than a constant | `orca_import.py` |
| Strip the authoring slicer's `plate_N.gcode` / `.json` so Orca re-slices | **Implemented**; plate *images* are kept | `orca_import.py` |
| Printer/profile identity swap, hardware keys only | **Already present** | `u1_identity.py`, `profile.py` |
| Custom G-code block replacement (Bambu AMS G-code would misbehave on U1) | **Already present** | `profile.py`, `u1_identity.scrub_foreign` |
| Bambu-only key filter + speed/acceleration clamp from the reference profile | **Already present** | `rules.py`, `preserve.py` |
| Filament slot order preserved, slot N stays slot N | **Already present** — Studio never auto-caps colours | `repair.py`, `filaments.py` |
| Per-filament override preservation (max volumetric speed, temps, cooling) | **Already present** via the per-filament key policy | `preserve.py`, `u1_filament_arrays.json` |
| Multi-plate coordinate remap | **Deliberately not implemented.** Studio built it, an independent review reproduced a case where the derived stride was wrong by 79% and a plate landed off the bed, and it was withdrawn rather than patched — the plate spacing is not in the file. Multi-plate projects are still *checked* per plate. | `plate_placement.py` |
| Print-profile matching by layer height | **Not implemented** — Studio uses one U1 base profile. Tracked as remaining work |
| Stock-OrcaSlicer output target toggle | **Not implemented** — deliberately out of scope; Studio targets Snapmaker Orca |

Two things Studio adds on top of the same rule set:

- **It checks its own output.** Every prepared file is validated against the
  source fingerprint, a preservation guard rejects any changed setting the
  pipeline did not explain, and a fidelity report lists what survived — including
  what it could not verify. Reviewing the result in Snapmaker Orca is still the
  right advice, and Studio gives it too; the difference is that Studio also
  arrives with a report.
- **It works on any local file.** No browser, no single site, no DOM coupling.

---

## 4. Where Studio differs (verified 2026-10-04)

Not "what nobody does" — others compare files with printers and audit files. What this
combination offers, and what the 2026-10-04 read of the other projects did not show:

1. **Deterministic, graded evidence on the project itself**: every finding is
   Confirmed / Likely / Informational / Unable to determine, with its evidence.
2. **A fail-closed prepare**: if Studio cannot vouch for the copy, it refuses and says why.
3. **A per-project fidelity audit**: what was preserved exactly, preserved in meaning,
   changed, removed, added or could not be verified.
4. **An original that is never modified**, as a rule enforced by tests.
5. **Local and no-cloud by default, with no AI**; nothing is uploaded.
6. **Before and after the slicer in one product**: the project check and prepare, then
   the sliced job against the printer.
7. Points a beginner at the *right community tool* for the file
   ([OPEN_ECOSYSTEM.md](OPEN_ECOSYSTEM.md)).

---

## 5. Licence wall — the operating rule

| Project | Licence | Studio may |
|---|---|---|
| u1hub, snapmaker-u1-toolkit | MIT | read, reference, reuse with attribution |
| Snapmaker Orca, upstream OrcaSlicer, PrusaSlicer, FOrcaSlicer, ImageMap, OctoPrint | AGPL-3.0 | interoperate over documented interfaces; **never read for code** |
| Klipper, Moonraker, Fluidd, Mainsail, Extended Firmware | GPL-3.0 | speak their documented HTTP/JSON-RPC APIs; **never vendor code** |
| makerworld-to-snapmaker-u1 | MIT shell over PolyForm-Noncommercial-derived internals | learn documented behaviour; **never copy code or profile data** |
| Snapmaker-U1-Config | none declared | **nothing** — no licence means all rights reserved |

Every rule Studio implements from an external project's *behaviour* is written
from the published symptom and the file-format schema, and carries a comment
saying what problem it solves. U1 reference profile values come from Snapmaker
Orca's own bundled defaults, exported directly.
