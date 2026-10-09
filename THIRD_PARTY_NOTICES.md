# Third-party notices

Snapmaker Studio is MIT licensed and contains no third-party source code beyond
its declared package dependencies and the vendored 3D viewport recorded under
"Code included in the app" below. This file records the other things a project
can owe: **facts learned from other people's documentation**, and the boundary
Studio keeps around licences it cannot mix with.

`docs/innovation-fund/COMPETITOR_MATRIX.md` states the rule Studio operates
under. This file is Studio holding itself to it.

---

## Code included in the app

### three.js · MIT

`three` 0.186.1, pinned exactly, is a declared dependency of the desktop app and is
bundled into the lazily loaded 3D project view (`desktop/package.json`). Its types come
from `@types/three` 0.186.0 (MIT, development only, not shipped).

> The MIT License
>
> Copyright © 2010-2026 three.js authors
>
> Permission is hereby granted, free of charge, to any person obtaining a copy of this
> software and associated documentation files (the "Software"), to deal in the Software
> without restriction, including without limitation the rights to use, copy, modify, merge,
> publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
> to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or
> substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
> INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
> PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
> FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
> OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
> DEALINGS IN THE SOFTWARE.

### SlicerX viewport · Apache-2.0

**Made possible by SlicerX** — <https://slicerx.app/support>

The read-only 3D project view draws with the framework-free viewport from
<https://github.com/slicerx-oss/slicerx> (`packages/ui/viewport`, Copyright (C) 2026 The
SlicerX contributors), vendored at commit `edb521fe41306dd60d01bda8a0f6bf8aa54fcb29` under
`desktop/src/vendor/slicerx/`, together with the SXPV and plate type definitions it imports
from `packages/contracts`. Both are Apache-2.0; the licence text and SlicerX's own NOTICE are
kept beside the source (`LICENSE-APACHE`, `NOTICE`). Studio's local changes are listed in
`desktop/src/vendor/slicerx/UPDATING.md`.

What this does and does not include: only the viewport and the contract types are vendored.
SlicerX's slicing engine, profiles, printer pictures and other AGPL-licensed data are **not**
part of Studio. The vendored viewport still contains SlicerX's editing code (move, rotate,
scale, paint, cut, sketch) because its entry class imports it; Studio never calls it. The 3D
view is read-only and reaches the viewport only through
`desktop/src/components/project-scene/readOnlyViewport.ts`. "SlicerX" and its logo are
trademarks of the SlicerX project; Studio is not affiliated with or endorsed by SlicerX.

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

## Boundary kept

These projects were studied as **behaviour** — the published symptom a rule
addresses, and the file-format schema it operates on. No source code, resources
or profile data from any of them is present in this repository.

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
