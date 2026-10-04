# Phase 1 field scorecard — all 41 projects, one rubric

> **Status note, 2026-10-04.** Compiled 2026-08-23 against the 41 projects then listed; the Fund page now shows
> 66–67 and new dates (Phase 1 submissions closed on 7 September, community voting on 22–30 September, **provisional results on 9 October**, and a review window that closes 15 October; Phase 2 submissions run 19 October – 14 December (results 31 December, final 14 January)). The tables below are that
> day's record, not current. Refreshed community figures: [USER_EVIDENCE.md](USER_EVIDENCE.md) and
> [PHASE1_POSITION.md](PHASE1_POSITION.md).

**Compiled 2026-08-23.** Every repository metric was read from the GitHub API on
that date. This file replaces the loose language used in earlier reports ("top
quartile", "borderline") with a stated rubric, per-project scores, and an evidence
level attached to each score.

**One date is unresolved and is recorded rather than guessed.** The maintainer
states that Phase 1 evaluation ends **22 September 2026**. The fund's public page
shows Phase 1 as *"Jun 9 – Sep 7, 2026 · Winners Sep 30"*. Both may be true — a
submission cut-off and an evaluation cut-off are different things — but they have
not been reconciled from a single source. Under the project's state-reconciliation
rule the maintainer's statement is the higher authority and is used throughout;
the discrepancy is noted here so nobody silently "corrects" one to the other. The
page watcher in `tools/watch/innovation_fund.py` tracks both strings.

It is a model, not a prediction. The Technical Committee has not published
weights inside each criterion, and 20% of the score is a community vote whose
mechanism does not exist yet.

---

## The rubric

Three dimensions, each scored **0–5**, taken from the fund's published criteria.

### Innovation & Technical Depth
Originality of the idea · difficulty of the problem · whether it unlocks a U1
capability that did not exist · technical sophistication of the implementation ·
whether it actually works · **depth rather than feature count**.

### Openness & Quality
Source accessibility · reproducibility by a stranger · documentation ·
tests · release quality · extension points · maintainability · **transparent
limitations** · contribution readiness.

> **Licence family is not scored as quality.** GPL and AGPL are not penalised, and
> MIT earns nothing on its own. What is scored is whether someone else can read,
> run, verify and extend the work. An earlier version of this analysis credited
> Studio for being MIT "in a GPL-heavy field"; that was wrong and is withdrawn.

### Practicality & Adaptability
Does it solve a real U1 problem today · how many users it helps · how easy it is
to try · usefulness now rather than eventually · applicability beyond one
project/printer/workflow · novice usability where that is the point.

### Community evidence — kept separate, never mixed into the three above
Stars · forks · contributors · issues · discussions · releases · community posts.
**Stars are not evidence of technical quality** and are not used as such anywhere
in this document.

## Evidence levels

| Level | Meaning |
|---|---|
| **VERIFIED** | Repository inspected: metrics, README, releases, tests, CI read directly |
| **STRONG INFERENCE** | Repository found and metrics read, but capability judged mostly from README/releases rather than code |
| **WEAK INFERENCE** | Only partial public material — a repository exists but little is legible, or identity is probable but unconfirmed |
| **UNKNOWN** | No public repository found from the fund listing. **Scored as unknown, not as zero.** A project may be excellent and simply not linked from a name I could resolve. |

Nineteen of the 41 fall into UNKNOWN. That is a limit of this analysis, not a
judgement on those projects, and it means any ranking below is a ranking of *what
can be seen*.

---

## Scores

Technical dimensions: **I** = Innovation & Technical Depth, **O** = Openness &
Quality, **P** = Practicality & Adaptability. "—" means not scored (UNKNOWN).

### Repository found and inspected

| Project | I | O | P | Evidence | Basis |
|---|:-:|:-:|:-:|---|---|
| SnapmakerU1 Extended Firmware | 5 | 4 | 5 | VERIFIED | Unlocks capability the stock machine does not have (SSH, debugging, hardware-accelerated camera, Klipper metrics). 21 contributors, 18 releases, 5 CI workflows, GPL-3.0. Deep systems work with obvious daily value; no visible test suite. |
| Lumina-Layers | 5 | 4 | 4 | VERIFIED | Physics-based multi-material colour — genuinely hard, original, and it works. 24 contributors, 60 test files, CI, 5 releases. Docs strong. Not U1-specific, which cuts both ways for this fund. |
| AFC-Klipper-Add-On | 5 | 4 | 4 | VERIFIED | Hardware-agnostic multi-material automation framework; the deepest Klipper integration in the field. 40 contributors, 35 test files, 11 releases, 93 open issues (an active user base, not neglect). Raises the U1's colour ceiling. |
| Kromacut | 4 | 4 | 5 | VERIFIED | Image → layered colour print. Not a novel category, but a strong implementation: 14 test files, 3 CI workflows, 6 releases, 27 KB README. Instantly useful to any U1 owner with a photo. |
| OrcaSlicer ImageMap | 5 | 3 | 4 | VERIFIED | Prints image textures most slicers discard — the hardest slicer-side idea here. 33 releases, 16 CI workflows. Issues are **disabled**, which is a real openness cost: there is no channel for a user to report anything. |
| SpoolEase | 4 | 3 | 4 | VERIFIED | Filament inventory and tracking wired into printers and slicers; clearly used (543 stars, 21 issues, discussions enabled). Licence is unrecognised by GitHub, no test suite visible, 2 releases. |
| sindricad | 4 | 3 | 4 | VERIFIED | Open parametric CAD, Linux-first, U1-first. 25 KB README, 2 CI workflows, but **1 contributor, 1 release, no visible tests** — young for its star count. |
| u1-slicer-for-android | 4 | 3 | 5 | VERIFIED | OrcaSlicer on Android: slice and send from a phone. Genuinely hard porting work, and **100 releases** — the highest velocity in the field. No visible tests; 27 open issues. |
| FOrcaSlicer | 4 | 3 | 4 | VERIFIED | Mixed-nozzle slicing for the U1. 21 releases, 13 test files, 3 CI workflows. Contributor count is inflated by the OrcaSlicer fork history. Research-preview framing is honest. |
| bespok3d | 4 | 3 | 4 | VERIFIED | App store and package manager for Klipper printers — a platform idea, not a tool. 6 releases, 3 contributors, CI. Early; the value depends on an ecosystem that does not exist yet. |
| u1hub | 3 | 3 | 5 | VERIFIED | Multi-printer dashboard, remote filament swaps, gcode transfer. 36 KB README, 11 releases, CI. Solves a daily problem for anyone with more than one U1. No visible tests, 1 contributor. |
| snapmaker-u1-toolkit | 3 | 4 | 4 | VERIFIED | Mobile-first send-and-monitor with confirm-before-print. **69 test files** and 37 releases from one maintainer — the strongest test discipline of the small projects. |
| ditherforge | 4 | 4 | 4 | VERIFIED | GLB/OBJ → dithered colour 3MF with mesh repair. 14 test files, CI, and a 50 KB README — the most thoroughly documented project of its size in the field. |
| makerworld-to-snapmaker-u1 | 3 | 3 | 5 | VERIFIED | One-click browser conversion at the moment of download. Modest technically; extremely practical, and 12 releases show it is maintained. |
| bambu-to-snapmaker-u1 | 3 | 2 | 4 | VERIFIED | Web converter. 11 open issues, 3 contributors, CI, but **no releases** and an unrecognised licence. |
| bl2u1 | 3 | 2 | 4 | VERIFIED | Bambu → Snapmaker Orca converter with real traction (67 stars). **No CI, no releases, last push 7 April** — the least maintained of the converters. |
| SnapCon | 3 | 2 | 4 | STRONG INFERENCE | Fleet management and Orca device control. Small, recent, MIT, 4 open issues; little visible beyond the README. |
| mUlt1ACE | 4 | 2 | 3 | STRONG INFERENCE | Drives up to four Anycubic ACE Pro units with cross-device loading. Real hardware integration, but **no licence file** and no push since 30 April. |
| pandabreath-klipper | 3 | 3 | 3 | VERIFIED | Klipper module for a chamber heater, with a thermal safety interlock and mainline-compliant code. Narrow by design, and honest about it. |
| Orca-Cad (snaporca-cad) | 4 | 2 | 3 | STRONG INFERENCE | Parametric CAD inside Snapmaker Orca — an ambitious idea. Very early: 6 stars, no releases, active this week. |
| BREPcode | 4 | 2 | 3 | STRONG INFERENCE | Browser CAD driven by code or natural language, outputs colour 3MF. Interesting; days old, 4 stars, unrecognised licence. |
| **Snapmaker Studio** | **4** | **4** | **3** | VERIFIED | See the self-assessment below. |

### No public repository resolvable from the listing — UNKNOWN

Bird3D · Miniskyline · QCMS Filament System · Meshivo · Filament Syndicate
Foreman 5 · PolyCarver · Nozzle Buddy · Sidecar 16-Color MMU · U1 Adaptive
Pressure Advance · U1 P1S/X1 Hotend Mod · U1 Driver Heatsink Mod · Adaptive
Manufacturing Planner · Bambu & Snapmaker U1 (nbn.cat) · Helix · PrinterTools ·
PrintProof · btu · OrcaSlicer FS UI rework · OrcaFS-NeotkoCM · Snapmaker-Orca
multi-nozzle.

Several are certainly substantial — the Sidecar 16-colour MMU has a long, active
community thread; the hotend and heatsink mods solve measured thermal problems;
the multi-nozzle slicer work is technically serious. **They are unscored because
I could not verify them, not because they are weak.** Any committee sitting inside
Snapmaker can see all of them, and will.

---

## Studio's own scores, argued against the same rubric

**Innovation & Technical Depth — 4.** The problem framing is original in this
field: nothing else here attempts to be correct when the file or the printer does
not expose enough information. Evidence grading, a project-to-printer join, an
audit that can refuse its own claim, and a feature withdrawn because its
arithmetic could not be justified are real depth. It is **not a 5** because it
unlocks no new machine capability — it explains and prepares, where Extended
Firmware, AFC and ImageMap make the U1 do something it could not do before. On
"U1 capability unlocked", Studio scores low by design.

**Openness & Quality — 4.** The verification apparatus is, as far as I can find,
unmatched in this field: an acceptance harness that drives the *published
installer*, a read-only hardware harness, a one-command end-to-end self-check, a
documentation-consistency lint, and tests that assert what the product must
*refuse* to say. Limitations are stated rather than hidden. It is **not a 5**
because contribution readiness is untested: **one contributor, zero external
issues, no discussions**. A project nobody has contributed to has not demonstrated
that it can be contributed to.

**Practicality & Adaptability — 3.** It solves a real novice problem and installs
in one click, but Windows-only, and its value is preventative — you notice it when
nothing goes wrong. Compare Kromacut or the Android slicer, where the user gets a
visible new capability in the first minute. This is Studio's weakest technical
dimension and no amount of engineering before 22 September changes it.

---

## Community evidence — separate, and unflattering

| Project | Stars | Forks | Issues | Contributors | Releases | Discussions |
|---|---:|---:|---:|---:|---:|:-:|
| Lumina-Layers | 995 | 141 | 21 | 24 | 5 | no |
| Extended Firmware | 933 | 111 | 83 | 21 | 18 | no |
| SpoolEase | 543 | 36 | 21 | — | 2 | **yes** |
| Kromacut | 257 | 29 | 28 | 4 | 6 | no |
| AFC-Klipper-Add-On | 252 | 97 | 93 | 40 | 11 | no |
| sindricad | 143 | 13 | 5 | 1 | 1 | no |
| OrcaSlicer ImageMap | 121 | 5 | disabled | — | 33 | no |
| bl2u1 | 67 | 15 | 4 | 2 | 0 | no |
| u1-slicer-for-android | 53 | 7 | 27 | 2 | 100 | no |
| u1hub | 51 | 3 | 1 | 1 | 11 | no |
| ditherforge | 28 | 2 | 0 | 1 | 2 | no |
| bespok3d | 25 | 1 | 1 | 3 | 6 | no |
| makerworld-to-snapmaker-u1 | 21 | 2 | 1 | 2 | 12 | no |
| FOrcaSlicer | 19 | 1 | 4 | — | 21 | no |
| snapmaker-u1-toolkit | 17 | 0 | 2 | 1 | 37 | no |
| bambu-to-snapmaker-u1 | 15 | 4 | 11 | 3 | 0 | no |
| SnapCon | 11 | 1 | 4 | — | — | no |
| mUlt1ACE | 11 | 0 | 0 | — | — | no |
| pandabreath-klipper | 10 | 2 | 1 | — | — | no |
| Orca-Cad | 6 | 0 | 0 | — | 0 | no |
| BREPcode | 4 | 1 | 0 | — | — | no |
| **Snapmaker Studio** | **1** | **0** | **0** | **1** | 40 | **no** |

On 2026-08-23 Studio was last on stars, forks, issues and contributors among every project whose
repository could be found (refreshed figures: see the note at the top). Its 40 releases are the second-highest count here,
which says something true and unhelpful: **a great deal of shipping, and nobody
watching it happen.**

The one honest bright spot is that release count paired with the verification
apparatus — this is a project that ships and proves, in public, repeatedly. That
is a quality signal, not a community one, and it belongs in the O column where it
already is.

---

## Three rankings

### 1. Technical Committee ranking — the 80%, verified projects only

Ordered by I + O + P, ties broken by depth. UNKNOWN projects are absent and would
change this materially.

| # | Project | I+O+P |
|---:|---|:-:|
| 1 | SnapmakerU1 Extended Firmware | 14 |
| 2 | AFC-Klipper-Add-On | 13 |
| 2 | Lumina-Layers | 13 |
| 4 | Kromacut | 13 |
| 5 | OrcaSlicer ImageMap | 12 |
| 6 | ditherforge | 12 |
| 6 | u1-slicer-for-android | 12 |
| 8 | **Snapmaker Studio** | **11** |
| 8 | SpoolEase | 11 |
| 8 | FOrcaSlicer | 11 |
| 8 | sindricad | 11 |
| 8 | u1hub | 11 |
| 8 | snapmaker-u1-toolkit | 11 |
| 14 | makerworld-to-snapmaker-u1 | 11 |
| 15 | bespok3d | 11 |
| 16 | mUlt1ACE | 9 |
| 17 | Orca-Cad | 9 |
| 18 | BREPcode | 9 |
| 19 | bambu-to-snapmaker-u1 | 9 |
| 20 | pandabreath-klipper | 9 |
| 21 | SnapCon | 9 |
| 22 | bl2u1 | 9 |

Studio sits in a **six-project tie at 11** — the middle of the visible field, not
the top quartile. The earlier claim of "top quartile on two dimensions" does not
survive scoring the others properly: Lumina-Layers has 60 test files and 24
contributors; Kromacut has CI, tests and a 27 KB README; ditherforge has 14 test
files and a 50 KB README. Studio's verification apparatus is more unusual than
theirs, but "unusual" is not the same as "further ahead", and their contribution
health is better.

### 2. Community position — the 20% (2026-08-23 record; refreshed below)

On 2026-08-23: last or joint-last among every project with a findable repository — 1 star,
0 forks, 0 issues, 1 contributor, discussions off. **Refreshed 2026-10-04:** 20 stars, 1 fork,
two issues from one outside user, 155 installer downloads, 484 unique cloners and 180
unique visitors in 14 days. Still below several projects (bl2u1 75, u1hub 66,
makerworld-to-snapmaker-u1 48 stars), above others; the vote closed 30 September.

### 3. Overall scenario model

The community mechanism does not exist yet, so its real weight is uncertain even
though its nominal weight is 20%.

| Scenario | Assumption | Studio's likely band |
|---|---|---|
| **A — Technical-heavy, community neutral** | Committee reads repositories; community vote diluted or lightly used because the system launched late | **11–20**, plausibly 4–10 if a judge runs the harnesses |
| **B — Technical middle, community low** | Committee skims; community vote counts as published | **21–30** |
| **C — Strong technical judging, weak community** | Committee inspects deeply, reproducibility rewarded, community mostly ignored | **4–10** |
| **D — Conservative** | Committee scores from the wall card and visible traction; the June description is what they read | **21–41** |

**Most likely band: 11–20, with meaningful probability of 21–30.** Confidence:
**moderate for the technical placement** (rubric applied consistently, but 19
projects unscored), **low for the overall outcome** (unknown intra-criterion
weights, unknown committee behaviour, unbuilt voting system).

The single variable that moves Studio between bands is not engineering. It is
**whether a judge reads past the wall card** — which is why the listing
correction, the demo, and the first-screen rewrite matter more than any feature.

## What this model deliberately does not claim

- No precise score cutoffs. The committee has published none.
- No prediction of which projects win the three $5,000 places.
- No claim that Studio is better or worse than any UNKNOWN project.
- No use of star counts as a proxy for technical quality, in either direction.
