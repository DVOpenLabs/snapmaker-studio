# Linux beta plan — L5 and L6 record

**UNRELEASED. Internal only, not linked from README/docs/landing. Not an
announcement.** No public GitHub Release, tag, or change to the stable
v0.9.0 release is authorized by this document.

## What L5 covers

Making the already-proven `.deb` (real, green in branch CI since L3/L4) a
correct, identifiable, checksummed, retrievable prerelease-quality artifact,
plus install/upgrade/purge lifecycle proof. Scope agreed by Fable + Astra
(independent joint plan review):

- `.deb` only. AppImage/RPM/Flatpak explicitly deferred — each reopens a
  CI-infrastructure verification burden (linuxdeploy/FUSE, a Fedora runtime
  matrix, a Flathub manifest) disproportionate to this phase, not a
  fundamental blocker in the sidecar locator (`sidecar.rs`'s `resource_dir()`
  path is reasonably format-agnostic already).
- Package metadata correctness (homepage, category, descriptions, Debian
  section) — landed in `desktop/src-tauri/tauri.linux.conf.json`.
- Artifact naming + provenance (checksum, version+commit in the name) and
  an install → reinstall → upgrade → purge lifecycle check — landed in
  `.github/workflows/linux-support-ci.yml` (see "What landed" below).
- Explicitly NOT L5: release.yml/ci.yml changes, tag/Release publication,
  public docs (`docs/linux-install.md` is L9, gated on a maintainer-approved
  prerelease), format widening, any version-number change.

## Two decisions that need the maintainer, not made here

1. **`bundle.publisher` in the shared `tauri.conf.json`** currently reads
   `"DeadlyVirusIn / Snapmaker Studio"` — stale since the repo moved to
   `DVOpenLabs/snapmaker-studio`. It also feeds the Windows NSIS installer's
   publisher string, so changing it is a Windows-visible change riding on a
   Linux-only phase. **Left untouched for L5** — the `.deb`'s `Maintainer:`
   field carries the same stale string as a documented, known gap. Fix it
   only with the maintainer's explicit yes (or confirm whether Tauri honors
   `publisher` as a `tauri.linux.conf.json`-only override, which would
   avoid touching the shared file at all).
2. **Version-numbering scheme for a Linux prerelease.** The `.deb` today
   ships `Version: 0.9.0` — identical to the stable, EXTERNAL-USER-VERIFIED
   Windows release, with nothing in the number itself signaling Linux is at
   PACKAGE/HEADLESS-RUNTIME tier only. Two real options, because Debian
   version ordering and the shared `tauri.conf.json`/`Cargo.toml` version
   collide:
   - **Option A** — bump the whole project to `0.10.0-beta.N` for the next
     prerelease. The trap: Debian version comparison treats the part after
     the hyphen as the package *revision*, so a later plain `0.10.0` (no
     revision suffix) sorts LOWER than `0.10.0-beta.N`, not higher —
     verified directly with `dpkg --compare-versions`. A real `0.10.0`
     stable release would then look like a *downgrade* from the beta to
     apt, which refuses downgrades without `--allow-downgrades`. This is
     the opposite of the usual semver intuition. Debian's own prerelease
     convention avoids exactly this with `~` (e.g. `0.10.0~beta.1`, which
     correctly sorts BELOW plain `0.10.0`), but Tauri's semver-driven
     `Version:` field does not emit `~`.
   - **Option B** — keep ordinary `0.9.x`/next patch numbers; carry "beta"
     via the GitHub prerelease flag and the package's long description
     text only. Debian-clean upgrade ordering; the version number alone no
     longer signals maturity tier.
   No number has been changed. This decision governs how L6 (permanent
   Linux CI/release integration) wires versioning. **Status: still open as
   of L6's autonomous slice landing** (renamed/retriggered workflow, this
   record) — that slice does not touch versioning or release wiring at
   all, so it does not depend on this decision, but any RELEASE-wiring
   part of L6 (see below) does, and this document's own earlier text said
   to record the decision "before L6 starts." Flagging that explicitly
   rather than silently treating it as satisfied or waived (per Astra's
   L6-planning review) — the maintainer should resolve or explicitly defer
   it before any release-wiring work begins.

## What landed so far (this record's own change log)

- `desktop/src-tauri/tauri.linux.conf.json`: added `homepage`, `category`
  (`GraphicsAndDesign`), `shortDescription`, `longDescription`, and
  `linux.deb.section` (`utils`). Linux-only file, no Windows-shared field
  touched.
