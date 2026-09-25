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
  `.github/workflows/linux-ci.yml` (renamed from `linux-support-ci.yml` in
  L6 — see "What landed" below).
- Explicitly NOT L5: release.yml/ci.yml changes, tag/Release publication,
  public docs (`docs/linux-install.md` is L9, gated on a maintainer-approved
  prerelease), format widening, any version-number change.

## Two decisions the maintainer made (recorded here, not made by any agent)

1. **`bundle.publisher` — RESOLVED (Option 2), split by platform, decided by
   the maintainer after a real Windows-breaking consequence surfaced in the
   L6 final review gate.**

   **Root cause this decision responds to:** Tauri's NSIS template derives
   the installer's Windows Registry key path directly from `publisher` —
   `Software\<publisher>\<productName>` under `HKCU`. That key is where the
   installer reads an existing install's custom location back on an
   upgrade, and where the default "uninstall before installing" flow finds
   the previous version's uninstaller. Verified directly (real read-only
   registry query, this session, not just reading the NSIS template
   source): `HKCU\Software\DeadlyVirusIn / Snapmaker Studio\Snapmaker
   Studio` genuinely exists and holds a real install path;
   `HKCU\Software\DVOpenLabs` does not. A Windows installer built with
   `publisher: "DVOpenLabs"` would not find any existing v0.9.0 install's
   registry entry — a custom install location would not be restored, and
   the default upgrade-over-existing-install flow was very likely to break
   for every existing Windows user.

   **Decision:** preserving the existing upgrade contract for current
   Windows users takes priority over immediately changing the installer's
   internal identity string. Split by platform via Tauri's config merge
   (RFC 7396 JSON Merge Patch — `tauri.linux.conf.json` overrides the
   shared `bundle.*` keys it sets):
   - `desktop/src-tauri/tauri.conf.json` (shared): `bundle.publisher`
     restored to the EXACT legacy value, `"DeadlyVirusIn / Snapmaker
     Studio"` — byte-for-byte what v0.9.0 shipped with, not normalized or
     trimmed. This is the value the Windows NSIS installer actually uses
     (Linux's `tauri.linux.conf.json` override, below, applies on top of
     it, so this is the value ANY platform gets unless it overrides).
   - `desktop/src-tauri/tauri.linux.conf.json` (Linux-only): new
     `bundle.publisher: "DVOpenLabs"` override. The `.deb`'s `Maintainer:`
     field is `DVOpenLabs`, asserted as a hard check in `linux-ci.yml`
     (unchanged by this decision — Linux was always meant to get the
     current name, and still does).

   **🔒 DO NOT casually rename `tauri.conf.json`'s `bundle.publisher` again.**
   Current project branding is `DVOpenLabs` — this value is an
   intentional, temporary EXCEPTION for Windows installer/registry
   compatibility, not a claim about current branding. It must not be
   presented as current branding anywhere user-facing (it isn't — Linux,
   README, the app's own update-check URL, and everywhere else already say
   `DVOpenLabs`; this one field in this one file is the sole holdout, and
   it exists only because real existing Windows installs depend on it).
   Migrating it requires a proven, tested Windows upgrade migration (see
   the follow-up item below) — not a one-line config edit.

   A repo-wide sweep for `DeadlyVirusIn`/`github.com/DeadlyVirusIn` was
   done: live surfaces (README, landing page, the app's own update-check
   URL in `main.rs`, issue templates, etc.) updated to `DVOpenLabs`;
   genuinely historical records (per-release evidence JSON, dated handoff
   docs, Innovation Fund submission records — submitted under the old
   name, so rewriting them would falsify what was actually submitted) and
   `@DeadlyVirusIn` (Kunal's personal GitHub handle, a different identity
   than the org rename) left untouched on purpose. This Windows
   compatibility exception in `tauri.conf.json` is now a third allowed
   category alongside those two.

   **Follow-up debt, explicitly NOT solved by this decision or PR #20:**
   "Windows installer publisher migration: DeadlyVirusIn → DVOpenLabs" —
   a future, separately-scoped and separately-tested Windows release. Must
   prove, at minimum: upgrade from a real v0.9.0 default install path;
   upgrade from a real v0.9.0 CUSTOM install path; existing installation
   correctly discovered; previous version correctly removed/upgraded;
   install location preserved where expected; Add/Remove Programs state
   stays sane; uninstall after migration works; no duplicate installations;
   no orphaned legacy registry/install records; a fresh install (no prior
   version present) uses the `DVOpenLabs` identity correctly. Investigate a
   custom NSIS migration script (or another supported mechanism) — do not
   rely on a release-note "uninstall the old version manually" instruction
   unless an engineered migration is proven impossible.
2. **Version-numbering scheme for a Linux prerelease — RESOLVED, decided by
   the maintainer.** Public SemVer/Git/GitHub tag: `v0.10.0-beta.N` (the
   next MINOR version, not a `0.9.x` patch — the maintainer's own reasoning:
   Linux support is substantial enough to earn it). Debian `.deb` `Version:`
   field: independently `0.10.0~beta.N` (Option A's `~`-based approach,
   confirmed the only Debian-correct choice — `dpkg --compare-versions`
   proves `0.10.0~beta.1 lt 0.10.0` while a plain hyphen (`0.10.0-beta.1`)
   does NOT sort below `0.10.0`, which would make a real stable release
   look like a downgrade from the beta). Tauri's bundler has no config-only
   way to emit `~` (verified against the pinned tauri-utils 2.9.3 source:
   its version deserializer parses with `semver::Version::from_str`, which
   rejects `~` outright) — implemented instead as a dedicated,
   independently-tested packaging-boundary script,
   `desktop/scripts/debianize-version.sh`, run after `tauri build --bundles
   deb` and before the artifact is used anywhere. No version number has
   actually been changed anywhere in the repo — this is the mechanism only,
   proven against real fixtures and a real `dpkg --compare-versions`
   ordering check, ready for whenever the maintainer reaches the actual
   beta-release gate.

