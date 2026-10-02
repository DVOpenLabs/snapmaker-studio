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
- `desktop/package-lock.json`: the root `"version"` and `packages[""].version`
  only. Hand-edit these two fields; don't regenerate the lockfile, because
  `npm install --package-lock-only` also prunes unrelated optional-dependency
  entries. `tools/release/version_consistency.py` (run by the backend suite)
  fails if any of these surfaces disagrees with `desktop/package.json`, and
  names the file, the expected version and the version it found.

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

## 4. Rehearse the publish workflow NOW, before the expensive local gates

Do this here, not after commit B — a bug in `release-publish.yml` itself is
cheap to fix now and expensive to discover only after the real U1 run below.
`release-publish.yml` only reads `docs/RELEASE_METADATA.md`, the version
manifests, and `docs/RELEASE_NOTES.md` — none of which need the real
acceptance/hardware counts to exist yet, so a throwaway scratch commit with
just the RC's real hashes (known from the manifest above) is enough to
exercise every gate honestly:

```
git checkout -b scratch/vX.Y.Z-rehearsal release/vX.Y.Z
# edit docs/RELEASE_METADATA.md with the RC's real name/size/sha256 for both
# platforms and the "Build run" URL from step 3; docs/RELEASE_NOTES.md can be
# a placeholder for this rehearsal only. Commit.
gh workflow run release-publish.yml --ref scratch/vX.Y.Z-rehearsal -f tag=vX.Y.Z -f dry_run=true
```
Exercises every gate — tag/metadata/manifest agreement, RC provenance and
ancestry, artifact re-download and re-hash, draft creation and asset check —
creates and deletes a draft Release, and publishes nothing. It deliberately
does NOT delete any git tag itself (tag deletion is always a HARD STOP,
never automatic) — if GitHub auto-created a throwaway tag for this
rehearsal's draft, verify with `git ls-remote origin refs/tags/vX.Y.Z` and
delete it by hand if so. Delete `scratch/vX.Y.Z-rehearsal` once green; it
was never merged.

**If a rehearsal run fails partway (not the gates — the workflow itself
crashing) it can leave its draft behind**, uncleaned. That draft will make
the REAL publish later fail its "refuse if a release already exists" check.
Check `gh release view vX.Y.Z` before assuming something is wrong with the
real run; delete a leftover rehearsal draft by hand if you find one.

If this fails, fix `release-publish.yml` on `release/vX.Y.Z`, then
**re-run step 3 (rebuild the RC)** before rehearsing again — never just
re-rehearse against the old RC build. Gate 2 checks that everything between
the RC build commit and the tag is docs-only; a `.github/**` fix committed
*after* the RC was built would itself fail that gate forever. Still worth
doing now, before spending time on the local gates below — a second RC
build here is far cheaper than discovering this after the real U1 run.

## 5. Local gates against the RC artifacts

```
cd backend  && python -m pytest -q
cd desktop  && npm run test && npx tsc --noEmit && npx vite build && cargo check --all-targets
```

**Windows, full UI-driven acceptance (rewrapped acceptance-identity lane):**

`tools/acceptance/run.ps1` no longer installs the production installer. It takes a
REWRAPPED acceptance-identity installer plus its attestation (`-InstallerPath` /
`-AttestationPath`), or a verified real installer for it to rewrap first
(`-RealInstaller` / `-ExpectedSha256` / `-SourceVersion` / `-Sha256SumsPath`), and
the matching `-UpgradeFrom*` parameters for a rewrapped OLD -> rewrapped NEW upgrade.
There is no installer auto-discovery. Verify the SHA256 of every real installer
against `docs/RELEASE_METADATA.md` before handing it to the lane. The lane refuses to
start while the production app is running, while its update auto-check is on, or while
an earlier run left a journal or an acceptance registration behind. The report
(`acceptance.json`, which carries the closed-schema lane block inside it), the per-phase
results (node-written `results-*.json` and logs), the screenshots and, for the hardware /
demo / capture harnesses, `lane-evidence.json` are written under
`<harness root>\run\<id>\evidence` (the per-user `SnapmakerStudio-Harness` folder).
The lane block and `lane-evidence.json` are closed schemas (fixed reason codes, counts,
generated ids and strict versions; no free-text errors or paths). The node-written files
and `hardware.json` are NOT closed-schema (they rely on their own scrub and leak scan), so
copying evidence into the release record still needs a human privacy glance; console detail
is mostly best-effort scrubbed and is not an evidence boundary.
Confirm 0 orphan processes, the
"Production state unchanged (tripwire)" check, and that the maintainer's own real
install (if any) is untouched: the lane never reads or writes the production
registration, and its tripwire reports any change to the production data folders.

