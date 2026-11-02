# Third-party notices

Snapmaker Studio is MIT licensed and contains no third-party source code beyond
its declared package dependencies. This file records the other things a project
can owe: **facts learned from other people's documentation**, and the boundary
Studio keeps around licences it cannot mix with.

`docs/innovation-fund/COMPETITOR_MATRIX.md` states the rule Studio operates
under. This file is Studio holding itself to it.

---

## Knowledge credited

### U1 Print Hub — <https://github.com/dlgambill/u1hub> · MIT

Its README documents that the Snapmaker U1 answers Moonraker on **port 80**
through the printer's own nginx, as well as on Klipper's standard 7125. Studio's
printer discovery probes both because of that (`snapstudio_core/moonraker.py`),
which fixed a real class of "printer not found" where a reachable machine looked
offline.

That is a fact about a printer rather than any of the Hub's code — no code or
data from it is used — but it was learned there and is credited here.

### Snapmaker — Klipper, Moonraker and Fluidd forks

<https://github.com/Snapmaker/u1-klipper> · <https://github.com/Snapmaker/u1-moonraker> ·
<https://github.com/Snapmaker/u1-fluidd> (GPL-3.0)

Studio speaks the documented Moonraker HTTP API over the network. It vendors no
code from these projects and does not link against them.

### 3MF Consortium — the 3MF specification

<https://github.com/3MFConsortium/spec_core> (specification text)

Studio's container reader is an independent implementation of the published OPC
package layout. The de-facto layouts that PrusaSlicer and the
BambuStudio/OrcaSlicer family write are read from publicly observable file
structure, not from their source.

---

## Formats and APIs read for the development features (after v1.7.0)

This section records research on formats, APIs and shapes, and says what that
research did and did not put in this repository. For the projects below, Studio
redistributes no source code and no captured project files; what exists in the
repository because of the reading is stated per entry. This section does not
describe the older Orca-derived data and slicer-written test files, which are
listed separately under "Orca-derived data and slicer-written fixtures already in
the repository". Licence identifiers are as reported by the GitHub repository API
on 2026-11-02 unless stated; they are recorded, not interpreted, and Studio makes
no legal conclusion from them. Studio is not affiliated with or endorsed by any of
these projects, and claims no contribution back to them.

### Creative-tool project formats (format only)

Read on 2026-11-01 to learn the shape of the 3MF each tool writes (member names,
XML element and attribute names, JSON keys). Pinned record, with the exact paths:
`backend/tests/fixtures/creative/PROVENANCE.md`; supported-format table:
`docs/internal/CREATIVE_COMPAT.md`.

| Tool | Source | Licence | Commit read | Path read |
|---|---|---|---|---|
| DitherForge | <https://github.com/rtwfroody/ditherforge> | MIT | `4d3552a434e8084d9b5fe573959a3493325be29f` | `internal/export3mf/export3mf.go`, `internal/export3mf/bambu.go` |
| Kromacut | <https://github.com/vycdev/Kromacut> | AGPL-3.0 | `94874755426ee7f33b3684a5544e7fab0e2e73f7` | `src/lib/export3mf.ts` |
| SindriCAD | <https://github.com/MakerViking/sindricad> | AGPL-3.0 | `8b2e9dc4f82fba58b39c206c993534c487cc1eab` | `sidecar/project3mf.py` |

What exists in this repository because of that reading: Studio's own readers, and
test archives generated at test time by Studio's own helper
(`backend/tests/fixtures/creative/zip_factory.py`). Those archives are synthetic
and are not captures of any tool's real output. The readers are fixture-tested
only. Other creative-compat research references (FOrcaSlicer, LixNix, FullSpectrum,
OrcaSlicer ImageMap) are listed with their evidence in `docs/internal/CREATIVE_COMPAT.md`.

### Lumina Layers (published API shapes only)

<https://github.com/lumina-layer-studio/Lumina-Layers> — GitHub reports
AGPL-3.0 (2026-11-02). An earlier Studio research note
(`docs/innovation-fund/PHASE1_POSITION.md`, a table measured 2026-08-23) recorded
"GPL-3.0"; the two differ and neither is a conclusion drawn here.

Studio's Lumina client sends requests to a service **you configure and run
yourself**, using the request and response shapes of the published Lumina Layers
API as recorded in a 2026-10-25 research bundle (read from the router source at
that time; the router is listed upstream today as `converter`). No Lumina code or
assets are redistributed. The test stand-in
(`backend/tests/mocks/lumina_server.py`) and its fixtures are hand-written from
those shapes; they are not captured from a Lumina service. The client is
mock-service-tested only: no real Lumina installation has been exercised.

### Accessory and host adapters (shapes in hand-written fixtures)

Fixtures are hand-written to published shapes and carry blob references in their
own `PROVENANCE.md` files under `backend/tests/fixtures/adapters/`. No device was
contacted and no code was copied.

