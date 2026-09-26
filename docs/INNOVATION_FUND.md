# Snapmaker Studio — Innovation Fund submission

> ## Status: **Submitted · Phase 1 · publicly listed**
>
> Snapmaker Studio was submitted to Phase 1 on **24 June 2026** and confirmed by
> the Innovation Fund team on **29 June 2026**. It is publicly listed among the
> **41 projects in the running** on <https://www.snapmaker.com/innovation-fund>
> as *"snapmaker-studio — by Kunal Khurana"*.
>
> **There is nothing left to submit.** Do not submit again; a second entry would
> be a duplicate. Evaluation closes **22 September 2026** and winners — 20 of the
> 41 — are announced **30 September 2026**.
>
> Independent open-source project — not affiliated with or endorsed by Snapmaker.

## What was actually submitted, and how it has aged

The entry was written against **beta.16-era** Studio. It describes understand →
validate → prepare → monitor, Source Check, Project Doctor, and the hardware-
verified Printer Hub control loop. All of that is still true.

What it does not mention, because none of it existed in June, is everything the
project is now strongest on: the project-to-printer preflight, the fidelity audit,
the reversible fix ledger, colour classification beyond four toolheads, the
ecosystem recommender, the installed-build acceptance harness, and the read-only
verification against a real U1 that shipped in beta.24.

Snapmaker's public wall entry condenses the original to *"Free local pre-print
checker for U1. Flags model defects and risky settings up front, before you waste
filament."* That is accurate about June and understates August.

The submitted text is preserved verbatim in
[innovation-fund/SUBMITTED_ENTRY.md](innovation-fund/SUBMITTED_ENTRY.md). The
sections below are the **current** description of the project — what an updated
entry would say, and what any judge reading the repository should be reading.

## The fund, as published today

Re-read from the official page on **2026-08-23**. Source:
<https://www.snapmaker.com/innovation-fund>.

| | |
|---|---|
| Phase 1 | 9 Jun – **7 Sep 2026**; winners announced 30 Sep 2026 |
| Phase 2 | 1 Oct – 31 Dec 2026; results 22 Jan 2027 |
| Scoring | **80%** tech committee (Snapmaker product and engineering staff, invited industry experts, long-standing community members) + **20%** community vote |
| Community vote | GitHub repository stars, community-channel likes, project-page upvotes |
| Committee criteria | Innovation & Technical Depth · Openness & Quality · Practicality & Adaptability |
| Awards per phase | 3 × $5,000 · 7 × $3,000 · 10 × $1,500, plus badge, certificate, social feature and beta access to upcoming products |
| Eligibility | Build something on or around the U1 — slicer plugin, hardware mod, workflow, accessory. Pre-existing and mature projects are explicitly welcome. Open source is preferred; closed source can qualify if it gives back another way. |
| Requirements | Published on GitHub or another public page · shared in a Snapmaker community channel · submitted through the fund's online form |
| Form fields | name, email, project name, GitHub/project URL, category, short description. Optional cover image: 640×360, PNG/JPG, max 5 MB |
| Word limits | None published. The short description below is kept near 40 words so it fits whatever the field allows. |
| Updating a submission | No self-service editing exists. The page says a browsing-and-voting system is still being built. The confirmation email invites questions at community@snapmaker.com, which is the only documented route to correct a listing. |
| Evaluation | Ends **22 September 2026**; 20 winners announced 30 September 2026 |

## Project

**Name:** Snapmaker Studio
**URL:** <https://github.com/DVOpenLabs/snapmaker-studio>
**Licence:** MIT
**Category:** Workflow / software tooling
**Cover image:** `docs/brand/hero.svg` (export at 640×360)

## Positioning

**Snapmaker Studio — The Intelligence Layer for Open 3D Printing.**

## Short description (~40 words)

Snapmaker Studio is a free, local-first desktop app that reads a downloaded 3D
project, explains the risks in plain language, compares it against your actual U1
over Moonraker, fixes only what it can justify, and proves what survived.
Snapmaker Orca still slices.

## Long description

A beginner downloads a project. It was made somewhere else, for another printer,
uses six colours on a four-toolhead machine, and one object hangs off the plate.
Their slicer says `out of bounds` and stops.

