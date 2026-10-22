# Snapmaker Studio — Product Vision

> **Shipping today:** the workflow platform for modern 3D printing.
> **North-star vision:** the operating system for multi-material 3D printing.
>
> Independent open-source project — not affiliated with or endorsed by Snapmaker.

Snapmaker Studio is not a converter. Conversion is the first useful thing it
does — the wedge — not the product. The product is a single, local-first
desktop platform that owns the *workflow* between a 3D model and a reliable,
multi-material print. Today that targets the Snapmaker U1; the long-term aim is
to span more slicers and more printers over time (not a claim of current support).

**The workflow — the spine of the product and the brand:**
**Understand → Validate → Prepare → Monitor.**
Validate is a mandatory stage, never skipped: every prepared file is *proven clean*
before output. (Brand: see [`brand/`](brand/README.md). Tagline: _Understand any
design, see what Studio could check, get a copy ready for Orca._)

---

## 1. Mission

**Give makers one place to take any model, from any ecosystem, to a reliable
multi-material print — without losing their work to format wars, vendor lock-in,
or silent compatibility failures.**

(Full mission statement: see the Mission section below.)

## 2. Vision

In three years, when a maker downloads a model, inherits a project, or switches
printers, the answer to "what can I check here, and how do I get a copy ready for Orca?" is a
single app: **Snapmaker Studio.** It diagnoses, repairs, converts, optimizes,
validates, and manages — locally, openly, and across ecosystems — the way an IDE
became the home for code regardless of language or compiler.

Multi-material is the forcing function. Single-color printing is largely solved;
multi-material/multi-tool is where compatibility breaks, presets diverge, purge
math goes wrong, and files silently fail to load. That is exactly the seam
Snapmaker Studio operates in, and it widens as the ecosystem fragments.

## 3. Core Principles

1. **Local-first.** No account, no cloud, no telemetry required. Your project
   files never leave the machine, and nothing Studio does leaves your local
   network. Privacy and offline reliability are features, not promises.
2. **Preserve, never destroy.** Geometry, painting, and color are sacred. The
   engine fails safe: a conversion is rejected on any change it cannot account for,
and a fidelity report states per project what was preserved, changed or unverified. Inputs
   are never overwritten.
3. **Cross-ecosystem by default.** Bambu, Orca, and raw STL are first-class today;
   PrusaSlicer is detected/read in limited form, with Cura, Creality, and broader
   adapters planned. We meet users where their files already are.
4. **Truthful state.** "Validated" must mean it actually loads clean. The Doctor
   and validator never report success they can't prove (verified against a
   real-world corpus, not a happy path).
5. **Open and inspectable.** The engine is open source. A maker can read exactly
   what we change in their file. Trust is earned by transparency.
6. **Extensible.** Every capability is a module behind a stable contract, so the
   community and vendors can add ecosystems and tools without forking.

## 4. Product Pillars

The platform is organized into five durable pillars. Features map to pillars;
pillars do not change when printers do.

| Pillar | What it owns | Today |
|---|---|---|
| **Diagnose** | Compatibility scoring, issue detection, "what can Studio check here?" | Doctor (READY/REPAIRABLE/CONVERTIBLE/HIGH_RISK, score/100) |
| **Transform** | Convert/repair/normalize across ecosystems, preserving design | Bambu/Orca→U1, Prusa/geometry-only 3MF wrap, STL wrap, identity normalization |
| **Validate** | Prove output is clean before the user wastes a print | `is_u1_clean` gate + real-world corpus (112 files, 100% structurally valid — internal gate, not print success) |
| **Manage** | Projects, versions, libraries, comparison, history | Workspace + diff foundation (mock UI shipped; engine in progress) |
| **Optimize** | Printability, material/cost/time intelligence, tuning | Optimization profiles (foundation in engine) |

The **Diagnose → Transform → Validate** loop is the proven core today; **Manage**
and **Optimize** are where the platform compounds.

## 5. 3-Year Roadmap

See [ROADMAP.md](ROADMAP.md) for the phased plan. Summary arc:
- **Year 1 — Reliable cross-ecosystem conversion + project workspace.** Own the
  "make any file print on my printer" job, end to end, with a polished app.
- **Year 2 — Optimization Studio + project library + batch.** Move from "it
  loads" to "it prints *well*"; manage many projects, not one file.
- **Year 3 — Manufacturing platform + plugin marketplace.** Multi-printer,
  simulation/failure-prediction, and a community/vendor extension ecosystem.

## 6. Plugin Architecture Vision

Snapmaker Studio is a **kernel + plugins**, not a monolith. The kernel is the
pure engine (`snapstudio_core`) and the local sidecar API; everything ecosystem-
or printer-specific is a plugin behind a stable contract.

Plugin types:
- **Ecosystem adapters** — read/normalize a slicer family (Bambu, Orca, Prusa,
  Cura, Creality). Adding a slicer = adding an adapter, not editing the core.
