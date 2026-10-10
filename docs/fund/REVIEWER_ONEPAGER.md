# Snapmaker Studio — Reviewer One-Pager

> **HISTORICAL — describes the v0.4.0-beta.1 RC era; not the current release.** In particular, 'read-only printer access / no printer control' was true then; the current Printer Hub provides monitoring plus user-confirmed controls (never auto-start). Current state: [`../TRUST_STATUS.md`](../TRUST_STATUS.md) · [`../RELEASE_METADATA.md`](../RELEASE_METADATA.md).

**The Intelligence Layer for open 3D printing.** Local-first desktop companion for
the Snapmaker U1. *Independent open-source project — not affiliated with Snapmaker.*

### The problem
Orca slices but won't say *why* a job fails ("out of bounds", no reason). Fluidd
shows raw telemetry, not judgement. Cost/price live in spreadsheets. Fixes are
scattered across Facebook, Reddit, GitHub. New owners waste filament on prints that
were never going to work.

### What Studio does
Before a layer is sliced, one screen — the **Studio Intelligence Report** — answers:
**What's at risk? · What will it cost? · What to sell it for? · Profit? · Biggest
risk? · Next action?** Each risk carries the **community's known fix** with a
confidence level. (Earlier builds also showed an expected-improvement percentage; it was
never calibrated and was removed in #92.)

### Why it's novel (and why it expands the ecosystem)
No tool in the U1 world does **cost -> pricing -> profit** intelligence, **pre-slice
out-of-bounds explanation**, or **community-knowledge-backed fixes**. Studio reads
the U1's own open Klipper/Moonraker data (read-only) + model geometry and
**synthesises** seven specialised "Doctors" into one verdict — making the open U1
approachable to first-time and business users.

### Outcomes vs the alternatives
| Maker's question | Orca | Fluidd | **Studio** |
|---|---|---|---|
| What is at risk, before slicing? | no | no | **yes** (advisory checks, not a prediction) |
| Why won't it, + the fix? | no | no | **yes** |
| Cost / price / profit? | no | no | **yes** |
| Printer healthy? (0–100) | no | partial | **yes** |
| Community fix in-app? | no | no | **yes** |
| One answer in 15s? | no | no | **yes** |

### Proof
- **60-second demo, zero setup:** Launch -> one-click Demo -> Intelligence Report
  -> community fix -> cost/price/profit -> "Why Studio?". No printer or file needed.
- **Engineering:** 166 automated tests green; v0.4.0-beta.1 RC built; frozen engine
  smoke-tested (endpoints 200, launch, 0 orphans).
- **Safety:** read-only printer access (no print-control); local-first; estimates
  clearly labelled; no fabricated data.

### Ask
Innovation Fund support to expand the Snapmaker ecosystem's intelligence + business
layer for the open U1.

*See `SUBMISSION.md`, `VALIDATION.md`, `METRICS.md`, `SCORECARD.md`.*
