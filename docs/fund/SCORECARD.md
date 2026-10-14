# Snapmaker Studio — Innovation Fund Readiness Scorecard

> **Historical — written before the Innovation Fund entry was submitted on 24 June 2026.** Kept for the reasoning, not as a description of the project's current state. Current state: [docs/SUBMISSION_STATUS.md](../SUBMISSION_STATUS.md) and [docs/innovation-fund/PHASE1_POSITION.md](../innovation-fund/PHASE1_POSITION.md).

> **HISTORICAL — describes the v0.4.0-beta.1 RC era; not the current release.** In particular, 'read-only printer access / no printer control' was true then; the current Printer Hub provides monitoring plus user-confirmed controls (never auto-start). Current state: [`../TRUST_STATUS.md`](../TRUST_STATUS.md) · [`../RELEASE_METADATA.md`](../RELEASE_METADATA.md).

## Problem -> Solution infographic
```mermaid
flowchart LR
  subgraph P [The pain]
    P1[Out of bounds, no reason]
    P2[Multi-colour fails]
    P3[First layer won't stick]
    P4[Cryptic firmware errors]
    P5[What does it cost / charge?]
    P6[Fixes scattered on forums]
  end
  subgraph S [Studio Intelligence]
    D[7 read-only Doctors]
    C[Community Knowledge]
    R[Studio Intelligence Report]
    D --> R
    C --> R
  end
  subgraph O [Outcome]
    O1[Decide in 15s]
    O2[Exact fix + confidence]
    O3[Cost, price & profit]
    O4[No wasted filament]
  end
  P1 --> D
  P2 --> D
  P3 --> D
  P4 --> D
  P5 --> D
  P6 --> C
  R --> O1
  R --> O2
  R --> O3
  R --> O4
```

## Final screenshot package (`docs/brand/shots/`)
| File | Shows |
|---|---|
| `dashboard_final.png` | Branded dashboard, Doctors first-class, Demo entry |
| `demo_report.png` | Studio Intelligence Report (demo) |
| `report_full.png` | Full Report: metrics, risks + community fixes, why-not-Orca (screenshot predates #92 and shows a score and an Expected Improvement figure Studio no longer displays) |
| `why_studio.png` | Outcome comparison vs Orca & Fluidd |
| `before_dashboard.png` / `after_dashboard.png` | Brand evolution |

## 60-second demo flow audit
3 clicks for the entire narrative — no unnecessary steps:
1. **"See a 10-second demo"** (Dashboard) -> full Intelligence Report renders.
2. **"See risks & Doctor findings"** -> reveals a community fix.
3. **"Why Studio?"** -> positioning.
Every screen reinforces the Intelligence Layer narrative (sidebar mark + tagline on
all; "Powered by Studio Intelligence" on the Report; outcomes framing on Why Studio).
Demo Mode verified: `/demo_report` returns the risks with community fixes (it
returned a score and an Expected Improvement before #92 removed both); renders with no printer and no file.

## Scorecard

### Strengths
- **Unique value:** cost->pricing->profit + pre-slice out-of-bounds explanation +
  community-backed fixes — none of which Orca/Fluidd/OctoPrint do.
- **Instant comprehension:** one Report answers six questions in ~15s; full demo <60s.
- **Zero-setup demo:** works with no hardware/file — ideal for reviewers.
- **Engineering quality:** 166 tests green, clean build, RC smoke-tested, 0 orphans.
- **Trust posture:** local-first, read-only printer access, labelled estimates,
  no fabricated data, clear non-affiliation notice.
- **Brand:** cohesive frozen Intelligence Layer identity end-to-end.

### Risks
- **Live-hardware breadth** is lightly field-tested (mitigated: demo uses sample data).
- **Community Knowledge is a curated MVP**, not live-ingested (Phase 2 documented).
- **External validation pending** — kit ready, tester results not yet collected.
- **Per-file UI shots** require the desktop runtime (capture live in the recorded demo).

### Remaining gaps (non-blocking)
- Run the external tester round; fill the User Validation Report + testimonials.
- Optional: rebuild the installer to fold in the dead-code cleanup (cosmetic; the
  removed helper never ran).
- Optional: in-app FeedbackButton at the four capture points (post-freeze).

### Recommendation: **SUBMIT**
The product is demonstrable end-to-end with no hardware, the differentiation is
clear in under a minute, engineering quality is verified, and every gap is either
non-blocking or a post-submission improvement. Recommend submitting now and running
the tester round in parallel to attach testimonials to the application.
