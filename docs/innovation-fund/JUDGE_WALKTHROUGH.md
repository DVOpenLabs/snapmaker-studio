# Judge walkthrough — 3 to 5 minutes

Everything below runs against the real product. There is no demo mode and no
scripted output: the numbers in this document were produced by the commands in it.

Sample project: **`examples/demo_offplate_foreign.3mf`** — a small project authored
for a 350 mm-bed printer, shipped in this repository so every step is reproducible.

---

## The 30-second version

Other projects in this field **do something to a file or a machine**: slice it,
convert it, send it, edit it. Snapmaker Studio **explains one** — what a project
is, what will go wrong on a U1, what it costs, and which of the community's tools
is the right next step.

It reads real geometry, grades its own certainty, never modifies your original,
and refuses to guess.

---

## Path A — the desktop app (about 3 minutes)

1. **Open Studio** and choose **Compatibility**.
2. **Open `examples/demo_offplate_foreign.3mf`.**
3. **Read the settings findings.** Studio names the profile problems and, for each
   one, what it is, why it matters, and what to do — not a code and a shrug.
4. **Read the Object placement card.** This is the part no other tool does:

   > 1 object is outside the U1's printable area.
   > Object 2 · 10 × 10 × 10 mm — Hangs 55.0 mm past the right edge.

   The object is far smaller than the U1's bed. Every size check in every tool
   passes. It is in the wrong *place*, because the project carries another
   printer's coordinates — and Snapmaker Orca's only word for this is
   `out of bounds`.
5. **Press "Move onto the plate (saves a copy)".** Studio writes a new file, says
   plainly that your original was not changed, and states what it preserved:
   layout, rotation, scale and height.
6. **Prepare a U1 copy** and look at the change list. Every changed setting shows
   its old value and the reason it changed. A preservation guard in the engine
   rejects any change the pipeline cannot explain.
7. **Look at "Best tool for this project"** under the Orca handoff. Studio names
   the right next tool for *this file*, with the reason it read from the file, the
   tool's licence, and a caution if the tool is an experimental community fork.

---

## Path B — the engine, no GUI (about 90 seconds)

Everything the app does is reachable from a CLI and a local JSON API. Run from
`backend/`:

```bash
# 1. What is this file, and how sure is Studio?
u1convert traits ../examples/demo_offplate_foreign.3mf
```

Every fact carries evidence and a confidence tier:

```json
"target_printer": { "value": "Bambu Lab H2D", "confidence": "confirmed",
                    "evidence": "Metadata/project_settings.config printer_model" },
"likely_makerworld": { "value": false, "confidence": "informational" }
```

```bash
# 2. Where do the objects actually sit?
u1convert placement ../examples/demo_offplate_foreign.3mf
```

```
1 object(s) fall outside the U1's plate, but the whole arrangement fits —
moving it as one piece brings everything back on, keeping the creator's
layout, rotation and scale.
```

```bash
# 3. Fix it. The original is never touched.
u1convert placement ../examples/demo_offplate_foreign.3mf --fix
```

```json
{ "ok": true, "objects_moved": 1, "offset_mm": { "x": -179.5, "y": -49.0 },
  "after": { "off_plate": [] },
  "summary": "1 object(s) moved onto the U1 plate in a new copy — demo_offplate_foreign_placed_U1.3mf. Your original file was not changed." }
```

Note `after` — Studio re-ran the same check against the file it actually wrote,
not against what it intended to write.

```bash
# 4. Which tool should this file go to, and why?
u1convert ecosystem ../examples/demo_offplate_foreign.3mf
```

```
Snapmaker Orca: This project was authored for another printer. Prepare a U1 copy
in Studio first — then Snapmaker Orca opens that copy with U1 settings.
```

```bash
# 5. What will it cost?
u1convert cost ../examples/demo_offplate_foreign.3mf
```

Because this project has not been sliced, Studio does **not** produce a number:

```json
{ "available": false, "basis": "not available",
  "reason": "This project has not been sliced yet, so no real material figure
             exists in the file. Slice it in Snapmaker Orca and open the saved
             project again, or enter your own estimate." }
```

That refusal is the feature. On a sliced project the same command reports the
time, weight and per-material cost the author's own slicer computed, and says so.

---

## What to look for while reviewing

**Does it claim more than it knows?** Ask for a fact it cannot have. Open a bare
STL and check `unit` — Studio reports `unknown`, because STL files do not record
their unit. Ask for cost on an unsliced project — it explains instead of guessing.