Snapmaker Studio sits on **both sides of Snapmaker Orca**. It reads the project's
real contents — not its filename — and says which object, which edge, how many
millimetres, and why. It asks the printer on the network what it can actually do,
using the open Klipper/Moonraker stack Snapmaker ships on the U1, and compares the
two: materials against toolheads, materials against what is *loaded*, objects
against the real bed, the features a prepared copy relies on against the
firmware's own object list. It fixes only what it can justify, writing a new copy
and never touching the original. Then it accounts for the result element by
element — what stayed byte-for-byte identical, what changed and why, what could
not be carried over, and, kept separate on purpose, what it could not check at
all. Finally it names the community tool that should handle the next step, because
a beginner should not have to know the whole ecosystem before they can use any of
it.

Then Orca slices — and the file comes back. Studio reads the G-code itself and
reports what the printer will *actually execute*: which machine it was sliced for,
which tools it prints from, how much filament per slot, how long it will take. It
joins that to the printer as it is right now — the tools the job needs against the
slots that have spools in them, its materials against what is loaded, its bed
against the real bed — and costs the job from the grams and minutes the slicer
measured rather than from an estimate. The failures that live on that side are the
expensive ones: the job prints from slot 3 and slot 3 is empty; it was sliced for
PETG and PLA is loaded; it was sliced for another machine entirely. None of them
are visible in the project file, and none are visible on the printer alone.

Studio does not slice, and will not. Snapmaker Orca slices. Studio is the layer
that makes the file, the printer and the person agree — before that happens, and
again afterwards.

The hard part is not the fixing. It is being correct when the file or the printer
does not expose enough information to be certain — and saying so, instead of
guessing in the direction that looks better.

## Innovation & technical depth

- **Evidence-graded forensics.** Every fact Studio states carries the part of the
  file that proved it and one of four confidence levels: confirmed, likely,
  informational, unknown. An unmeasured trait is null at `unknown` — never false.
  "Not detected" is never rendered as "not supported", and that wording is
  asserted by tests over every unknown the modules can produce.
- **Joining a project to a machine.** The preflight is the join: the project's
  materials, nozzle expectation, geometry and required capabilities against the
  printer's toolhead count, loaded filament, real bed and Klipper object list.
- **A preservation invariant.** Originals are never modified. Preparing always
  writes a new copy, and a test asserts the input is byte-identical afterwards —
  including in the acceptance harness that runs against the shipped installer.
- **A fidelity audit that can fail.** Studio may only say "nothing was lost" when
  the audit grants that claim for *that project*. Most of its tests build a
  deliberately wrong copy and assert Studio reports it as unverified.
- **Deterministic classification beyond four colours.** Six colours on four
  toolheads is two problems, not one: colours that share a layer each need a
  toolhead, colours introduced higher up may be planned swaps. Painted colour is
  decoded from the project's own facet data — which filaments, how much area,
  what heights — and a painted colour is called swappable only where the geometry
  proves it never shares a height with another. Whether two overlapping colours
  land on the same printed layer is left to the slicer, and said so.
- **Refusal under uncertainty.** Multi-plate repositioning was implemented,
  reviewed, and **withdrawn**: plate spacing is not recorded in a project file, a
  reproduced case placed a plate off the bed while reporting success, and the
  honest fix was to remove the feature rather than tune a number Studio cannot
  observe. Per-plate fit checking, which is position-independent, stayed.
- **Hostile-archive bounds.** A 3MF is an untrusted ZIP. Studio meters the
  decompressed stream rather than trusting the header, with configurable caps on
  total bytes, per-part bytes and part count. The same bounding applies to printer
  responses.
- **Real firmware interrogation.** The Klipper object list is used as a capability
  oracle; the U1 answers on port 7125 and on 80, and both are tried. Loaded
  filament is read the way the firmware actually publishes it — parallel arrays
  with a per-slot presence flag — a shape found only by asking a real machine.
- **A reversible fix ledger.** Every produced file records what was done, what
  triggered it, each change with its old value and reason, and whether the result
  validated. The way back is explicit, and the exportable form carries no local
  paths.
- **Local-first by architecture.** A Python engine on loopback behind a token
  handshake, a Tauri shell, and no network egress in the pipeline at all.

## Openness & quality

- **MIT**, with every interoperating project listed by licence in
  [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). AGPL and GPL neighbours are
  interoperated with, never vendored.
- **No account, no cloud, no telemetry, nothing uploaded off the local network.**
- **A documented CLI** (`u1convert`) and a **documented local HTTP API**, so the
  engine is usable without the app.
- **An ecosystem registry that is data, not code.** Adding a tool is a small pull
  request against a JSON file; the rules that fire it are declarative, and a test
  proves every entry is reachable. See [EXTENDING.md](EXTENDING.md).
