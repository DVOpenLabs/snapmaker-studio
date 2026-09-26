# Final submission package — Snapmaker Innovation Fund, Phase 1

**Status: submitted, confirmed, and publicly listed.** Entry sent 24 June 2026,
confirmed 29 June, listed as one of the 41 projects in the running. There is
nothing left to enter — see [SUBMITTED_ENTRY.md](SUBMITTED_ENTRY.md) for the exact
text the committee received.

This page is now the index to the package a judge would read, plus the record of
what the entry says versus what the project is. Evaluation closes
**22 September 2026**; 20 of the 41 win. Where Studio stands in that field:
[PHASE1_POSITION.md](PHASE1_POSITION.md).

> Independent open-source project — not affiliated with or endorsed by Snapmaker.

---

## 1. What the entry says

| Field | As submitted, 24 June 2026 |
|---|---|
| Project name | Snapmaker Studio |
| Project URL | <https://github.com/DeadlyVirusIn/snapmaker-studio> |
| Category | Slicer / software (listed on the wall as *Workflow*) |
| Name, email | Kunal Khurana, kunalkhurana1@gmail.com |
| Description | The June text, verbatim in [SUBMITTED_ENTRY.md](SUBMITTED_ENTRY.md) |
| Cover image | The old "workflow platform" banner |

The listing describes the June build. A correction was prepared for the fund's own
confirmation thread, with a replacement description and a replacement 640×360 card
at [`../brand/innovation-fund-card.png`](../brand/innovation-fund-card.png) — see
[LISTING_UPDATE.md](LISTING_UPDATE.md).

**Do not re-submit the form.** A second entry is a duplicate, which is worse than
a stale description.

## 2. The current description

The text below is what the project would say today, and what the repository says.
It is not a form field any more; it is the answer to "what is this?" for anyone
who arrives from the wall.

> Snapmaker Studio is a free, local-first desktop app that reads a downloaded 3D
> project, explains the risks in plain language, compares it against your actual
> U1 over Moonraker, fixes only what it can justify, and proves what survived.
> Snapmaker Orca still slices.

Long form: [../INNOVATION_FUND.md](../INNOVATION_FUND.md).

## 3. What is being submitted

