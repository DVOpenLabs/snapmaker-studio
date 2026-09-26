# Release checklist (Snapmaker Studio — Windows + Linux)

Architecture (v1.0.0 onward): **build once, verify locally, promote the exact
bytes.** `release-candidate.yml` builds both platforms from the final code and
runs the Windows default-path upgrade smoke test; the maintainer/agent runs the
real local gates (full UI-driven acceptance, real-U1 hardware) against those
exact artifacts; only then does a docs-only commit record the hashes/counts,
and only then does `release-publish.yml` — the ONLY tag-triggered workflow —
promote those same bytes to a public Release. Nothing is ever rebuilt after
verification; nothing publishes if either platform's build, its own
clean-environment validation, or the upgrade smoke test failed.

Why "build once": builds are not bit-reproducible (PyInstaller + Rust + NSIS),
so the SHA256 is only known after a real build runs — but the docs that
describe that hash (and the acceptance/hardware counts measured against it)
must exist in the commit that gets tagged. Rebuilding at tag time would
produce different bytes than what was actually verified.

## 1. Land the release infrastructure on main FIRST

GitHub will not let a `workflow_dispatch`-triggered workflow be dispatched
from a branch until the workflow FILE exists on the default branch. So the
workflow files themselves (`release.yml`, `release-linux.yml`,
`release-candidate.yml`, `release-publish.yml`, `linux-clean-env-validate.yml`)
must be reviewed, merged to `main`, and confirmed green there — with metadata
still saying the PREVIOUS version, so `release-publish.yml`'s gates fail
closed — before any release branch tries to dispatch `release-candidate.yml`.

## 2. Branch, bump versions (commit A)

Branch `release/vX.Y.Z` from `main`. Bump, in one commit:
- `desktop/package.json`, `desktop/src-tauri/tauri.conf.json`,
  `desktop/src-tauri/Cargo.toml` (**`bundle.publisher` in tauri.conf.json
  stays untouched** — Tauri derives the NSIS upgrade-detection registry key
  from it; changing it breaks upgrade detection for every existing install)