## What landed so far (this record's own change log)

- `desktop/src-tauri/tauri.linux.conf.json`: added `homepage`, `category`
  (`GraphicsAndDesign`), `shortDescription`, `longDescription`, and
  `linux.deb.section` (`utils`). Linux-only file, no Windows-shared field
  touched.
- `.github/workflows/linux-ci.yml` (was `linux-support-ci.yml` before L6's
  rename): new `dpkg-deb -f` assertions for
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

- `origin/main` diverged after this branch started (a real external PR #9
  by a community contributor, correcting `backend/snapstudio_core/data/
  ecosystem.json`) — reconciled via a real `git merge origin/main`
  (commit `ea1429f`), zero conflicts (the branch never touched that file).
  Confirmed via `git fetch` + `git rev-list --left-right --count`, not
  assumed, both before and after the merge.
- `ci.yml` was already modified by L1 (added a `windows-latest` leg to the
  backend pytest matrix) — "production workflows untouched" has only ever
  been true for `release.yml` and the full Linux packaging workflow, not
  `ci.yml` in full.
- **`ci.yml` now HAS run against this branch, for the first time, via
  PR #20** — opened once the branch was reconciled with `main`, per the
  maintainer's explicit authorization. Both required gates green on that
  PR: `ci.yml` (Windows backend pytest, `cargo check --all-targets`,
  frontend) and `linux-ci.yml`. This is the first time the `sidecar.rs`
  extraction (and everything added to it since) has compiled through
  GitHub's own CI infrastructure, not just local `cargo check` on the dev
  machine.
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
  `Maintainer:` WITHOUT touching the Windows NSIS publisher string — this
  is exactly the mechanism decision 4 above now uses, confirmed not just
  theoretical: `linux-ci.yml`'s `dpkg-deb -f ... Maintainer` assertion
  passes for real on every CI run, proving the Linux override actually
  takes effect while the shared file's value (verified byte-identical to
  the real v0.9.0 release) is what Windows gets.

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

### Status of the four decisions (maintainer decided all four)

1. **Merge `linux-support/l1-platform-abstraction` into `main`.** DECIDED —
   the maintainer explicitly authorized both opening the PR and merging it,
   once branch reconciliation + both CI checks + a Boss Orchestrator review
   of the complete diff are satisfied. Reconciliation done (`ea1429f`, zero
   conflicts). PR #20 opened. Both `ci.yml` and `linux-ci.yml` green on it.
   Opus + Sol reviewed the complete accumulated diff (paired, per the
   pre-merge gate) — Sol: APPROVE-WITH-NOTES, zero CRITICAL/HIGH; Opus
   found one genuine HIGH (the Windows publisher/registry consequence,
   resolved below via Option 2) that blocked the merge until resolved.
   Separate hard stops, unaffected by this decision: deleting the feature
   branch after merge; enabling branch protection on `main`.
2. **Release wiring — DECIDED: R3.** New, separate `release-linux.yml`,
   `workflow_dispatch` ONLY (deliberately no `push: tags: [...]` — that
   stays a future, separately-authorized step). Cannot create a Release,
   cannot create/push a tag, cannot mark anything stable — verified
   directly by reading the file, not just its own commit message. Mirrors
   `linux-ci.yml`'s proven build pipeline, then translates the version
   (`debianize-version.sh` — a no-op today, since the project version has
   no prerelease suffix yet), runs a real install + `/health` smoke-test,
   checksums, manifests, and uploads. `release.yml` (Windows) is completely
   untouched by this decision.
3. **Version-numbering scheme — DECIDED**, see the resolved item 2 above
   (public `v0.10.0-beta.N`, Debian `0.10.0~beta.N`, mechanism only,
   version not yet bumped anywhere).
4. **`bundle.publisher` — DECIDED (Option 2), split by platform** — see the
   full detail above. Windows keeps the exact legacy value for real
   installer/registry compatibility with existing v0.9.0 users; Linux gets
   `DVOpenLabs` via a `tauri.linux.conf.json` override. A separate,
   tested Windows publisher migration is tracked as explicit follow-up
   debt, not solved here.

### Resolved: the HIGH finding from the final review gate

Opus's review of the complete PR diff (the final "Boss Orchestrator
review" gate the merge decision requires) found one real HIGH, reproduced
directly on this machine (a read-only registry query, not just reading
Tauri's NSIS template source): renaming `bundle.publisher` would have
changed the Windows installer's `HKCU\Software\<publisher>\<productName>`
registry key path, which the NSIS installer uses to find an existing
install's custom location and to run its previous uninstaller during an
upgrade. Resolved via the maintainer's Option 2 decision above — the
Windows value is unchanged from v0.9.0, so this consequence no longer
applies. The follow-up Windows migration debt item exists specifically so
this doesn't quietly become permanent.

### Adjacent, explicitly NOT part of L6

Enabling branch protection on `main` and/or making `linux-ci.yml` a
required check (a policy choice, and premature before it's run against
real PRs); deleting the feature branch after merge (separate hard stop);
running the Windows acceptance harness against a `main` build (a merge
consequence, listed above for visibility, not L6 work).