- `.github/workflows/linux-support-ci.yml`: new `dpkg-deb -f` assertions for
  Homepage/Section/Description; the install step now also validates the
  installed `.desktop` file (`desktop-file-validate` + an explicit
  non-empty-`Categories=` check, since `desktop-file-validate` itself exits
  0 on an empty `Categories=`) and exercises reinstall → upgrade-in-place
  (a rewritten `.deb` with only its `Version:` bumped, avoiding a second
  full `tauri build`) → purge, asserting every file the package installed
  is actually gone afterward; a checksum+manifest step labels the `.deb`
  with its version and a short commit SHA and generates `SHA256SUMS`,
  uploaded as its own artifact (90-day retention) separate from build logs.
- Also fixed, found during this work (not itself an L5 packaging change):
  the L4 "parent-death stdin lifeline" CI step was printing the sidecar's
  raw handshake line — including its per-launch auth token — into this
  public repo's CI logs; now prints only the parsed port.
- Deferred (not done this pass, needs its own safe follow-up): additional
  icon sizes (32/128/256 alongside the existing 1024) for desktop-launcher
  compatibility. `npx tauri icon` regenerates icons for ALL platforms from
  one source, including `icons/icon.ico` which `tauri.conf.json` (shared)
  uses for the Windows build — running it unreviewed risked a Windows icon
  regression, so this needs its own reviewed step, not a blind run.

## Evidence tiers claimed

PACKAGE VERIFIED / HEADLESS RUNTIME VERIFIED only, same as L4/L5. L6 adds
CI plumbing, not a new evidence tier — a green `pull_request` run is not
new evidence by itself.

## L6 — permanent Linux CI/release integration

Independently planned by Fable + Astra (dispatched in parallel); both
converged on the same shape. L6 is **mostly a maintainer-decision phase**,
not an implementation phase — the technical work is small and already
landed (see below); everything that makes the integration operationally
*permanent* depends on decisions only the maintainer can make.

### Facts that shaped this (verified directly, not taken from either plan on faith)