**Does it destroy anything?** Every fix writes a new file.
`test_fix_never_modifies_the_original` and `test_fix_only_touches_the_model_part`
(a byte-diff of the whole archive) are in `backend/tests/test_plate_placement.py`.

**Does it refuse when it should?** Give it a multi-plate project with an unevenly
spaced grid, or one where a plate will not fit. It moves every plate or none, and
says which.

**Does it survive a hostile file?** `backend/tests/test_container_limits.py`
builds real decompression bombs and asserts the reader refuses them.

---

## Run the tests

```bash
cd backend  && pytest          # 2802 passed, 13 skipped
cd backend  && u1convert selfcheck   # 27/27 over production code paths
cd desktop  && npm run test    # 725 passed
cd desktop  && npm run build   # tsc + vite
```

The tests worth reading are the ones that assert what Studio *will not* say:

- `test_ecosystem.py::test_unmeasured_traits_never_fire_a_rule`
- `test_project_cost.py::test_unsliced_project_gets_an_explanation_not_a_number`
- `test_orca_import.py::test_a_brim_the_creator_chose_is_left_alone`
- `test_plate_placement.py::test_an_object_on_no_plate_stops_the_whole_fix`
- `test_project_traits.py::test_generic_3mf_claims_nothing_it_cannot_see`

---

## Verifying the shipped installer, not the source tree

Everything above runs from a clone. Two harnesses go further and check the build a
user would actually download: they install a rewrapped copy of that build (the same application payload with an isolated
identity), not the production installer itself.

**The installed application.** Build the installer with `npm run release:windows`
in `desktop/`. The maintainer then runs `tools/acceptance/run.ps1`. It refuses to
run without a rewrapped acceptance-identity installer and its attestation (see
[../internal/HARNESS_ISOLATION.md](../internal/HARNESS_ISOLATION.md)), and it never
modifies the production installation; a tripwire fails the run if production state
changes.

It installs the rewrapped build into an isolated directory with its own WebView2
profile and engine data directory, drives the real application window over the
Chrome DevTools Protocol, and uninstalls. Its checks include that the input file
is byte-identical afterwards and that uninstalling leaves nothing behind. It stops
only processes it started. For the v1.3.0 release candidate, this harness scored **45/45** —
[../internal/acceptance-1.3.1.json](../internal/acceptance-1.3.1.json).

**A real printer.** With a Snapmaker U1 on the same network, the maintainer runs
`tools/hardware/verify.ps1 -PrinterHost <printer-ip>`. Like the acceptance harness,
it refuses to run without a rewrapped acceptance-identity installer and its
attestation (see [../internal/HARNESS_ISOLATION.md](../internal/HARNESS_ISOLATION.md))
and never modifies the production installation; a tripwire fails the run if production state changes.

Read-only by construction: the allowed routes are asserted against a deny-list
before the first request, so nothing is started, uploaded or queued and no
temperature, motion, homing, pause, resume, cancel, emergency-stop or configuration
call is made. The printer's address is replaced with a placeholder before anything
reaches the evidence file. This release's real-U1 check ran through the
Windows-installed application itself — last result: **58/58** —
[../internal/hardware-1.3.1.json](../internal/hardware-1.3.1.json).

That run is worth reading rather than just counting. It proved the four
toolheads' fitted nozzles are read live and shown as the printer's own reading,
that an offline-saved conflicting nozzle note is shown as a conflict once
the printer answers again with the printer's value used, and that a real
"Remove my note" action restores the live row — with zero printer-control
routes called throughout, confirmed by the harness's request listener, which
records every call. Not run this release: the Spoolman/Bambuddy-seeded
provider-on-hardware checks; this printer's four toolheads all carry the same
0.4 mm nozzle, so a genuinely mixed-nozzle setup was exercised only in
automated tests; and the Linux-installed app was not run against the real
printer. No SpoolEase check was run against hardware either (its real-device
validation is pending). When no reading is available, Studio still says "check
this yourself" rather than guessing.

---

## Further reading

- [DIFFERENTIATION_STRATEGY.md](DIFFERENTIATION_STRATEGY.md) — why this needs to exist
- [COMPETITOR_MATRIX.md](COMPETITOR_MATRIX.md) — the evidence behind that answer
- [TECHNICAL_DEPTH.md](TECHNICAL_DEPTH.md) — the hard problems and how they are solved
- [OPEN_ECOSYSTEM.md](OPEN_ECOSYSTEM.md) — how Studio connects the rest of the ecosystem
- [../EXTENDING.md](../EXTENDING.md) — the extension seams, for contributors
- [NEXT_MOVES.md](NEXT_MOVES.md) — what is planned next, and what is deliberately not