**Release:** [v1.0.0](https://github.com/DVOpenLabs/snapmaker-studio/releases/tag/v1.0.0)
— the current stable build; v0.4.0 was the first verified against a real Snapmaker
U1, and every release since has been. Installer name, size and SHA256:
[../RELEASE_METADATA.md](../RELEASE_METADATA.md). Verification record:
[../TRUST_STATUS.md](../TRUST_STATUS.md).

**Demo:** [`docs/media/snapmaker-studio-demo.mp4`](../media/snapmaker-studio-demo.mp4)
— 66 seconds, every frame the installed application.

## 4. How the package maps to the three judged criteria

The committee scores 80% on Innovation & Technical Depth, Openness & Quality, and
Practicality & Adaptability. The remaining 20% is a community vote.

| Criterion | Read this | The one-line case |
|---|---|---|
| Innovation & Technical Depth | [TECHNICAL_DEPTH.md](TECHNICAL_DEPTH.md) | Being correct when the file or the printer does not expose enough information to be certain — evidence grading, a project-to-printer join, a preservation invariant, a fidelity audit that can fail, deterministic colour classification, and a feature withdrawn because its maths could not be justified |
| Openness & Quality | [OPEN_ECOSYSTEM.md](OPEN_ECOSYSTEM.md) | MIT, local-first, no account or telemetry, documented CLI and local API, a data-file ecosystem registry anyone can extend by pull request, and every claim reproducible by one command |
| Practicality & Adaptability | [JUDGE_OVERVIEW.md](JUDGE_OVERVIEW.md) | Seven concrete novice dead-ends, each with what Studio actually does — and a printer layer that speaks Moonraker rather than anything U1-specific |
| Community (20%) | [USER_EVIDENCE.md](USER_EVIDENCE.md) | Thin and honestly reported: interest is measured, outcome is empty, and nothing is inflated to cover the gap |

## 5. Evidence, in one table

Verified against the published v1.0.0 installer, not a development build.

| What | Result |
|---|---|
| Installed-application acceptance, through the real UI (incl. the v0.9.0→v1.0.0 upgrade) | 39/39 |
| Linux clean-image validation, Ubuntu 22.04 + 24.04 | 35/35 each |
| Read-only verification against a real Snapmaker U1 | 39/39 |
| Regression tests against genuine Orca/Bambu/Prusa projects | 36 tests |
| End-to-end pipeline self-check | 27/27 |
| Backend tests | 1833 passed, 7 skipped |
| Desktop tests | 340 passed |
| TypeScript · production build · Rust | clean |

Reproduce any of it: [JUDGE_WALKTHROUGH.md](JUDGE_WALKTHROUGH.md).

## 6. The claims this package will not make

Stated here so they cannot creep back in under deadline pressure:

- **No print-success guarantee.** Every check is advisory.
- **No "nothing was lost"** unless the fidelity audit granted that claim for that
  specific project.
- **No endorsement.** Snapmaker has not endorsed this project, and neither has any
  of the community projects Studio names.
- **No fabricated adoption.** There are no testimonials because there are no
  testimonials.
- **No signed-installer claim** until an installer is actually signed.
- **The 112-file corpus is not headline evidence.** It measures structure, not
  print success, and it is dominated by STLs. It stays as historical context.

## 7. What is actually left before 22 September

1. **Send the listing correction** — drafted in the maintainer's mailbox, on the
   fund's own confirmation thread. [LISTING_UPDATE.md](LISTING_UPDATE.md).
2. **Post the community update** — written, never posted before, and checked to
   confirm that. [COMMUNITY_POST.md](COMMUNITY_POST.md).

That is the whole list. Code signing is prepared but will not land inside the
evaluation window and does not affect judging; it is tracked separately in
[../CODE_SIGNING_POLICY.md](../CODE_SIGNING_POLICY.md).

## 8. Package contents

| File | What it is |
|---|---|
| [../INNOVATION_FUND.md](../INNOVATION_FUND.md) | The current description of the project, plus the fund's rules |
| [SUBMITTED_ENTRY.md](SUBMITTED_ENTRY.md) | The June entry, verbatim — historical |
| [PHASE1_POSITION.md](PHASE1_POSITION.md) | Where Studio stands against the other 40, and the five real risks |
| [LISTING_UPDATE.md](LISTING_UPDATE.md) | Why the public card is stale and what was done |
| [COMMUNITY_POST.md](COMMUNITY_POST.md) | The community update, written and ready |
| [JUDGE_OVERVIEW.md](JUDGE_OVERVIEW.md) | Five-minute orientation for a judge |
| [JUDGE_WALKTHROUGH.md](JUDGE_WALKTHROUGH.md) | Reproduce every claim yourself |
| [DEMO_SCRIPT_90_SECONDS.md](DEMO_SCRIPT_90_SECONDS.md) | The recorded demo, beat by beat |
| [TECHNICAL_DEPTH.md](TECHNICAL_DEPTH.md) | The engineering case |
| [OPEN_ECOSYSTEM.md](OPEN_ECOSYSTEM.md) | Licence wall, registry, interoperability |
| [COMPETITOR_MATRIX.md](COMPETITOR_MATRIX.md) | The measured field |
| [DIFFERENTIATION_STRATEGY.md](DIFFERENTIATION_STRATEGY.md) | Why this position holds |
| [USER_EVIDENCE.md](USER_EVIDENCE.md) | Measured community signal, interest separated from outcome |
| [ECOSYSTEM_OUTREACH.md](ECOSYSTEM_OUTREACH.md) | The notes sent to other maintainers, verbatim, with URLs |
| [NEXT_MOVES.md](NEXT_MOVES.md) | What is left, ranked, weaknesses first |
| [CHANGE_SUMMARY.md](CHANGE_SUMMARY.md) | What changed and why, across the sprints |