- `origin/main` is at `a400fe0` ("ecosystem: correct the Snapmaker U1
  Toolkit entry (#9)"). The task branch is 14 commits ahead of it, 1
  commit BEHIND (`git rev-list --left-right --count origin/main...branch`
  = "1  14") — confirmed with a real `git fetch` + `rev-list`, not assumed.
  A straight fast-forward merge is no longer possible; this needs
  reconciliation as part of any future merge decision.
- `ci.yml` was already modified by L1 (added a `windows-latest` leg to the
  backend pytest matrix) — "production workflows untouched" has only ever
  been true for `release.yml` and the full Linux packaging workflow, not
  `ci.yml` in full.
- **`ci.yml` has never once run against this branch.** No PR against
  `main` exists, and `ci.yml` triggers only on `push: [main]` +
  `pull_request` — so the Windows `cargo check --all-targets` in `ci.yml`'s
  `shell` job (which covers the `sidecar.rs` extraction from L1, and
  everything added to it since) has only ever been verified by running it
  locally on the Windows development machine this session (repeatedly,
  clean, zero warnings) — never through GitHub's own CI infrastructure on
  this exact branch. This is real evidence, but a weaker tier than the
  Linux side's real-CI proof.
- `main` has no branch protection configured (`GET /branches/main/protection`
  → 404 at the time this was checked). The only merge gate today is this
  session's own standing git-discipline rule, not a repository setting.
- `release.yml` never itself creates a GitHub Release — it builds a
  Windows artifact on a `v*` tag or manual dispatch; the Release itself is
  created by hand (`gh release create --prerelease`, per
  `docs/RELEASE_CHECKLIST.md` §6). A Linux equivalent would not itself
  cross the release boundary, but editing `release.yml`, or adding any
  `v*`-tag trigger anywhere, is still a production CI/CD pipeline change
  needing sign-off regardless.
- Tauri's config merge (`json_patch::merge`, RFC 7396) means a
  `bundle.publisher` set in `tauri.linux.conf.json` overrides the `.deb`'s
  `Maintainer:` WITHOUT touching the Windows NSIS publisher string — the
  Linux-only-fix option from the L5 open decision above is mechanically
  real, not just theoretical. The exact npm `@tauri-apps/cli` bundler
  version isn't pinned in `Cargo.lock` (it's a Rust-side lockfile), so this
  should be spot-checked with a `dpkg-deb -f ... Maintainer` print in CI
  before being fully relied on, if/when the value is decided.

### What landed (L6 autonomous slice — no maintainer decision needed)

- `.github/workflows/linux-support-ci.yml` renamed to `linux-ci.yml`
  (`git mv`, done before any status-check name could become "required" and
  therefore sticky). Workflow `name:` changed from `Linux support (branch
  CI)` to `Linux CI`. Triggers changed from branch-push-only to
  `push: [main, linux-support/**]` + `pull_request` + `workflow_dispatch`
  (mirrors `ci.yml`'s own trigger shape). The `linux-support/**` push
  trigger is kept for now so the task branch keeps self-verifying; safe to
  drop after merge. Header comment rewritten to describe permanent status,
  the evidence tiers it can and cannot establish, and the corrected L6
  (not L7) phase reference. No step logic changed — same 25 steps that
  went real-CI-green on run 36081506854.
- Two stale self-references to the old filename fixed (`linux-ci.yml`'s
  own MANIFEST-generation echo line; a comment in `sidecar.rs`).
- This record.

### What does NOT proceed without the maintainer (four named decisions)

1. **Merge `linux-support/l1-platform-abstraction` into `main`.** Explicit
   approval required every time per this session's standing rules,
   independent of any Linux-phase authorization — this is not new, but
   worth restating because L6 cannot be operationally "permanent" (running
   on every real PR to `main`) until this happens. Consequences to weigh
   beyond CI: the merge puts the refactored Windows sidecar-lifecycle code
   (`main.rs` → `sidecar.rs`, from L1) onto `main` — the installed-build
   acceptance harness (`tools/acceptance/run.ps1`) should run against a
   `main` build before the next Windows release, as a merge consequence,
   not L6 work itself. It also makes the Linux workflow and
   `tauri.linux.conf.json` visible on the public default branch (not an
   announcement — README stays Windows-only until L9/L10 — but visible).
   Deleting the feature branch afterward is its own separate hard stop
   (branch deletion). Because `main` has diverged (see above), the useful
   pre-merge step is a PR (draft or otherwise) so `ci.yml` and the renamed
   `linux-ci.yml` both run on the real merge candidate — proving Windows
   compile-time compatibility for the first time via GitHub's own CI, not
   just local review. **Not opened yet** — creating even a draft PR is a
   publicly-visible action; the maintainer should say go before one exists.
2. **Release wiring.** Three mechanical options, all needing sign-off
   before any implementation, because touching `release.yml` or adding a
   `v*` tag trigger anywhere is a production pipeline change:
   - **R1** — add `push: tags: ["v*"]` to `linux-ci.yml` itself. Zero new
     files, `release.yml` stays untouched. The workflow already produces
     the exact release-shaped artifact (labeled `.deb` + `SHA256SUMS` +
     `MANIFEST.txt`).
   - **R2** — add a `linux-deb` job to `release.yml`. Touches the
     production Windows release file directly — highest-review option.
   - **R3** — new `release-linux.yml` on the same `v*` trigger. Cleanest
     separation, one more file to maintain.
   Attaching any artifact to an actual GitHub Release stays the same
   manual `gh release create` step regardless of which option (mirrors how
   Windows releases work today) — none of R1/R2/R3 by itself publishes
   anything. What's genuinely blocked on the version-scheme decision (item
   3 below): under Option A (`0.10.0-beta.N`), the release job needs a
   guard step refusing a hyphenated `Version:` from ever being mistaken
   for the "real" release (see the Debian-ordering trap explained above);
   under Option B, no guard is needed, but the MANIFEST/description must
   still carry the "beta" signal some other way. Which guard (or none) to
   add is not something an agent should pick.
3. **Version-numbering scheme** — Option A vs Option B, above. Still open;
   this document's own earlier text asked for it to be resolved before L6
   starts, and L6's release-wiring half genuinely depends on it (the
   autonomous CI-plumbing slice above does not).
4. **`bundle.publisher` value and scope** — now confirmed mechanically
   possible to fix Linux-only (via `tauri.linux.conf.json`) without
   touching the Windows NSIS string, so the remaining question is purely
   the maintainer's: what value, and whether to also fix Windows at the
   same time or leave that for later.

### Adjacent, explicitly NOT part of L6

Enabling branch protection on `main` and/or making `linux-ci.yml` a
required check (a policy choice, and premature before it's run against
real PRs); deleting the feature branch after merge (separate hard stop);
running the Windows acceptance harness against a `main` build (a merge
consequence, listed above for visibility, not L6 work).