- **Printer profiles** — a printer's identity block, presets, bed, and rules
  (e.g. the U1 identity layer). New printer = new profile pack.
- **Transforms** — repair/optimize passes (purge tuning, support strategy,
  preset migration) that run over the normalized model.
- **Validators** — pluggable "is it clean for target X?" checks.
- **Views** — UI panels/workflows in the desktop shell.

Why this matters: the hard-won knowledge (what triggers a "Customized Preset"
warning, min-4 filament blocks, array-length consistency) lives in declarative
profile/adapter packs that a community can extend and a vendor can certify —
without a single fork. The corpus validator becomes the CI that keeps every
plugin honest.

## 7. Ecosystem Strategy

- **Be the neutral layer.** We are not a slicer and not a printer vendor. We are
  Switzerland for 3D printing files — which is precisely why both makers and
  vendors can trust us.
- **Files as the network.** Every shared/inherited project that "just works" in
  Studio is a proof point. Compatibility is the growth loop.
- **Community profile/adapter packs.** Crowdsource the long tail of slicers and
  printers; the kernel + corpus keep quality high.
- **Vendor partnerships.** Printer makers gain a polished, open onboarding path
  for foreign files onto their hardware without building it themselves.
- **Knowledge as a moat.** The validation corpus + categorized failure taxonomy
  is a compounding asset no single slicer is incentivized to build.

## 8. Why Snapmaker Studio should exist even if OrcaSlicer exists

OrcaSlicer is an excellent **slicer** — its job is to turn *one* prepared,
already-compatible project into G-code for a configured printer. Studio owns a
different, unmet job: **getting a foreign/broken/ambiguous file *to* that
clean, compatible state in the first place — across ecosystems.**

- **Orca assumes you're already in its world.** It doesn't repair a Bambu H2D
  project so it loads clean on a Snapmaker U1; it shows the "Customized Preset"
  and "newer version" warnings (the exact problem Studio eliminates).
- **Orca is per-fork, per-vendor.** Snapmaker Orca, Bambu Studio, and stock Orca
  diverge. Studio is the layer *above* the forks that reconciles them.
- **Orca is a slicer, not a workflow.** No cross-ecosystem diagnosis, no
  preservation-guaranteed conversion, no project library, no corpus-validated
  "this will load clean," no multi-printer management.
- **Studio makes Orca better.** The output of Studio is a prepared U1 profile copy
  to open in (Snapmaker) Orca and review before slicing. We are complementary, not competitive —
  the on-ramp to the slicer, not a replacement for it.

In short: Orca slices; Studio makes anything *sliceable here*.

## 9. Why it becomes more valuable as new printers appear

Studio's value scales with **fragmentation**, and the market is fragmenting fast
(Bambu, Snapmaker U1, Creality K-series, Prusa XL/CORE, Anycubic, etc.), each
with its own format dialect, preset identity, and multi-tool quirks.

- **Each new printer = a new conversion target and a new source.** The value of
  a universal translator grows with the number of languages — combinatorially.
- **Migration is the recurring pain.** Every maker who switches or adds a printer
  faces "rebuild years of projects." Studio turns that into a one-click convert.
- **Multi-material multiplies the edge cases** (toolhead counts, purge matrices,
  filament-array consistency) — exactly where Studio's engine is differentiated.
- **The corpus + profile packs are leverage.** Supporting printer N+1 is adding a
  profile pack validated by the existing corpus, not a rewrite. Marginal cost
  falls while addressable value rises.

A slicer's value is roughly constant per user; Studio's value rises with every
printer and ecosystem added to the world.

## 10. Innovation Fund positioning

