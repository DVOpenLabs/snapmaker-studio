# Snapmaker Studio — Release-Readiness Report (v0.4.0-beta.1 RC)

> **HISTORICAL — describes the v0.4.0-beta.1 RC era; not the current release.** In particular, 'read-only printer access / no printer control' was true then; the current Printer Hub provides monitoring plus user-confirmed controls (never auto-start). Current state: [`../TRUST_STATUS.md`](../TRUST_STATUS.md) · [`../RELEASE_METADATA.md`](../RELEASE_METADATA.md).

## Production-ready (show with confidence)
- **Conversion + validation engine** — STL/3MF → U1-ready project; foreign
  (Bambu/Orca) project repair. Long-standing, heavily tested.
- **Studio Intelligence Report** — synthesis engine + UI; the core demo surface.
- **The Doctors (read-only):** Project (bed-fit/out-of-bounds), Multi-Material,
  First Layer, Printer Health (0–100), Cost, Pricing, Profit. All unit-tested.
- **Community Knowledge (curated MVP)** — per-risk fixes with confidence + sources.
- **Demo Mode** — one-click, no printer/file; deterministic; reviewer-facing.
- **Why Studio?** positioning screen.
- **Brand** — dark-first frozen identity; app/installer icon; splash; sidebar mark.
- **Read-only printer integration** — GET-only Moonraker (telemetry, history,
  capabilities, bed mesh); cannot write or start prints.
- **Engineering quality** — 166 automated tests green; clean build; RC installer
  built, frozen engine smoke-tested (endpoints 200, launch, 0 orphans).

## Beta-quality (works; set expectations)
- **Live printer features** — correct against the U1's Moonraker, but field
  coverage is limited; the demo uses sample data so it never depends on hardware.
- **Cost/Pricing/Profit defaults** — sensible estimates (filament price, power,
  machine wear, labour, markup tiers); user-tunable. Clearly labelled estimates.
- **Expected Improvement** — removed in #92 (it was an uncalibrated percentage); the report now lists the risks found.
- **Community Knowledge** — curated knowledge base (MVP). Phase-2 reviewed
  ingestion from Reddit/GitHub/forums is designed but **not built**.
- **Advanced (power-user) Workspace** — full-featured but denser; not the novice path.

## Do NOT show reviewers
- **Nothing is broken that must be hidden.** The cautions below are about *framing*,
  not concealment:
  - Don't run the **web bundle in a plain browser** — it shows data errors without
    the Tauri runtime. Always demo the **packaged app** (or recorded capture).
  - Don't present the **curated Community Knowledge** as if it were live-scraped —
    it's curated-by-theme today (Phase 2 is roadmap).
  - Don't claim **printer control** — Studio is deliberately read-only; there is no
    print-start/write path to show, by design.
  - Avoid live **connect/disconnect** of a printer on camera (latency/risk) and the
    raw Advanced-mode internals (off-narrative for a 60s reviewer demo).

## Recommendation
**Ready to submit.** The RC is demonstrable end-to-end with no hardware, the unique
value (decide → cost → price, community-backed, local-first) is clear in under a
minute, and the honest beta caveats are limited to live-hardware breadth and the
Community Knowledge ingestion phase — neither blocks the demo or the narrative.
