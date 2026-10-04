# Next moves — what would make Studio elite

> **Status note, 2026-10-04.** This plan was written on 2026-08-23 around a 22 September deadline that has passed.
> Voting ran 22–30 September and provisional results are due 9 October 2026. Read its "Before / After 22 September"
> headings as historical. Current facts: [USER_EVIDENCE.md](USER_EVIDENCE.md), [PHASE1_POSITION.md](PHASE1_POSITION.md).

Updated **2026-08-23**, after the beta.24 release sprint. Phase 1 submissions
close **7 September 2026** — fifteen days from this update.

Items completed since the previous version of this document are listed first, so
this file never reads as if shipped work were still pending.

---

## The honest read on where Studio stands

**Strong on merit, invisible in the field.** The full reassessment against all 41
current entries is in [PHASE1_POSITION.md](PHASE1_POSITION.md); Studio is last in
the field on every community measure and, as far as can be found, the only entry
doing pre-print validation at all. In the Phase 1 field as first surveyed on 2026-08-22
([COMPETITOR_MATRIX.md](COMPETITOR_MATRIX.md)), Studio was the sole entry doing
pre-print validation, the sole one costing a print, and the sole one naming the
right community tool for a file. That survey is dated and needs re-checking for
Phase 2. Since then Studio has added the project↔printer join, a fidelity audit,
an auditable fix ledger with a real way back, colour classification beyond four
toolheads, and a one-command self-check — all with evidence grading and
refusal-to-guess enforced by tests rather than by convention.

**Weak, and it is now one weakness rather than two.** Visibility. 20% of the Fund
score is community, weighted partly on GitHub stars, and Studio sits at the bottom
of the measured field. The product no longer has a "nothing to see" problem —
there are current screenshots, a recorded demo of the running application, and a
release verified against real hardware. What was missing in August was people: that has started to change (20 stars and two reports from an outside user on 2026-10-04), but it is small, and the installer is still unsigned.

---

## State this plan starts from

**Submitted, confirmed, publicly listed** — among the Phase 1 projects (the Fund page now counts 66–67).
Voting ran 22–30 September 2026; provisional results are due **9 October 2026**. Nothing about entering the fund
is outstanding. See [PHASE1_POSITION.md](PHASE1_POSITION.md) for where Studio
actually stands against the other 40.

## Done since the last update

| Was | Now |
|---|---|
| Record and publish the demo | Recorded from the installed beta.24 build, 71 seconds, at the top of the README |
| Post the ecosystem notes | Four posted 2026-08-23; URLs in [ECOSYSTEM_OUTREACH.md](ECOSYSTEM_OUTREACH.md) |
| Installed-build acceptance | 21 checks against the shipped installer |
| Real hardware verification | 13 read-only checks against a real U1; found and fixed a genuine firmware-reading bug |
| Release acceptance | beta.24 is the first build marked ACCEPTED with software, installed-application and hardware evidence |
| **CI** | The `cargo check` job had failed on every run since it was added, because Tauri needs the frozen sidecar to exist and CI does not build it. Fixed; the trust record's false "enforced in CI" claim is corrected |
| **Repository discoverability** | The GitHub description still carried the pre-pivot "workflow platform" positioning and the repo was not in the top 30 results for "snapmaker". Description, homepage and topics rewritten |
| **Listing correction** | Investigated; there is no editing UI, so a factual update was prepared on the fund's own confirmation thread — [LISTING_UPDATE.md](LISTING_UPDATE.md) |
| **Community post** | Checked first: the project has never been posted on the Snapmaker forum. Written and ready — [COMMUNITY_POST.md](COMMUNITY_POST.md) |

---

## Before 22 September — only these

The bar: does it change what a judge understands, or what a user can verify?
Feature work does not clear it.

### 1. Send the listing correction
**The single highest-leverage item.** The card the committee reads describes the
June product. One email fixes two months of invisible work. Drafted and waiting in
the maintainer's mailbox; sending it is theirs.

### 2. Post the community update
Never done, verified today. It is also the only honest route to the 20% community
component — and that component has no voting system built yet, so there is nothing
to game even if we wanted to. Written; posting is the maintainer's.

### 3. Keep the build green and the evidence reproducible
CI is now honest. It should stay that way through the evaluation window, because
"run it yourself" is the whole argument and a red X refutes it silently.

### 4. Answer anything that arrives
Four ecosystem notes are out and a community post is pending. A maintainer's
correction or a first bug report is worth more than any feature — it would be the
project's first external evidence of any kind.

---

## After 22 September — the strongest product work

### 5. Painted-colour enumeration
**P5 D5 J4 N4 T5 E3 R2 C2 · cx4 rr2**

`color_plan` currently reports painted colours as unclassified, because per-triangle
paint data is encoded and Studio will not guess. Decoding it properly would turn
"cannot classify" into a real answer for the hardest multi-colour projects — the
single biggest remaining accuracy gain, and genuinely difficult.

### 6. Diagnostic packs as data
**P3 D5 J3 N2 T4 E5 R2 C3 · cx3 rr2**

The ecosystem registry proved a rule set can live in JSON with a schema and a test
that rejects rules referencing facts the engine cannot measure. The same shape for
*diagnostics* would let the community contribute checks without touching engine
code. This is the strongest long-term answer to the Fund's openness criterion.

### 7. Broaden the hardware surface
**P3 D3 J3 N3 T2 E3 R3 C3 · cx2 rr1**

One U1, one firmware version. The read-only harness generalises; the sample does
not. More machines and more firmware builds would turn "verified on hardware" into
"verified across hardware". The original form of this item — verify the preflight
against a real printer at all — was completed in beta.24 and found a real bug.

### 8. A second printer
**P2 D4 J3 N1 T4 E4 R2 C3 · cx4 rr3**

"Not U1-only by construction" is still unproven. Adding one more machine — profile
plus capability detection, no per-check branching — would prove it, and will expose
every place a U1 assumption is still hard-coded.

### 9. Project reproducibility manifest
**P2 D5 J3 N1 T4 E5 R3 C4 · cx2 rr1**

A versioned JSON summary emitted beside a prepared copy: provenance, graded traits,
changes applied, fidelity result. Makes a converted project auditable by a third
party. Most of the content already exists across `traits`, `fidelity` and the
ledger; this is the assembly.

### 10. Cost from a sliced project, end to end
**P3 D4 J3 N4 T2 E2 R2 C4 · cx2 rr1**

`project_cost` reads figures a slicer recorded, but the loop is only closed when a
user slices in Orca and reopens the saved project. Making that round trip a
first-class flow — "slice it, then bring it back here" — turns a capability into a
habit.

---

## Explicitly not doing

- **Slicing, or forking a slicer.** It would make Studio a worse Orca overnight.
- **A second printer dashboard.** Fluidd already ships on the machine.
- **A browser extension.** The nearest competitor's coupling to one site's DOM
  broke it in three of its last four releases. Any local file is a better input.
- **Requiring Extended Firmware.** Most owners run stock, and its presence cannot
  be reliably detected anyway.
- **LLM features.** Everything Studio does is deterministic and explainable. An
  "AI" button would weaken the one property that makes it trustworthy.
- **Chasing feature count.** The Fund's criteria reward depth over breadth, and a
  polished capability beats six unfinished ones.

---

## If only one thing gets done before 22 September

Send the listing correction. The engineering is done, recorded, verified against
hardware and reproducible by anyone — and the page the committee reads still
describes the June build. Everything else on this page is worth less than closing
that gap.