- `desktop/src-tauri/Cargo.lock` (regenerate via `cargo check --offline` in
  `desktop/src-tauri`, don't hand-edit)
- `backend/pyproject.toml` (PEP 440 form, e.g. `1.0.0`)

This commit is EXPECTED to fail `backend`'s `test_app_manifests_match_the_released_version`
/ `test_the_rust_crate_version_matches_the_released_version` / the pyproject
equivalent — metadata still says the old version. That's the release-governance
lint doing its job (manifests ahead of metadata); say so in the PR description,
don't work around it.

## 3. Build the release candidate

```
gh workflow run release-candidate.yml --ref release/vX.Y.Z
```
Confirm green: Windows build + bundled-sidecar smoke, Linux build + its own
clean-environment validation (both `ubuntu:22.04`/`24.04`, against THIS
build's own `.deb` — not a different one), `windows-upgrade-smoke` (silent
default-path install of the last published version, then this RC, one
registration, version updated, same install location, uninstall leaves
nothing). Download the `release-candidate-manifest` artifact; note the run
URL and the four hash/size/name values for both platforms.

## 4. Local gates against the RC artifacts

```
cd backend  && python -m pytest -q
cd desktop  && npm run test && npx tsc --noEmit && npx vite build && cargo check --all-targets
```

**Windows, full UI-driven acceptance + real upgrade proof:**
```
pwsh -File tools/acceptance/run.ps1 -Installer <RC exe> -UpgradeFrom <previous published exe>
```
Download the previous published installer first and verify its SHA256 against
`docs/RELEASE_METADATA.md`'s "Previous release" row. Writes
`docs/internal/acceptance-X.Y.Z.json` and screenshots. Confirm 0 orphan
processes and that the maintainer's own real install (if any) is untouched —
the harness backs up and restores its registry entry, never deletes it.

**Real Snapmaker U1, read-only hardware verification (the one genuinely
human-gated step in this whole checklist):**
```
pwsh -File tools/hardware/verify.ps1 -PrinterHost <U1 LAN IP> -Installer <RC exe>
```
Needs the printer powered on and its LAN IP (Moonraker, port 7125 — hostnames
do not resolve). Writes `docs/internal/hardware-X.Y.Z.json`, IP redacted by
the harness itself. If the printer is unreachable, this step blocks — nothing
downstream substitutes for it; wait for the printer rather than skip it.

Re-capture the four README screenshots from this RC's own installed run into
`docs/screenshots/vX.Y.Z/`; anonymize (no real paths/IPs/private model names).

```
python tools/evidence/update.py --backend <N> --backend-skipped <K> --desktop <M>
```
writes `docs/internal/evidence.json` and `docs/internal/evidence/X.Y.Z.json`.

## 5. Docs commit (commit B)

Update, all referencing the same RC hashes/counts: `docs/RELEASE_METADATA.md`
(Windows values under the bare `Version`/`Installer`/`Size (bytes)`/`SHA256`
keys, Linux values under NEW distinctly-named rows — never rename the
existing ones, `backend/tests/test_release_docs.py`'s metadata fixture
requires those exact keys — plus a `Build run` row = the RC run URL from
step 3), `README.md`, `CHANGELOG.md`, `docs/RELEASE_NOTES.md`,
`docs/TRUST_STATUS.md`, `docs/linux-install.md`, innovation-fund docs.
`git diff --name-only <commit A> <commit B>` must be a subset of
`{README.md, CHANGELOG.md, docs/**}` — `release-publish.yml`'s Gate 2 checks
this mechanically; a code/manifest/workflow change here means the bytes it
would tag were never actually verified.

Run the full governance test suite before committing:
```
cd backend && python -m pytest -q backend/tests/test_release_docs.py backend/tests/test_evidence_consistency.py backend/tests/test_public_claims.py backend/tests/test_doc_truth_guard.py
```

## 6. Rehearse the publish workflow BEFORE tagging

```
gh workflow run release-publish.yml --ref release/vX.Y.Z -f tag=vX.Y.Z -f dry_run=true
```
Exercises every gate against commit B, creates and deletes a draft Release,
publishes nothing. Do this as early as commit B allows — a bug in
`release-publish.yml` itself is cheap to fix here and expensive to discover
after a real U1 run.

## 7. Merge, tag, publish

```
gh pr create --base main --head release/vX.Y.Z ...
```
Paired review (plan + result) same as every other change this project ships.
Merge with a **merge commit — never squash or rebase**: `release-publish.yml`'s
provenance gate checks that the RC build commit is an ancestor of the tag,
which a squash/rebase merge breaks.

```
git checkout main && git pull
git tag -a vX.Y.Z -m "Snapmaker Studio vX.Y.Z" <merge commit>
git push origin vX.Y.Z
```
`release-publish.yml` fires automatically. Confirm it goes green and the
Release is public, not a draft.

## 8. Post-publish verification (live, not assumed)

- `gh api repos/DVOpenLabs/snapmaker-studio/releases/latest` → `tag_name` is
  the new tag, `prerelease: false`, `draft: false`, exactly 3 assets, sizes
  match metadata.
- Download both assets from their `browser_download_url`s, re-hash locally,
  compare against `docs/RELEASE_METADATA.md` and `SHA256SUMS`.
- Open the live release body: every link resolves (no 404s), SHA256 +
  unsigned notice present for both platforms, no banned tooling/AI/vendor
  terms (`backend/tests/test_public_claims.py`'s guard covers this
  mechanically for the file that becomes the body — still read the live page).
- On `main`: both README download links resolve; `/releases/latest` points
  at the new tag.
- Install the published asset fresh; Settings/About shows the new version;
  the update check reports "up to date" (proves the version bump reached the
  running binary, not just the manifest).

## 9. Public release-notes protocol (every release)

`docs/RELEASE_NOTES.md` becomes the GitHub release body. Public/marketing:
- **User-facing only.** Never mention internal review tools, AI model/vendor
  names, or implementation mechanics. `backend/tests/test_public_claims.py`'s
  tooling-name guard enforces this mechanically — keep it green, don't just
  grep once.
- **No guarantees, no paid model names** (`test_public_claims.py` covers both).
- **Absolute links.** A GitHub release page resolves relative links against
  the repo root, not `docs/` — link
  `https://github.com/DVOpenLabs/snapmaker-studio/blob/vX.Y.Z/docs/<file>`.

## Rollback

A published Release can only be un-published by `gh release edit vX.Y.Z
--draft=true` (fast, first line of defense — un-publishes without touching
the tag) or, if it must come down entirely, `gh release delete`. Deleting
the git tag itself is a **HARD STOP** — needs explicit maintainer approval
every time, never a routine step. Prefer a forward-fix release through the
same pipeline over any rollback. A dry-run's draft needs no rollback — it was
never public and is deleted by the workflow itself.

## Pre-GA blockers (still open, not this release)

- **Code signing** (Windows) — acquire a cert; see `docs/windows-code-signing.md`.
- **CSP** — set in `tauri.conf.json`; re-verify the GUI still reaches the
  local engine after any CSP change. See `docs/SECURITY.md`.
- **Linux package signing** — the `.deb` is unsigned (no apt repository/GPG
  key); same SHA256-verify-before-install guidance as Windows.