This proves the rewrapped acceptance-identity payload only. The real production
installer's registration, shortcuts, default-path install, upgrade and uninstall are
proven by the disposable CI lanes (`installer-smoke`, `release-candidate`), not here.
See `docs/internal/HARNESS_ISOLATION.md` for the design, the recovery procedure and
what is not proven locally.

**Real Snapmaker U1, read-only hardware verification (the one genuinely
human-gated step in this whole checklist):**

Start seeded, session-owned Spoolman and Bambuddy containers first, then run:
```
$env:SNAPSTUDIO_HW_SPOOLMAN = "<host:port>"
$env:SNAPSTUDIO_HW_BAMBUDDY = "<host:port>"
$env:SNAPSTUDIO_HW_SP_AGREE = "<spool id that agrees with what the U1 reports loaded>"
$env:SNAPSTUDIO_HW_SP_CONFLICT = "<spool id that conflicts with it>"
$env:SNAPSTUDIO_HW_BB_AGREE = "<same, for Bambuddy>"
$env:SNAPSTUDIO_HW_BB_CONFLICT = "<same, for Bambuddy>"
pwsh -File tools/hardware/verify.ps1 -PrinterHost <U1 LAN IP> -InstallerPath <rewrapped acceptance installer> -AttestationPath <its attestation>
```
(Same rewrapped acceptance-identity lane and refusals as above; `-RealInstaller` /
`-ExpectedSha256` / `-SourceVersion` can be given instead to rewrap a verified real
installer first.)
Needs the printer powered on and its LAN IP (Moonraker, port 7125 — hostnames
do not resolve). Writes `hardware.json` (IP redacted by the harness itself) and
`lane-evidence.json` under `<harness root>\run\<id>\evidence`. If the printer is unreachable, this step blocks — nothing
downstream substitutes for it; wait for the printer rather than skip it.

**The env vars above are not optional decoration.** `tools/hardware/checks.mjs`
only runs its provider-on-hardware checks when both `SNAPSTUDIO_HW_SPOOLMAN`
and `SNAPSTUDIO_HW_BAMBUDDY` are set; without them it logs "the
provider-on-hardware checks were skipped" and silently reports a SMALLER
`total` — a run missing them can still print "N/N passed" (100%) while
covering fewer checks than a real run does. **The real, full total is 57**
(confirmed in `docs/internal/hardware-0.9.0.json`). If a run's `total` is
below 57, the env vars were not set — do not accept that run as the release's
hardware evidence; re-run with the containers seeded. Require `passed == total`
AND `total >= 57`, not `passed == total` alone.

Re-capture the four README screenshots from this RC's own installed run into
`docs/screenshots/vX.Y.Z/`; anonymize (no real paths/IPs/private model names).

```
python tools/evidence/update.py --backend <N> --backend-skipped <K> --desktop <M>
```
writes `docs/internal/evidence.json` and `docs/internal/evidence/X.Y.Z.json`.

## 6. Docs commit (commit B)

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

## 7. Optional: re-rehearse against commit B

Step 4 already proved the publish workflow's gates against the RC's real
bytes. If commit B's content (README/CHANGELOG/RELEASE_NOTES wording,
anything besides RELEASE_METADATA.md's already-rehearsed values) changed
`release-publish.yml` itself, or if in doubt, repeat step 4's rehearsal
against `release/vX.Y.Z` directly (now that commit B is real, not a scratch
commit) before merging. Otherwise this step can be skipped.

## 8. Merge, tag, publish

**Known limitation:** `release-publish.yml`'s concurrency group is
repo-wide for every publish (a real tag push OR a dry-run rehearsal, for
ANY tag) — this project deliberately serializes ALL publishes rather than
only the same tag, since the SemVer-latest decision (§9) needs a
not-currently-changing releases listing. This ONE group covers the whole
run, `publish` AND the `verify` job that follows it (`verify` has no
job-level concurrency of its own — a job-level group identical to the
workflow-level one is a documented GitHub Actions deadlock and would cancel
the run). In practice this means at most ONE publish, including the
post-publish verification that follows it, can be pending at a time; a
second one queues rather than running concurrently. A stuck/long rehearsal
delays a real publish behind it — cancel the rehearsal first if that
happens. A `verify_only` dispatch is unaffected — it gets its own per-run
group and never queues behind a publish.

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
Release is public, not a draft. A tag whose name carries SemVer prerelease
identifiers (e.g. `v1.3.0-rc.1`) now fails closed at the latest decision —
before any draft exists — since a prerelease-identifier tag can never
become `/releases/latest`; this project's own tags are plain SemVer, so
that path is not expected to trigger here, but it fails safely if it ever
does.