Snapmaker Studio is a strong fit for an innovation/ecosystem fund (e.g.
Snapmaker's) because it **grows the hardware's addressable market without the
vendor building or maintaining it**:

- **De-risks switching to U1.** A Bambu/Prusa owner's existing library becomes
  prepared for the U1 in one click (review in Orca before slicing) — directly lowering the barrier to buying the printer.
- **Open-source + local-first** aligns with maker trust and avoids the vendor
  having to own a cloud/account product.
- **Leverage, not headcount.** A small grant funds a platform that the community
  extends; the vendor gets an onboarding funnel and goodwill, not a cost center.
- **Defensible public good.** Funds a neutral compatibility layer that benefits
  the whole ecosystem while disproportionately benefiting the sponsoring printer
  (which gets first-class, certified profile support).
- **Measurable.** Corpus success rate, converted-files count, and printers
  supported are concrete milestones a fund can track.

## 11. Open-source strategy

- **Core is open (MIT).** The engine (`snapstudio_core`), CLI, and desktop shell
  are open source. Trust in a tool that rewrites your files *requires* this.
- **Open profile/adapter format.** Printer profiles and ecosystem adapters are
  declarative, documented, and community-contributable.
- **Corpus-as-CI, in the open.** The validation methodology (not users' private
  files) is public, so contributions can't regress reliability.
- **Public roadmap + transparent changelog.** Build in the open; community
  decides the long tail of supported hardware.
- **Governance toward a foundation** as adoption grows, to guarantee neutrality
  (no single vendor controls the translation layer).

## 12. Commercial strategy

Open core, with revenue that never compromises the local-first, no-lock-in
promise. The free, open desktop platform stays fully capable for makers.

- **Studio Pro (individual/prosumer).** Convenience + power on top of the open
  core: batch/fleet workflows, advanced optimization, simulation/failure
  prediction, priority profile packs. Local; one-time or modest subscription.
- **Vendor partnerships / certified profiles.** Printer makers sponsor and
  certify first-class profile packs and onboarding flows.
- **Innovation/ecosystem grants** (see §10) fund platform milestones.
- **Marketplace rev-share** (Year 3) on premium community plugins.
- **Optional team/manufacturing tier** for multi-printer/queue management in
  small production shops.

Non-goals: no ads, no selling user data, no cloud-lock, no paywalling basic
compatibility. The translation layer for the ecosystem must stay trustworthy and
free at its core.

## Traction & proof points (today)

Not a deck promise — shipped and measured:

- **112 real-world files, 100% structurally valid conversions (internal gate — not print success)** (Bambu, Orca, Prusa/geometry,
  STL; single + multi-color; custom presets; large + non-English files), proven
  by an automated validation corpus.
- **Prepared U1 output reviewed in Snapmaker Orca** on real user files (e.g. a Bambu H2D
  project → U1 profile copy, reviewed by a user).
- **One-click Windows installer** (~14 MB) with a bundled engine — **no Python,
  no terminal, no cloud, no account**.
- **Zero orphan processes** across graceful close, crash, and force-kill
  (OS-level Job Object guarantee).
- **Truthful validation:** conversion reports success only when the output is
  provably clean (no foreign Bambu/BBL/H2D identity survives).

### Metrics we steer by
Corpus success rate · ecosystems supported · printers supported · converted-files
count · "validated-but-warns" defects (target: 0) · geometry/color-loss incidents
(target: 0) · clicks from foreign file → clean print (target: 1).

---

### One-line positioning

> **OrcaSlicer slices. Snapmaker Studio makes anything sliceable — anywhere.**


---

## Mission

_(Merged from the former PRODUCT_MISSION.md.)_

# Snapmaker Studio — Mission

## Mission statement

**Give makers one place to take any model, from any ecosystem, to a reliable
multi-material print — without losing their work to format wars, vendor
lock-in, or silent compatibility failures.**

_Understand any design, see what Studio could check, get a copy ready for Orca._ The flow is always
**Understand → Validate → Prepare → Monitor** — Validate never skipped.

## What we believe

- **Your files are yours.** Years of projects, painting, and tuned settings are
  a maker's accumulated craft. Switching printers or slicers should never mean
  rebuilding that from scratch. Migration should be one click, not a project.
- **Compatibility is a workflow problem, not a slicer feature.** The pain lives
  *between* tools — foreign formats, diverging presets, multi-material edge
  cases. No single slicer is incentivized to solve the seam. We are.
- **Trust requires transparency.** A tool that rewrites your files must be open,
  local, and honest. "Validated" means it actually loads clean — proven, not
  promised.
- **Multi-material is the frontier.** Single-color is mostly solved; multi-tool
  is where things break. Solving it well is the mission's center of gravity.

## Who we serve

- **The switcher / multi-printer maker** — owns a Bambu/Prusa/Creality library,
  is adding or moving to a new printer (e.g. Snapmaker U1), and refuses to
  abandon their projects.
- **The novice** — downloaded a file that "won't load right," wants one button
  and a clear answer, not a forum thread.
- **The prosumer / small shop** — runs many files and (soon) many printers, and
  needs reliability and batch throughput.

## How we measure the mission

- **Conversion reliability:** internal validation-gate pass rate (today: 112/112
  structurally valid outputs — not print success) — held at or near 100% as coverage grows.
- **Breadth:** ecosystems and printers supported.
- **Truthfulness:** zero "validated but actually warns in the slicer" defects.
- **Preservation:** zero geometry/color-loss incidents.
- **Time-to-print:** clicks from "foreign file" to "opens clean on my printer"
  (target: one).

## What we will not do

- Sell or upload user files. Local-first, always.
- Silently reduce colors, mutate geometry, or overwrite originals.
- Lock basic compatibility behind a paywall or an account.
- Become "another slicer." We make files *sliceable*; the slicer slices.

See [PRODUCT_VISION.md](PRODUCT_VISION.md) for the full strategy and
[ROADMAP.md](ROADMAP.md) for the plan.
