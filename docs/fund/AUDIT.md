# Snapmaker Studio — Application Audit

> **HISTORICAL — describes the v0.4.0-beta.1 RC era; not the current release.** In particular, 'read-only printer access / no printer control' was true then; the current Printer Hub provides monitoring plus user-confirmed controls (never auto-start). Current state: [`../TRUST_STATUS.md`](../TRUST_STATUS.md) · [`../RELEASE_METADATA.md`](../RELEASE_METADATA.md).

Scope: full app sweep before fund submission. Method: code inspection of all
routes, grep for placeholders/stubs, automated tests, production build, and the
v0.4.0-beta.1 RC smoke test (frozen engine + launch).

## Findings

### Broken pages — none
All 10 routes present and render: Dashboard, Projects, Batch, Printers, Settings,
Why Studio, Workspace (DesignInsights in Simple / LiveWorkspace in Advanced),
NotFound. `tsc --noEmit` clean; production build clean.

### Placeholder data — none hidden
No TODO/FIXME/lorem/mock/stub in shipping code. The only `placeholder=` hits are
legitimate input hints ("U1.local", "Search projects…"). **Demo Mode** uses
representative sample data, but it is *explicitly labelled* — `is_demo` flag + a
"Demo" badge in the UI — not disguised as live data. One dead helper
(`toast.notImplemented`) has **zero callers** (cosmetic; safe to remove later).

### Empty states — handled
Projects (`EmptyState` + error/empty branches), Batch (`EmptyState` + error),
Printers (error branch; lands on live status rather than a bare input). Dashboard
degrades gracefully when the library is unavailable.

### Missing branding — none material
Dark-first frozen identity applied across splash, sidebar mark, app/installer
icon, Dashboard hero (ribbons→core→cube + tagline), Doctors grid, workflow colours,
Why-Studio. Light theme exists as a secondary variant (also on-brand accent).

### Runtime errors — none in the real app
Backend: 166 automated tests green; every endpoint returns 200 (incl. demo_report,
community_knowledge, intelligence_report, convert) on the frozen RC sidecar.
Frontend: clean build. **Note:** running the web bundle in a plain browser shows
data errors ("Cannot read … invoke") because the Tauri runtime/sidecar is absent —
this is a *preview-only artifact*, not a bug; the packaged app was verified to
launch, spawn its sidecar, and leave 0 orphans on close.

### Demo flow — intact
Dashboard → "See a 10-second demo" → Studio Intelligence Report (metrics,
biggest risk, next action, why-not-Orca, per-risk community
fixes) → "Why Studio?" CTA. Runs with no printer and no model file.

## Issues to address (non-blocking)
| Severity | Item | Action |
|---|---|---|
| Low | Dead `toast.notImplemented` helper | Remove in cleanup |
| Low (env) | Per-file Report/Doctor cards can't be screenshotted headless (need Tauri runtime) | Capture live in the recorded demo |
| Info | Live printer features need a reachable U1 | Demo uses sample data; live path verified by smoke test |

**Verdict: no blockers for the fund demo or submission.**
