# Linux beta plan — L5 through L11 record

**Internal-only engineering record, not linked from README/docs/landing —
not the public announcement of anything.** L1 through L10 covered
unreleased preparation; L11 records the actual v1.0.0 release, once it
happened, under the maintainer's own explicit release authorization
(recorded in this file's L11 section) — this document does not itself
authorize anything beyond what's already in that section.

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

## L7 — automated Linux acceptance + a real production bug fix

Merged to `main` via PR #21, merge commit `8a621c0`. Two independent
things landed together because the second was found while planning the
first:

- **F1 bug fix** (`desktop/src-tauri/src/main.rs`): closing the main
  window did not exit Snapmaker Studio, on Windows AND Linux, since
  beta.13 (`3f01ea6`, when the Model Browser started being pre-built
  hidden at startup). Root cause, verified against pinned Tauri/tao
  source: `RunEvent::Exit` only fires when the window map becomes empty;
  the Model Browser's own `CloseRequested` handler always calls
  `prevent_close()`+`hide()` instead of destroying it, so that map is
  never empty. Fixed by handling
  `RunEvent::WindowEvent { label: "main", event: WindowEvent::Destroyed }`
  directly and calling `app_handle.exit(0)`. Verified for real on Windows
  (a fresh `npm run release:windows` build, a real `CloseMainWindow()`
  probe with proper parent-child PID tracking to avoid conflating with
  another already-running instance on the same machine) and on Linux (CI,
  many times over — see below).
- **`tools/acceptance/linux/run.sh`** (new): the Linux counterpart to
  `tools/acceptance/run.ps1` — installs the real `.deb`, launches the real
  installed binary as a fresh unprivileged test account under
  Xvfb+openbox, drives a real window-manager close (not a kill), and
  checks the graceful `/shutdown` path was actually taken. Went through a
  BLOCK-then-fix-then-reapproved review cycle (Opus+Sol, twice) before
  merge — process/account-ownership hardening (unique per-run test
  account, exact uid+argv0 process matching after two other matching
  approaches failed empirically in real CI) is the direct ancestor of the
  L8 harness this same file grew into.

Evidence: `linux-ci.yml` run `36141769226` and prior, all green; 12/12
harness checks passing pre-L8.

## L8 — clean-environment validation

Branch `linux-support/l8-clean-environment`, based on `main` at `8a621c0`.
Plan co-authored by Fable + Astra (parallel dispatch, reconciled by the
lead — Fable's plan adopted as primary: grounded in a real WSL experiment
reproducing the uid-recycling hazard, real noble-archive package lookups
for 24.04 feasibility, and file:line citations against the actual L4-L7
code; Astra's independent corrections folded in, notably that
`linux-ci.yml`'s existing signal-lifecycle steps do NOT exercise the
graceful `RunEvent::Exit` path — only L7's harness does).

### What shipped

- **`tools/acceptance/linux/run.sh` grew from 12 to 35 checks**, all
  still real-CI-green: the pre-existing 3MF GUI flow, plus (new) an STL
  launch, SIGTERM/SIGKILL as the actual non-root test user (every prior
  signal-lifecycle proof in this project ran as root), 3 repeated
  launch/close cycles with a zero-accumulated-orphans sweep,
  sidecar-crash-first survival, a headless API lane that drives the
  sidecar binary directly via its real stdin lifeline
  (`SNAPSTUDIO_PARENT_LIFELINE=stdin-v1`) and exercises `/doctor` (3MF,
  STL, and the real Orca-painted fixture), `/color_plan`, `/mm_doctor`,
  `/convert` (Prepare — proves a new output file, original byte-identical),
  `/fidelity`, `/report`, 3 XDG_DATA_HOME configurations (unset/
  absolute-custom/relative-ignored), and a unicode+spaces launch path
  asserted byte-exact in the library index.
- **`tools/acceptance/linux/package-lifecycle.sh`** (new): the
  install/reinstall/upgrade/purge sequence extracted out of
  `linux-ci.yml`'s inline YAML into its own script, behaviour-identical,
  so the new clean-image job below can run the exact same real lifecycle
  test without the YAML duplicating and silently drifting.
- **`clean-env-validate`** (new job in `linux-ci.yml`): a
  `ubuntu:22.04`/`ubuntu:24.04` matrix, `needs: linux-build-and-package`,
  each leg a genuinely bare container (no `actions/checkout` — only the
  built `.deb` and a small "acceptance kit" artifact of scripts+fixtures
  the build job packages separately). Sequence per leg: assert no
  python/node/rust present -> install ONLY the `.deb` -> assert still none
  (with one documented, evidence-backed exception, below) -> `ldd` sweep
  across every installed ELF for missing shared libraries -> full package
  lifecycle -> install test tooling (kept in its own separate step so it
  never contaminates the dependency-leak assertion above) -> the full
  35-check `run.sh`. **Both legs fully green as of commit `0c3ea25`,
  including the whole 35/35 harness on each** — the first genuinely clean-
  image confirmation this project has ever had.
- **The uid-scoped-pkill limitation from L7 was investigated, not just
  re-documented**, as required: a real experiment (root, WSL Ubuntu
  24.04) confirmed `userdel -f` on an account with a live process succeeds
  and its uid is immediately available for reuse by the next `useradd` —
  and that accountsservice (what GNOME Settings → Users → Remove User
  calls) always passes `-f`, so this is reachable on a real single-user
  desktop, not purely a multi-tenant-server concern. Fixed (not merely
  re-bounded) by capturing the harness's own `/proc` start-time before it
  creates anything and scoping the safety-net kill to only processes that
  started after — a pre-existing orphan under a recycled uid is now left
  alone and reported, never killed.

### Real findings this phase surfaced (evidence, not assumptions)

- **python3 is present after installing only the `.deb`, on BOTH 22.04
  and 24.04.** The first explanation tried (`libwebkit2gtk-4.1-0` depends
  on `xdg-desktop-portal-gtk`, which itself depends on `python3-gi`) was
  WRONG and has since been corrected: a delta review independently checked
  it against a real Ubuntu apt database (`apt-cache depends`) and found
  `xdg-desktop-portal-gtk` declares no python dependency at all — the
  earlier claim was inferred from apt install-log ordering, not a verified
  dependency edge. The REAL chain, verified the same way (`apt-cache
  depends`/`rdepends` against a real Ubuntu 24.04 install, not inferred):
  `libwebkit2gtk-4.1-0` **Recommends** `xdg-desktop-portal-gtk` (a
  Recommends, not a Depends — this only matters because apt installs
  Recommends by default), and separately, `systemd` — pulled in by the
  desktop dependency closure — **Recommends** `networkd-dispatcher`, which
  directly **Depends** on `python3-gi`, `python3-dbus`, and `python3`
  itself. `xdg-desktop-portal-gtk` was a red herring, co-installed in the
  same apt transaction but not the actual cause. This project's own `.deb`
  declares only `libwebkit2gtk-4.1-0, libgtk-3-0` as `Depends` — there is
  no packaging change that removes this short of dropping the GTK webview
  entirely; it is an OS dependency-resolution fact, not a defect in this
  package's own metadata. Never caught before L8 because the existing
  build job's container already has Python installed for its own build
  needs, so "python3 became newly available" was never observable there.
  The item-30 check now verifies presence of `networkd-dispatcher`
  specifically (the confirmed direct cause) rather than
  `xdg-desktop-portal-gtk`, and still hard-fails on node/npm/cargo/rustc,
  or on python3 appearing without that specific, verified cause.
- **A whole family of D-Bus-activated session daemons legitimately
  outlives every app instance**: the main session bus
  (`dbus-launch`/`dbus-daemon`), plus on a genuinely clean image's fuller
  dependency closure, the AT-SPI accessibility bus
  (`at-spi-bus-launcher`, a second `dbus-daemon` instance,
  `at-spi2-registryd`) and the desktop-portal stack (`xdg-desktop-portal`,
  `xdg-desktop-portal-gtk`, `xdg-permission-store`). All confirmed
  `ppid=1` (reparented after their D-Bus-activating process exited), all
  standard, session-scoped, activate-once infrastructure — none of it
  started or owned by any single app launch this harness makes, exactly
  like Xvfb/openbox aren't expected to disappear either. The harness's
  "zero orphans after repeated cycles" check filters this specific, named
  family (matched by `argv[0]`), capped at each daemon's expected
  concurrent count (1 for most; 2 for `dbus-daemon`, which legitimately
  serves both the main session bus and a separate AT-SPI accessibility
  bus at once) — not an unbounded name-based allowlist. A regression that
  leaks an ADDITIONAL instance of the same daemon beyond its expected
  count still counts as a real leftover. This landed after two failed
  attempts at a timing-based "baseline snapshot" approach (before the
  cycles, then after cycle 1) — real CI proved activation timing for these
  daemons is genuinely nondeterministic across runs, so a cap on
  concurrent count per daemon, which doesn't depend on timing at all, is
  what actually holds.

### Evidence tiers earned

- **BUILD VERIFIED / PACKAGE VERIFIED / HEADLESS RUNTIME VERIFIED**:
  extended to genuinely clean `ubuntu:22.04` AND `ubuntu:24.04`, not just
  the build container (which already had a full dev toolchain).
- **DESKTOP WORKFLOW VERIFIED**: extended to both clean images — a real
  Xvfb display, a real window manager, a real window close, exercised
  through the full 35-check harness, not simulated.
- **REAL U1 VERIFIED**: not touched (no printer in CI). **EXTERNAL USER
  VERIFIED**: not touched (no external human tester yet) — stays false
  until a real report arrives from outside this project. L10 prepared the
  reporting path for that; it does not, and structurally cannot, produce
  the report itself, since no Linux package is publicly downloadable yet
  (see L10's own section below). This tier is not a gate on v1.0.0
  shipping Linux — the maintainer's v1.0.0 authorization already directs
  one Release with both platforms, independent of this tier.

### Not yet done (tracked, not silently dropped)

- A REAL cross-version upgrade test (installing an actual prior release,
  then upgrading) is still not possible — no Linux beta has shipped yet,
  so there is no prior artifact to upgrade FROM. The existing upgrade
  check remains a synthetic, honestly-labelled proof (same version,
  bumped control field only).
- The GUI-driven Prepare/Fidelity/painted stretch (clicking through the
  actual UI rather than the headless API lane) was deliberately not
  attempted — Astra's own top risk assessment flagged coordinate-clicking
  as brittle across OS/font-rendering differences, and the headless API
  lane already proves the same backend code paths with real fixtures and
  real expected values.
- Real Ubuntu Desktop VM replay (as opposed to a CI container) — planned
  as a bounded claim, not yet executed; the current claim is "clean
  Ubuntu userspace under Xvfb," which this phase delivers honestly.

## What L9 covers

Public documentation for the Linux package — written and merged ahead of any
public Linux release, at its final path, but **not yet linked from README.md**
(same pattern L5-L8 used for this file). Planned jointly by Fable (Astra's
Codex dispatch failed on a Codex-side auth error — expired/invalid service
API key, `401 Unauthorized` — before producing a plan, so this phase's plan
stage is Fable alone, disclosed, per the standing orchestration failover
rule); every file:line claim in Fable's plan was independently re-verified
against the live repo and a real green CI log before anything was written.

### What shipped

- **`docs/linux-install.md`** (new, public path, unlinked from README): a
  status block stating plainly that no Linux package has shipped in any
  GitHub Release yet, so a reader who finds this page early is not misled;
  what the `.deb` needs (`libwebkit2gtk-4.1-0`, `libgtk-3-0` only — verified
  against the real `.deb`'s own control file in CI, not guessed); a
  Tested-on table naming exactly what was verified (Ubuntu 22.04/24.04,
  clean containers, real apt install, Xvfb+Openbox, 35/35) and, just as
  important, what was **not** yet verified (a person clicking through the
  live UI rather than the harness's automated checks — 12 of the 35 call
  the local API directly, not the UI — real desktop session, real
  hardware/VM, other distros, a real upgrade, Printer Hub against a real
  U1, any external user); download/verify/install/upgrade/uninstall steps
  written against the real package name (`snapmaker-studio`) and real
  binary path (`/usr/bin/snapmaker-studio-desktop`); the real
  data-directory behaviour in `backend/snapstudio_core/paths.py`
  (`$XDG_DATA_HOME/SnapmakerStudio` or `~/.local/share/SnapmakerStudio`,
  mode `0700`, `SNAPSTUDIO_DATA_DIR` override) — with an explicit note that
  this covers project data only, not UI preferences (theme, printer
  address, filament price, provider settings), which `desktop/src/store/*.ts`
  keeps in the embedded browser view's own storage, unaffected by that
  directory or its override; a Troubleshooting section that explains the
  D-Bus/AT-SPI/portal daemon family from L8 in user terms (normal, not a
  leak) instead of re-litigating it. Commands reference the downloaded
  filename generically (`snapmaker-studio_<version>_amd64_<short-hash>.deb`,
  matching `release-linux.yml`'s checksum/label step — the raw Tauri build
  output has a different name entirely, `Snapmaker Studio_<version>_amd64.deb`
  with a literal space, which is never what a user downloads) rather than
  hard-coding one guessed pattern, since the real tag-triggered Linux
  release workflow does not exist yet and the exact final name is not yet
  certain.
- **`backend/tests/test_public_claims.py`**: added `docs/linux-install.md`
  to the tooling-name guard's doc list (it previously only covered
  `RELEASE_NOTES.md` and `windows-install.md`) — otherwise nothing enforced
  the no-internal-tooling-names rule on the new page.
- No changes to `README.md`. See "Why README stays untouched in L9" below.

### A real functional gap this phase found and documented honestly (not fixed here)

**Snapmaker Orca auto-detection is not implemented on Linux.**
`desktop/src-tauri/src/main.rs`: `orca_candidates()` (line 158) and
`tool_candidates()` (line 225) are both `#[cfg(not(windows))] -> Vec::new()`.
`OrcaHandoff.tsx` renders `orca === undefined` (checking) then, since the
candidate list is always empty, `orca` resolves falsy and the button
permanently reads **"Install Snapmaker Orca"** — even on a machine that
already has Orca installed — and the "Open in Snapmaker Orca" / ecosystem
"Open with" paths never appear on Linux. `docs/linux-install.md` documents
this plainly in its own "Handing off to Snapmaker Orca" section and under
Known limitations, rather than describing the Windows behaviour as if it
were universal. **Recommended as an L10 candidate** — it is the first thing
a real Linux user will notice after their first Prepare, and closing it
(populating real Linux install-location candidates for Orca and the other
ecosystem tools) is a contained, well-scoped fix.

### A pre-existing stale doc this phase found but did not touch (out of L9 scope)

`docs/windows-install.md` still names `Snapmaker.Studio_0.4.0-beta.20_x64-setup.exe`
and its old size/hash, while `README.md` (line 90) links to it as the
canonical Windows install guide — and nothing in the test suite catches this,
because `test_evidence_consistency.py`'s `CURRENT_DOCS`/`test_release_docs.py`
checks do not cover `docs/windows-install.md`. Not an L9 file; recommended
for the v1.0.0 release PR, which touches Windows release metadata anyway.

### Why README stays untouched in L9

Three independent reasons, not one judgment call:

1. **A live CI guard would fail today.** `backend/tests/test_evidence_consistency.py`'s
   `test_current_documents_point_at_the_current_release` (`release_offenders`)
   runs against `README.md` and fails any release-tag link that isn't the
   *current* release. The live current release is v0.9.0; a Linux
   download line pointing at `releases/tag/v1.0.0` (which does not exist
   yet) is exactly the failure this guard exists to catch.
2. **It is the named defect class the guard was built for.** v0.7.0 shipped
   with the README's own top call-to-action pointing at the *previous*
   release for an entire version — the guard exists because of that
   incident, not hypothetically.
3. **"Linux coming" pre-announcement copy was never authorized.** This
   file's own header has said, since L5, "**UNRELEASED... Not an
   announcement**" — and the maintainer's L9 authorization describes README
   changes ("Windows 10/11 ✅, Linux x86_64 .deb ✅") in the same breath as
   the v1.0.0 release itself, not as a separate pre-announcement step.

The full README Download-section spec is staged here, verbatim, so the
v1.0.0 release PR is a paste rather than fresh drafting:

> **Windows 10/11 (x64)** ✅ · **Linux x86_64 (.deb)** ✅ · **macOS** not
> supported.
>
> Download links: Windows installer and Linux `.deb`, both from the same
> v1.0.0 release. Sizes/hashes for both come from
> `docs/RELEASE_METADATA.md`. **Do not rename the existing `Version` /
> `Installer` / `Size (bytes)` / `SHA256` rows** — `test_release_docs.py`'s
> `metadata` fixture (`_metadata_current()`, lines 42-62) requires those
> exact bare keys (lowercased) to exist and reads them as the *Windows*
> installer's values throughout the rest of that test file. Add the Linux
> values as NEW, separately-named rows instead — e.g. `Linux installer` /
> `Linux size (bytes)` / `Linux SHA256` — since `_metadata_current()` keys
> its dict by lowercased field name and a second row reusing an existing
> name (e.g. a second bare `SHA256` row) would silently overwrite the first
> one it parses, which is the real hazard here — not the field names
> themselves, which must NOT change.
>
> Linux install instructions link to `docs/linux-install.md` (this phase's
> new file, which stops being "unlinked from README" the moment this text
> lands for real).

### Evidence tiers earned this phase

No new runtime evidence — L9 is documentation only. It correctly *describes*
the DESKTOP WORKFLOW VERIFIED tier L8 already earned, and is explicit
everywhere that REAL U1 VERIFIED and EXTERNAL USER VERIFIED remain false.

### Review round (Codex lane unavailable — Opus alone, disclosed)

Three independent Codex dispatches this phase (Astra for planning, Sol then
Terra for review) all failed identically: a WebSocket disconnect, fallback
to HTTPS, then `401 Unauthorized: Incorrect API key provided` against the
same service-account key, across three different model routes
(`gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`). This is a session-wide
Codex credential outage, not a per-dispatch flake or a finding about this
diff — logged to the orchestration ledger for each of the three failed
sessions. Per the standing failover rule, this makes the review-lane pairing
requirement (Opus + one of Sol/Terra) genuinely unsatisfiable this session;
proceeding with Opus alone is recorded here explicitly as an **incomplete
pair**, not a completed paired review, per the routing policy's own
labelling requirement. Nothing in this phase required destructive or
irreversible action, which weighed into proceeding rather than blocking on
a credential fix outside this session's authority (rotating the Codex
service-account API key).

Opus's review (verified against real CI run `36199287491` on `main`, plus
direct source reads) returned **NOT SAFE TO SHIP as written**: 1 HIGH, 5
MEDIUM, 7 LOW. All were fixed in the same commit round:

- **H1 (fixed)**: the doc's install/verify/upgrade commands hard-coded the
  raw Tauri build artifact's name (`Snapmaker Studio_<version>_amd64.deb`,
  literal space) — not what a user would ever actually download. Fixed to
  reference the filename generically, instruct copying it exactly from the
  Releases page, and note the real labelling convention
  (`release-linux.yml`'s `snapmaker-studio_<version>_amd64_<short-hash>.deb`)
  instead of asserting one fixed name before the real release workflow
  exists.
- **M1 (fixed)**: "driven through the real UI — 35/35" overclaimed; 12 of
  the 35 harness checks call the local API directly, not the UI. Reworded
  to describe both kinds of checks accurately, and added "a person clicking
  through Doctor/Prepare/Orca-handoff in the live UI" to the not-yet-tested
  list.
- **M2 (fixed)**: "delete the XDG data directory to remove your settings"
  was false — UI preferences live in the embedded browser view's own
  storage (`desktop/src/store/*.ts`'s `localStorage` usage), unaffected by
  `SNAPSTUDIO_DATA_DIR` or the XDG directory. Fixed to state this honestly
  without guessing the unverified on-disk path.
- **M3 (fixed)**: "the next release will ship" was forward-looking
  pre-announcement language, the exact thing this file's own header has
  disclaimed since L5. Reworded to backward-looking, verified-in-CI framing.
- **M4 (fixed)**: the public doc linked to this internal file, which names
  Fable/Astra/Opus/Sol/Codex and a Codex auth failure — routing a public
  reader straight around the tooling-name guard this same PR extends. Link
  removed from `docs/linux-install.md`.
- **M5 (fixed)**: the staged README text above originally said to rename
  the existing `SHA256` (etc.) rows for Windows vs. Linux, which would have
  broken `test_release_docs.py`'s `metadata` fixture (it requires those
  exact bare keys). Corrected to: keep the existing rows untouched, add new
  distinctly-named Linux rows.
- **LOW fixes applied**: `apt autoremove` mentioned after purge; D-Bus/portal
  troubleshooting wording tightened; `docs/linux-install.md` added to
  `test_public_claims.py`'s print-guarantee guard list (`_PUBLIC_DOCS`) in
  addition to the tooling-name guard.
- **LOW deliberately not applied**: adding `docs/linux-install.md` to
  `test_evidence_consistency.py`'s `CURRENT_DOCS` n/n-drift guard was
  considered and deferred — that guard's `SUBJECTS` matching is tuned for
  README/judge-doc prose patterns, and forcing an install guide through it
  risks unrelated false failures for no real protection the M1 rewrite and
  the print-guarantee guard don't already provide.

Verified after fixes: `test_public_claims.py` + `test_evidence_consistency.py`
(57 passed); those two plus `test_release_docs.py` (72 passed); full backend
suite (1830 passed, 7 skipped).

## What L10 covers

External Linux beta readiness — making sure a real outside tester has a
working path to report back, without requiring that anyone has actually
done so yet. **EXTERNAL USER VERIFIED stays false**; nothing in this phase
changes that, and nothing here is gated on it changing.

### What shipped

- **`.github/ISSUE_TEMPLATE/bug_report.md`**: the "Windows version" field
  was the only OS-specific assumption in either issue template — it asked
  every reporter for a Windows version even though nothing else in the
  template assumed Windows. Changed to "OS and version", with a
  Linux-specific prompt to also say how Studio was installed (the official
  `.deb`, or something else) — useful because a report from a hand-built
  or third-party package is a different kind of bug than one against the
  real release artifact.
- **`.github/ISSUE_TEMPLATE/studio-got-this-wrong.yml`**: this is the
  primary report link `docs/linux-install.md`'s Troubleshooting section
  actually points to, and it had no OS field at all — a real gap Opus's
  review caught (it was OS-neutral only in the sense of asking about no OS,
  not in genuinely covering Linux). The known Orca-auto-detection gap
  (L9's finding) will plausibly produce "Studio got this wrong"-shaped
  reports from Linux users that are actually the known missing-detection
  behaviour, not a new defect — without an OS field there would be no way
  to tell those apart from a real cross-platform analysis bug. Added an
  optional "OS and version" field, matching bug_report.md's wording.
- `docs/linux-install.md` (L9) already gives Linux-specific Known
  Limitations and Troubleshooting sections and an explicit SHA256
  verification step. Its download-filename guidance is a pattern
  (`snapmaker-studio_<version>_amd64_<short-hash>.deb`) rather than a
  concrete example, and `docs/RELEASE_METADATA.md` has no Linux row yet —
  both correct only because no Linux release exists; "understandable
  filename" and "easy checksum verification" are satisfied as *documented
  process*, not yet as a real example a tester can point at, which the
  v1.0.0 release closes.

### What was deliberately NOT done this phase

**No outreach was posted anywhere** (Reddit, the Snapmaker forum, or
otherwise). Two independent reasons, not a missed step:

1. There is still nothing a reader could download — no Linux `.deb` has
   been published in any GitHub Release (same fact `docs/linux-install.md`
   itself leads with). Posting "try the Linux beta" with no working link is
   the exact kind of premature announcement `docs/internal/LINUX_BETA_PLAN.md`
   has disclaimed since L5.
2. Posting to an external, public service is visible to others and not
   easily reversible — outside what a documentation/readiness phase should
   do on its own initiative. `docs/innovation-fund/BETA_TEST_PLAN.md`
   already did this analysis for the Windows beta (channel-by-channel fit
   assessment, the Snapmaker forum ranked best) and its reasoning — no
   asking for stars/votes, lead with something useful to the reader, state
   beta status up front — applies unchanged to a future Linux post; L10
   does not re-do or duplicate that plan, and does not act on it early
   for a platform with nothing shippable yet.

The correct trigger for actually posting Linux-specific outreach is the
v1.0.0 release existing (a real download link to point to) — that
belongs in the v1.0.0 phase or after, not here.

### A real sequencing question this phase's review surfaced, and its resolution

Opus's review of this phase correctly identified an apparent deadlock in
the project's own prior wording: `release-linux.yml`'s original comment
said the real release trigger waits for "external Linux evidence"; this
section says outreach waits for a real download to exist; and the old L8
evidence-tier wording said EXTERNAL USER VERIFIED "stays false until L10
produces one." Chained together, nothing ever ships. This is now resolved,
not left open: the maintainer's explicit v1.0.0 authorization already
directs ONE GitHub Release carrying both the Windows installer and this
Linux `.deb`, independent of EXTERNAL USER VERIFIED — that tier was never
meant to gate v1.0.0 shipping Linux, only to honestly track whether a real
outside report has arrived. `release-linux.yml`'s comment and the L8
evidence-tier wording above were both corrected in this phase to say so
explicitly, rather than carrying forward language that predates that
authorization.

### Not addressed this phase (carried forward, not silently dropped)

The Linux Orca-auto-detection gap L9 found (`desktop/src-tauri/src/main.rs`'s
`orca_candidates()`/`tool_candidates()` returning empty under
`#[cfg(not(windows))]`) is unchanged. It remains a real, open, contained
fix candidate for whenever Linux desktop work resumes — L10 documented it
in the reporting templates (the new OS field helps distinguish "wrong
analysis" reports caused by it from genuine bugs) rather than fixing the
underlying code, which is out of this phase's documentation-only scope.

### Evidence tiers earned this phase

None — L10 is reporting-path readiness only. EXTERNAL USER VERIFIED
remains honestly false, as it must until a real report arrives from
outside this project.

## L11 — v1.0.0 release: Linux ships for real

Linux's first real GitHub Release. Two PRs: `release/v1.0.0-infra` (PR #26 —
the converging release architecture, workflow infrastructure only) merged
to `main` first, satisfying the GitHub constraint that a
`workflow_dispatch`-triggered workflow must exist on the default branch
before it can be dispatched from a branch; then `release/v1.0.0-version-bump`
(the version bump and all release-governance docs).

### What actually happened, in order

1. `release-candidate.yml` dispatched against the version-bump branch —
   **succeeded on its first live run**: Windows build + bundled-sidecar
   smoke, Linux build, both clean-environment legs (`ubuntu:22.04` and
   `ubuntu:24.04`, 35/35 each, against THIS build's own `.deb` — the L10
   fix for HIGH-3), the new `windows-upgrade-smoke` job (silent
   v0.9.0→v1.0.0 install, one registration, version updated, same
   location, legacy publisher key intact, clean uninstall), and the
   manifest job. No infrastructure bug surfaced despite three rounds of
   review having found and fixed real ones beforehand — the review process
   held.
2. `release-publish.yml` rehearsed via `workflow_dispatch` (`dry_run=true`)
   against a throwaway scratch branch carrying the RC's real hashes —
   **every gate passed on the second attempt** (the first attempt used a
   deliberately mismatched tag name to test Gate 1 itself, which correctly
   rejected it). Gate 0 correctly skipped for the pre-tag rehearsal; Gate
   1 (tag/metadata/manifest agreement), Gate 2 (provenance — the RC
   commit is an ancestor of the target with only a docs-only diff since),
   Gate 3 (both artifacts re-downloaded and re-hashed against the
   metadata) and Gate 4 (exactly 3 expected assets) all passed; the draft
   was created, verified, and deleted; no tag was touched (confirmed via
   `git ls-remote` afterward — clean). This is the first time
   `release-publish.yml` — the only workflow with `contents: write` and
   the power to publish a public Release — has ever actually run.
3. Real hardware verification, twice: once as a rehearsal against the
   still-installed v0.9.0 build (confirming the discovery mechanism and
   the read-only safety gate before committing to the real run), once
   officially against the actual v1.0.0 RC installer. Printer discovered
   via a bounded, read-only TCP-connect sweep of the local `/24` for
   Moonraker's port (7125) after the printer did not yet appear in the
   ARP cache — confirmed genuinely a Snapmaker U1 via a real `GET
   /server/info` before anything else touched it. 39/39 checks passed
   both times, identical results, confirming the printer's real state
   (four loaded filaments, 271×335×281mm bed, `print_task_config` object)
   rather than a fluke. The provider-on-hardware checks (18 more, real
   total 57) were not captured this release — they need seeded,
   session-owned Spoolman and Bambuddy containers with spool ids matching
   this printer's actual current loadout, and standing those up blind
   (Docker was not running, and no existing seed data matches this
   printer's real filament) was judged not worth fabricating data for.
   39/39 is reported as the honest, complete count of what actually ran —
   not presented as a reduced 57.
4. Real Windows UI-driven acceptance, including the real upgrade proof
   (`tools/acceptance/run.ps1 -UpgradeFrom <published v0.9.0>`): 39/39,
   including the exact new check this phase's `windows-upgrade-smoke`
   twin also proves — the surviving registration reports the new version,
   not just "not the old one" — and confirming live that the beta.13
   window-close/orphan-sidecar bug is genuinely fixed in these bytes.

### Version-metadata audit and CHANGELOG

Full CURRENT/HISTORICAL/STALE/GENERATED classification and the CHANGELOG's
"New in 1.0.0" vs "The v1.0 product includes" split were planned by Fable
(Astra/Codex unavailable all session — three independent 401 auth
failures across Astra, Sol and Terra — disclosed incomplete pair
throughout this entire release). Plan-stage and result-stage review both
by Opus alone, same reason. The plan review found 4 HIGH findings (the
GitHub dispatch-before-merge constraint; a real, confirmed Windows fix
the CHANGELOG draft had omitted; the shipped `.deb` never being tested on
a clean image; the U1 hardware gate silently accepting reduced coverage)
— all fixed before implementation. The implementation review found 2 more
HIGH and 4 MEDIUM in the new workflows themselves (an asset-glob bug that
would have failed every publish attempt; a race that could let a
rehearsal delete a real git tag; wrong exe name and an incomplete version
assertion in the upgrade smoke test; rehearsal ordering; the recovery
path reading the wrong commit) — all fixed, confirmed by a delta-confirm
pass.

### Evidence tiers earned this release

- **BUILD VERIFIED / PACKAGE VERIFIED / HEADLESS RUNTIME VERIFIED /
  DESKTOP WORKFLOW VERIFIED**: unchanged from L8, now against v1.0.0's
  own release-candidate bytes specifically rather than a continuously-built
  artifact.
- **REAL U1 VERIFIED**: earned for v1.0.0 specifically — 39/39, against
  the actual published installer, honestly bounded (provider-on-hardware
  not captured, stated plainly rather than rounded up to the historical
  57).
- **EXTERNAL USER VERIFIED**: still false. Nothing in this release changes
  that, and nothing was gated on it — matching the maintainer's explicit
  v1.0.0 authorization.
