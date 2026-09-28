# Snapmaker Studio Roadmap

Where Studio is today, and what comes next. Status reflects v1.2.0, the current
release (September 2026). Dates are targets, not commitments. Release-by-release
detail is in [CHANGELOG.md](../CHANGELOG.md); what was verified, and how, is in
[TRUST_STATUS.md](TRUST_STATUS.md).

Every release keeps the core print flow **Input → Diagnose → Transform →
Validate → Output**. **Validate is mandatory and is never removed** from the
product or the branding. Studio does not slice — Snapmaker Orca does — and it
never starts a print on its own. Brand: [`brand/`](brand/README.md). Pillars are
defined in [PRODUCT_VISION.md](PRODUCT_VISION.md) §4.

---

## Shipped — v1.2.0

**Platforms.** A one-click Windows 10/11 installer and a self-contained Linux
`.deb` for Ubuntu 22.04/24.04 x86_64, each with the engine bundled — no Python,
Node or Rust to install. Local-first throughout: no cloud, no account, no
telemetry, nothing uploaded off your local network. The one transfer Studio
makes is a sliced job to your own printer, after you confirm it.

**Reading a project.** Bambu Studio, OrcaSlicer, Snapmaker Orca and PrusaSlicer
`.3mf` projects and plain `.stl` files are read from their real contents:
geometry, objects, parts, plates, filaments, colours and settings. A
PrusaSlicer project's printer, bed, filaments, layer heights, supports and
per-object assignments are read from its own config. Cura and other 3MF
sources are detected and their geometry read; their settings are not
converted.

**Diagnosing it.** Project and Design Doctors (watertight, holes, manifold and
normals, overhangs and supports, tip risk, bed fit), Compatibility, Scale,
First Layer, Multi-Material, Print Quality, and Cost/Pricing/Profit with
editable assumptions. Painted multi-material projects are read before
slicing: which filaments the painting uses, how much surface each covers, and
the height band each occupies, with colours classified as needing a toolhead,
a possible swap, or not classifiable.

**Preparing a copy.** Prepare writes a new Snapmaker U1 copy — the original is
never modified — followed by a fidelity audit: what stayed byte-identical,
what changed and why, what could not be carried over, and what Studio could
not check. Batch Prepare, a Design Library, and Compare (original against
copy).

**Checking against the printer.** Printer-aware preflight compares the project
with the printer Studio can see on your network: toolheads, bed, loaded
filament, whether it is busy, and the fitted nozzle — read live from the
printer, and compared toolhead by toolhead where the data carries that order.
Printer profiles are data; the Snapmaker U1 is hardware-verified and a VORON
2.4 250 profile ships as a second, profile-only target.

**Materials.** Spoolman and Bambuddy as read-only material providers, with
freshness rules for remaining weight. Your own spool notes and a nozzle size
you confirm yourself, both in the desktop app under Settings, each value
labelled by where it came from and the printer's own reading always winning.

**Handing off and reading back.** Open the prepared copy in Snapmaker Orca,
detected on Windows and Linux. After slicing, the G-code is read back and
checked against the printer as it is right now, with cost from the figures the
slicer measured.

**Printer Hub.** Live status, temperatures, toolheads, history and health for a
U1 on your network, plus user-confirmed pause, resume, cancel, upload and
start. Studio never auto-starts a print.

**Ecosystem.** Studio names the community tool that fits the file in front of
you (FOrcaSlicer, OrcaSlicer ImageMap, U1 Print Hub, MakerWorld converters,
Snapmaker Orca), from a data registry anyone can correct by pull request.

**Tools and trust.** The `u1convert` CLI, including `u1convert selfcheck` and
the read-only, redacted `u1convert verify-printer` for community hardware
reports. An opt-in update check, off by default, at most once a day. Published
SHA256 for every installer.

## Near-term

Only work that is genuinely not shipped yet.

- **Signed-in material providers.** A provider that requires a sign-in cannot
  be read today, because Studio has nowhere safe to keep a credential. This
  needs a credential store Studio can rely on across Windows and Linux.
- **Painted colours on the same layer, proven.** Whether two painted colours
  meet on a printed layer is decided by the slice. Studio reserves a toolhead
  rather than claiming either way. Proving it needs reading the sliced job's
  actual extrusion moves; tool-change data alone proved unreliable.
- **Objects whose parts cannot all be carried over.** Today such an object
  crosses whole, with the audit naming what that costs. Carrying more of its
  volumes through preparation.
- **PrusaSlicer preservation.** Carry per-object extruder assignments through
  preparation (reading them ships today), and more of what a U1 copy currently
  names as not carried over.
- **Scaled 3MF export.** Scale Doctor prepares a scaled copy of an STL today;
  a 3MF project is blocked with a clear message.
- **Broader real-hardware verification.** One Snapmaker U1 on one firmware
  version has been verified. More machines and firmware versions, a genuinely
  mixed-nozzle setup, and the full provider-backed hardware check run again,
  including from Linux.
- **External Linux reports.** Linux has not yet had a report from a user
  outside the project.
- **Code signing.** Neither installer is signed yet. The Windows path is
  described in [CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md); Linux package
  signing is not started.

## Longer term

- **OBJ and GLB input.**
- **More printer targets beyond the U1**, each hardware-verified before it is
  called supported.
- **A stable API for third-party integration**, with a public contract for
  ecosystem adapters, printer profiles and validators.
- **More ecosystems prepared, not just read** — Cura projects (detected today,
  settings not converted) and Creality Print projects (read today as a generic
  3MF), with the same "what carried over, what didn't" reporting.
- **Rendered 3D plate preview** — Plate Color Remap shows a 2D plate map today.
- **Multi-printer management** — several printers through one Studio, still
  local and user-confirmed.
- **Deeper print intelligence** — more evidence signals in Print Quality, and
  toolpath analysis before printing.

Out of scope, permanently: embedded slicing, cloud accounts, and any
autonomous printer control.

## Cross-cutting (every release)

- **Reliability:** keep the regression tests against genuine OrcaSlicer,
  BambuStudio and PrusaSlicer projects current; wiring the full real-file
  corpus run into CI is still to do.
- **Trust:** every claim is computed, not asserted; unknown stays unknown;
  what was verified, and how, is published per release.
- **Polish:** the novice experience stays first-class as power features grow.