| Project | Source | Licence (GitHub) |
|---|---|---|
| AFC-Klipper-Add-On | <https://github.com/AFCProject/AFC-Klipper-Add-On> | GPL-3.0 |
| BMCU-Klipper | <https://github.com/jarczakpawel/BMCU-Klipper> | GPL-3.0 |
| multiACE | <https://github.com/decay71/multiACE> | GPL-3.0 |
| Sidecar-Beta | <https://github.com/dcan999/Sidecar-Beta> | GitHub reports `NOASSERTION` (licence not identified); Studio copies nothing from it |
| Snapmaker u1-klipper (stock Moonraker shape) | <https://github.com/Snapmaker/u1-klipper> | GPL-3.0 |
| Snapmaker u1-moonraker (OctoPrint-compat shape) | <https://github.com/Snapmaker/u1-moonraker> | GPL-3.0 |
| SnapmakerU1-Extended-Firmware (SpoolLink shape) | <https://github.com/paxx12-snapmaker-u1/SnapmakerU1-Extended-Firmware> | GPL-3.0 |
| OctoPrint (documented version reply) | <https://github.com/OctoPrint/OctoPrint> | AGPL-3.0 |

### Snapmaker Orca source (setting facts only)

<https://github.com/Snapmaker/OrcaSlicer> (AGPL-3.0), read at commit
`b1831e5dcb464172de33783142425aafda834fbc`. What is redistributed is **facts and
names, not source**: `backend/snapstudio_core/data/u1_setting_scopes.json` (which
project settings are per-filament and which per-extruder, with prose evidence that
cites Orca file names) and `backend/snapstudio_core/orca_nonnullable.py` (a
generated list of option names plus a digest of that list, produced by
`tools/derive-orca-nonnullable.py`). No Orca source text, resources or profile
data is copied by these two files.

### Orca-derived data and slicer-written fixtures already in the repository

These existed before the work above and are documented in their own files; they
are listed here so this notice is read together with them. Studio makes no licence
determination about them here.

- `backend/snapstudio_core/data/templates/u1_base_project_settings.json`: project
  settings captured from a real Snapmaker Orca project
  (`backend/snapstudio_core/data/templates/PROVENANCE.md`).
- `backend/snapstudio_core/data/profiles/snapmaker_u1.json`: U1 reference profile
  values exported from Snapmaker Orca's own reference project (see "U1 reference
  profile values" below).
- Test fixtures written by slicers, described in
  `backend/tests/fixtures/painted/PROVENANCE.md` (for example a Snapmaker Orca
  2.3.5-authored and a Bambu Studio 02.08.02.61-authored project, and
  PrusaSlicer 2.9.6 and OrcaSlicer 2.4.2 round-trips of Studio's own 20 mm cube) and
  `backend/tests/fixtures/orca-object-overrides/`.

---

## Boundary kept

These projects were studied as **behaviour** — the published symptom a rule
addresses, and the file-format schema it operates on. No source code from any of
them is present in this repository. The data files derived from them are the
Orca-derived data and slicer-written fixtures listed above and the factual
printer-profile data described under "Printer profile facts" below.

| Project | Licence | Why Studio must not copy from it |
|---|---|---|
| Snapmaker Orca, upstream OrcaSlicer, PrusaSlicer, FOrcaSlicer, OrcaSlicer ImageMap, OctoPrint | AGPL-3.0 | Incompatible with MIT distribution |
| Klipper, Moonraker, Fluidd, Mainsail, SnapmakerU1 Extended Firmware | GPL-3.0 | Incompatible with MIT distribution |
| makerworld-to-snapmaker-u1 | MIT shell over PolyForm-Noncommercial-derived internals | The non-commercial terms travel with the derived parts |
| Snapmaker-U1-Config | none declared | No licence means all rights reserved |

Every Snapmaker Orca import rule in `snapstudio_core/orca_import.py` carries a
comment naming the problem it solves, so the reasoning can be audited against the
published symptom rather than taken on trust.

U1 reference profile values in `snapstudio_core/data/` are derived from Snapmaker
Orca's own bundled defaults, exported directly.

### Printer profile facts

`snapstudio_core/data/printer_profiles/` records facts about machines: build
volume, tool count, what a printer reports about its own materials. Each profile
names where every fact came from in its own `source_refs`.

`voron_2_4_250.json` is derived from `config/kit-voron2-250mm.cfg` in
[Klipper](https://github.com/Klipper3d/klipper) (GPL-3.0), read at blob
`e82ee28a152ed61599e0422c1c353d13e0c3453e` on 2026-08-25. What was taken is
factual: the axis limits its steppers declare, the single `[extruder]` it
declares, and which optional modules it does and does not declare. **No
configuration text was copied into this repository**, and the profile is data
about a machine rather than a derivative of Klipper's work.

The same holds for the test fixture built from it,
`backend/tests/fixtures/printers/voron_2_4_250_moonraker.json`, whose own
`_provenance` block states the derivation of every field and states plainly that
it is not evidence from hardware. VORON Design's machines and documentation are
credited in that profile's `source_refs`; Studio is not affiliated with, or
endorsed by, VORON Design.

---

## Corrections

If you maintain a project named here and something is wrong — the attribution,
the description, or the fact that you are listed at all — open an issue or a pull
request. Registry descriptions live in
`backend/snapstudio_core/data/ecosystem.json` and are a one-object change.