## 9. Post-publish verification (live, not assumed)

Post-publish verification runs as its **own `verify` job** (`needs:
publish`), never inside the `publish` job itself — a job's `timeout-minutes`
is a ceiling on everything in it together, so giving verification its own
job gives it its own, disjoint time budget instead of sharing one with every
earlier gate. It runs automatically whenever a real (non-dry-run) publish
was **attempted** — not only once it is known to have *succeeded*: an "arm"
step writes that fact down immediately before the flip-to-public step, so
even if `gh release edit --draft=false` itself fails or the job then times
out before it can record its own result, `verify` still runs afterwards
and reports the true live state from the read side — no separate action
needed either way. **Limitation**: if the runner machine itself is lost
after the flip but before the job finishes, GitHub never receives that
job's outputs and `verify` is skipped. In that case (the `publish` job
shows as failed/lost with no `verify` job), run a `verify_only` dispatch
for the tag by hand (see below) to check the actual state. It runs
`tools/release/publish_verify.py verify` (tested in
`backend/tests/test_publish_verify.py`): whether the tag should be
`/releases/latest` (SemVer precedence against every other non-draft,
non-prerelease release), the release's public/non-prerelease/asset state
(bounded retry for GitHub's read-after-write delay), and a
re-download-and-re-hash of every asset — one combined pass/fail report,
always printed even if its own 480s end-to-end deadline is hit.

**If `verify` reports the release is still a draft (or missing) after a
publish was attempted**: the flip itself did not complete — nothing new
went live. Inspect with `gh release view vX.Y.Z` before doing anything
else; do not re-dispatch blindly (the refuse-if-exists check makes a
re-dispatch safe regardless, but understand what happened first).

**If `publish` succeeds and `verify` then fails for any other reason (or is
cancelled)**: the release **IS public** — a failed/cancelled `verify` job
never un-publishes anything — but it is **unverified**. Re-run the same
check, read-only, with no rebuild and nothing else touched, via
`workflow_dispatch` with `verify_only: true`:
```
gh workflow run release-publish.yml -f tag=vX.Y.Z -f verify_only=true
```
This dispatches the SAME `verify` job directly (the `publish` job's `if:`
excludes a verify-only dispatch, so it never reaches the refuse-if-exists
check, draft creation, or the publish step). `dry_run` is ignored when
`verify_only` is true. A tag whose name carries SemVer prerelease
identifiers (e.g. `v0.4.0-beta.24`) fails closed at the latest decision with
a clear message, the same as it would during a real publish — that tag was
never meant to be `/releases/latest`. Do not re-tag to "fix" a
failed/cancelled verify — the release already exists; re-verify, don't
re-publish.

**Cancelling the whole workflow run** (not just watching a failure) skips
`verify` too — cancelling is meant to stop everything, so `verify`
deliberately does not force itself to run in that case. Use a `verify_only`
dispatch afterwards to check the actual state by hand.

A publish run that ends **cancelled** (not failed) is only guaranteed to
have published nothing and left no draft behind if it was cancelled
**before** the "Create the release as a DRAFT" step started (pending, or
still in an earlier gate) — re-dispatch it; do not re-tag. If it was
cancelled **during or after** draft creation (including during or after the
publish step, or during the separate `verify` job), do not assume either
way: check the release state by hand first (`gh release view vX.Y.Z` —
present but still a draft means clean up the draft; present and public
means the release actually went out, cancellation only interrupted
verification) before re-dispatching. The refuse-if-exists check makes a
re-dispatch safe either way — it will not create a second release for a tag
that already has one.

Besides the automated check, still by hand:
- Open the live release body: every link resolves (no 404s), SHA256 +
  unsigned notice present for both platforms, no banned tooling/AI/vendor
  terms (`backend/tests/test_public_claims.py`'s guard covers this
  mechanically for the file that becomes the body — still read the live page).
- On `main`: both README download links resolve; `/releases/latest` points
  at the new tag.
- Install the published asset fresh; Settings/About shows the new version;
  the update check reports "up to date" (proves the version bump reached the
  running binary, not just the manifest).

## 10. Public release-notes protocol (every release)

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