- **One command anyone can run.** `u1convert selfcheck` runs the real pipeline end
  to end and prints a 27-check pass/fail table, so the claims can be verified
  without reading the source. It runs in CI on every pull request.
- **An acceptance harness that drives the installed application**, not a dev
  server: 39 checks over the real window and the frozen engine, including that the
  input file is byte-identical afterwards and that uninstalling leaves nothing
  behind.
- **Regression tests against genuine slicer output** — real OrcaSlicer,
  BambuStudio and PrusaSlicer project files, fetched rather than vendored because
  they are AGPL and one embeds an upstream developer's username.
- **Reproducible.** Clone, then `pytest`, `npm run test`, `u1convert selfcheck`,
  and `tools/acceptance/run.ps1` against a built installer. The walkthrough is
  [innovation-fund/JUDGE_WALKTHROUGH.md](innovation-fund/JUDGE_WALKTHROUGH.md).

## Practicality & adaptability

Situations a novice actually hits, and what Studio does:

| Situation | What Studio does |
|---|---|
| A project made in another slicer for another printer | Reads it, states the source, prepares a U1 copy for review in Orca |
| An object hangs off the plate | Names the object, the edge and the millimetres, and offers to move it in a copy |
| Six colours, four toolheads | Separates colours that need a toolhead from colours that can be swaps, and says which it cannot classify |
| The fitted nozzle is unknown | Says "check this yourself", explains the consequence, and never calls it unsupported |
| The printer is busy, or missing materials | Compares against what the machine reports right now, including which spools are loaded |
| Something could not be carried over | Lists it, with the reason, separately from what merely changed |
| The file needs a tool the beginner has never heard of | Names it, says why, and links it |

**Why the U1 specifically.** Snapmaker publishes the U1's firmware and ships the
standard Klipper/Moonraker stack, so a local application can ask the machine what
it can do instead of inferring it from a model name. That is what makes a
project-to-printer comparison possible at all, locally and without a cloud
account. Studio is a direct beneficiary of Snapmaker's openness, and the
comparison it performs is not possible on a closed printer.

**Adaptability.** The printer layer speaks Moonraker, not a U1-specific protocol.
The tool registry is data. The trait extractor reads 3MF dialects from three
different slicer families. None of that is U1-only by construction — the U1 is
simply the machine it is verified against.

## Evidence

Everything below was verified against the **published v1.0.0 installer**, not a
development build. Commands, counts and full reports:
[TRUST_STATUS.md](TRUST_STATUS.md).

| What | Result |
|---|---|
| Installed-application acceptance, through the real UI | 39/39 |
| Read-only verification against a real Snapmaker U1 | 39/39 |
| Regression tests against genuine Orca/Bambu/Prusa projects | 36 tests |
| End-to-end pipeline self-check | 27/27 |
| Backend tests | 1833 passed, 7 skipped |
| Desktop tests | 340 passed |
| TypeScript, Rust, production build | clean |

Demo: [`docs/media/snapmaker-studio-demo.mp4`](media/snapmaker-studio-demo.mp4) —
66 seconds, every frame the installed application.

Studio is advisory. It does not slice, does not promise a successful print, and
never controls a printer on its own.

## Community evidence

Measured, not asserted — see
[innovation-fund/USER_EVIDENCE.md](innovation-fund/USER_EVIDENCE.md) for the
figures and the date they were taken. Interest (downloads, clones, visitors,
stars) is reported separately from proven user outcomes, and where the second is
still zero, it says so.

## What funding would be used for

- **Code signing.** The largest barrier to novice adoption is SmartScreen's
  unknown-publisher warning. EV certificates no longer bypass it, so the plan is
  reputation over time through [SignPath Foundation](CODE_SIGNING_POLICY.md),
  which signs qualifying open-source projects at no cost. Funding is not the
  blocker here, and saying so is better than inflating the ask.
- **macOS builds.** Linux shipped in v1.0.0, with its own CI release pipeline.
- **Broadening the verified hardware surface** — more real printers, more firmware
  versions, and more genuine slicer projects in the regression corpus.
- **Maintainer time** for review, releases and community contributions.

## Notes

- **Entry is complete.** Submitted, confirmed, and publicly listed. The remaining
  work is competitive, not procedural.
- The community-vote component is 20% and includes GitHub stars, but the fund's
  own page says the voting system is still being built, so there is nothing to
  vote on yet.
- The listed description is a June snapshot. See
  [innovation-fund/LISTING_UPDATE.md](innovation-fund/LISTING_UPDATE.md) for what
  was done about that.
