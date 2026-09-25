# Linux beta plan — L5 record

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
   Linux CI/release integration) wires versioning — record it before L6
   starts, not during.

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

PACKAGE VERIFIED / HEADLESS RUNTIME VERIFIED only, same as L4. Not claimed:
DESKTOP WORKFLOW VERIFIED, REAL U1 VERIFIED, EXTERNAL USER VERIFIED.
