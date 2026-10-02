# Harness install-identity isolation (issue #55)

Status: implemented on branch `fix/55-harness-install-isolation`; nothing here has been run against a real installer or
the app on the maintainer workstation. This document describes the design, the four workstation lanes, what the
controls do and do not cover, and how to recover.

## Why

The workstation harnesses used to install the real production installer (product name `Snapmaker Studio`, publisher key
`DeadlyVirusIn / Snapmaker Studio`, binary `snapmaker-studio-desktop.exe`) into a scratch directory. The uninstall
registration, remembered-install-location key, Start Menu / Desktop shortcuts, Run value, AUMID and the app data folders
are keyed by identity, not by install directory, so a harness run could overwrite, then delete, the maintainer's real
installation. Two harnesses also launched the app without an isolated WebView2 profile, and one stopped processes by
name.

## Design in one paragraph

Workstation tooling never installs the production identity. It installs a **rewrapped acceptance-identity installer**:
`tools/release/rewrap_installer.ps1` extracts a verified real installer with a pinned 7-Zip and recompiles the payload
with a pinned NSIS template whose only differences are the identity (product name `Snapmaker Studio Acceptance`,
publisher key `SnapmakerStudio-Acceptance`, bundle id `com.snapmakerstudio.acceptance`, renamed main binary
`snapmaker-studio-acceptance-desktop.exe`), the removal of every app-data deletion, and the removal of the reinstall
page. It writes an attestation (payload manifest, renames, enumerated delete targets, template hash). The installer is
never run by the rewrap. The harnesses accept only such an installer and its attestation; the real production
installer is always refused by `tools/lib/InstallGuard.psm1`. Real-identity install, upgrade and uninstall exist only as
inline steps of the disposable GitHub-hosted CI workflows.

## Components

| Piece | File | Role |
|---|---|---|
| Identity constants | `tools/lib/HarnessIdentity.psd1` | Acceptance identity (write target), Production identity (detection and refusal only), recovery allow-list |
| Guard | `tools/lib/InstallGuard.psm1` | Installer/uninstaller authorisation, copy-then-hash-then-launch, path allowlists, machine-wide lock, production detection |
| Journal + recovery | `tools/harness/HarnessJournal.psm1`, `tools/harness/Repair-Harness.ps1` | Per-run recovery journal written before the installer starts; compare-and-swap recovery of the fixed acceptance surfaces |
| Shared lane | `tools/harness/HarnessLauncher.psm1` | The one fail-closed install / launch / uninstall / cleanup lane used by all four harnesses |
| Rewrap | `tools/release/**` | Builds the acceptance installer and its attestation |
| Disposable CI | `release-candidate.yml` (job `windows-upgrade-smoke`); `.github/workflows/installer-smoke.yml` (reusable lane, no permanent caller) | The only places the real production identity is installed, upgraded or uninstalled |

## The four workstation lanes

All four call the same functions in `HarnessLauncher.psm1`. None keeps its own copy of the install, launch, kill or
cleanup logic. Each takes the same installer parameters: either a rewrapped installer plus its attestation, or a
verified real installer plus its expected sha256 and source version for the lane to rewrap first. There is no installer
discovery (no glob, no "newest in the build folder"), and a wildcard in any installer path is refused.

| Lane | Script | What it does | What it proves |
|---|---|---|---|
| Acceptance | `tools/acceptance/run.ps1` | Install, launch six times (warm-up, relaunches, painted/second/third runs), drive the UI over CDP, run the 21+ acceptance checks, uninstall | The shipped payload (exe plus frozen sidecar) under the acceptance identity. With the upgrade parameters: rewrapped OLD to rewrapped NEW, not a production upgrade |
| Hardware | `tools/hardware/verify.ps1` | Same plumbing, then read-only questions to a real U1 over the LAN. No print, heat, move, upload or configuration call | The shipped payload talking to a real printer, read-only |
| Demo | `tools/demo/record.ps1` | Same plumbing, FFmpeg plus CDP recorder; FFmpeg is told to quit through its stdin and force-stopped only by its tracked pid | The recording is the real app window |
| Capture | `scripts/capture_embedded.ps1` | Same plumbing; finds the window by the tracked process id and captures it with PrintWindow | The screenshot is the tracked app's own window |

Evidence from every lane names the lane honestly (`rewrapped acceptance-identity installer`, or the OLD to NEW label
for an upgrade), records `identity: acceptance`, the installer sha256, the template hash and the tripwire result, and
carries a `notProven` statement. The acceptance report and the lane evidence use `<harness-root>`-style paths, never
absolute local paths.

## What the shared lane enforces

Everything fails closed: any error, ambiguity or missing evidence aborts.

**Install.** The installer is copied into `<harness root>\staging`, hashed, and its VersionInfo product name must be the
acceptance identity and its hash must be bound to a valid attestation (`Assert-InstallerAllowed`).
`Confirm-InstallerUnchanged` re-checks the staged copy immediately before the launch. The arguments are exactly
`/S /NCRC /NS /D=<install dir>` with `/D=` last and unquoted; never `/P`, never an app-data flag. The install directory is
`<harness root>\install\<runId>`, not `%TEMP%` and not a production path. `/NS` creates no shortcuts.

**Journal and lock.** `Enter-HarnessLock` (machine-wide) is held for the whole run. A journal is written before the
installer starts (`New-HarnessJournal`) and completed after (`Set-JournalOwnedAfter`). Because `/NS` creates no shortcuts,
and the default-resolved OneDrive-redirected Desktop is a reparse point that the journal refuses by design, the journal's
Start Menu and Desktop destinations are harness-owned, empty directories under the run directory. Separately, the lane
asserts, read-only (`Test-Path` only), that the real Start Menu and Desktop known folders hold no acceptance shortcut,
before the install, after it and at the end. It never writes or restores there. An upgrade lane uses one journal per
phase.

**Launching the app.** Every launch of the app exe goes through one function. It refuses unless all of these hold:
every isolation path (WebView2 profile, engine data dir, evidence dir, install dir) resolves, reparse-free, strictly inside
the harness directory; the exe is the renamed acceptance binary, inside the harness install dir; the production exe is not
running; `%APPDATA%\com.snapmakerstudio.desktop\update_check.json` (resolved with `[Environment]::GetFolderPath`) is
absent or parses as JSON with `auto_check` explicitly `false` (corrupt, unreadable, ambiguous or a directory is refused);
the WebView2 runtime is present (read-only registry check, the bootstrapper is never run); and the debug port is free.
The isolation variables are passed **only to the child process** (`ProcessStartInfo.Environment`); the session
environment is never modified. After launch `<profile>\EBWebView` must exist exactly (no alternative layout is accepted;
hard failure otherwise: the app and its descendants are stopped) and the CDP endpoint must belong to the tracked app's
process tree. The app's descendants (the sidecar) are registered for cleanup immediately after launch and again when a
postflight fails, so a failed launch leaves no tracked process behind. No harness drives the update auto-check checkbox or diagnostics export.

**Process hygiene.** Every process the lane starts is tracked by pid and start time (and journaled when it is the app).
Close is graceful first. A forced stop happens only for a tracked pid whose start time still matches and whose image is
still inside the harness tree (tools such as node and ffmpeg: the exact recorded image). Nothing is ever stopped by name.
Only `node` and `ffmpeg` can be started through the tool path. Snapmaker Orca, printer, slicer and any user GUI process
are never touched.

**Cleanup (always runs, in `finally`).** Stop tracked processes, then uninstall (silent `/S` only, after
`Assert-UninstallerAllowed` and `Confirm-UninstallerUnchanged`), then journal recovery, then the production tripwire and
the real-folder shortcut check, then release the lock. Each step is isolated so a failure in one never skips the next.
`-KeepInstall` skips the uninstall and the recovery (the journal stays pending); it does not skip the tripwire, the
evidence or the lock release, and the evidence states that the install and journal were kept and gives the exact
`-RunId` / `-ShortcutDir` for `Repair-Harness.ps1`.

Three rules keep a failed run from silently orphaning an install:

- **Uninstall hand-off.** The NSIS uninstaller may hand off to a temp copy and exit at once. After the parent exits the lane
  waits, bounded, for both the install dir to hold no files and for no process whose command line references the install
  dir (read-only inspection; the hand-off child is never killed). A timeout is a lane failure ("uninstall hand-off did not
  complete") and the journal stays pending. The "Uninstall completes" check rests on the install dir state and that wait,
  not on the parent's exit code.
- **No recovery over a populated install dir.** The installer copies the exe and sidecar before the uninstaller and the
  registration, and recovery treats unchanged registry/shortcut surfaces as "nothing to do" and finalises the journal.
  So recovery is never called while the install dir still holds files. The lane reports `orphaned acceptance install:
  <count> files under install\<runId>` (relative path and count only), exits non-zero and leaves the journal pending.
  Remove the acceptance install under the harness install folder yourself, then run `Repair-Harness.ps1` for each journal.
- **Installer failure is lane failure.** A non-zero installer exit code, a kill or a timeout fails the lane.

Underneath all three is one principle: **any ambiguity means unknown, and unknown holds the journal.**

- **Strict enumeration.** The install-dir file count is a strict enumeration. Any enumeration error (access denied, an
  unlistable subtree) or a reparse point under the install dir yields `$null`, which means "files may remain" and is never
  treated as zero. `$null` is not clean at the hand-off wait, at the recovery gate or in the "Install directory removed" check.
- **Process-query failure is an unknown hand-off.** If the read-only process query fails, the hand-off is unknown, not
  "no process found".
- **Explicit uninstall outcome.** The uninstall outcome is `Success`, `NothingInstalled`, `NotLaunched` (the guard refused
  before anything ran), `Failed` or `Unknown`. Any exception after the uninstaller launched (parent timeout, wait or query
  failure) is `Unknown`. Recovery is an allow-list: it runs only for `Success`, `NothingInstalled` or `NotLaunched` with a
  strictly clean install dir. Anything else keeps the journal pending, exits non-zero and prints the exact
  `Repair-Harness.ps1 -RunId <id> -ShortcutDir <harness-root>\run\<id>\shortcuts` hint.
- **Lane evidence is closed-schema, so its privacy comes from its shape, not from scrubbing.** For the three
  evidence-writing harnesses (`verify.ps1`, `record.ps1`, `capture_embedded.ps1`) the lane evidence is `lane-evidence.json`;
  for the acceptance harness it is the `lane` block INSIDE `acceptance.json` (there is no separate `lane-evidence.json`
  there). It is built field by field from typed lane state and the schema enforces: fixed enums (lane label, status,
  uninstall outcome, reason codes), strict patterns (hex hashes, a strictly numeric release version such as `1.2.0` or
  `0.4.0-beta.20.2`, a numeric WebView2 version, and GENERATED ids: a run id is `h` plus 32 lowercase hex characters and can
  never be a word a person chose, so `install\<runId>` and `run\<runId>\shortcuts` are fixed-shape names), integers and
  booleans. A value that does not fit is dropped to null or rejected. Raw exception text, command output, paths, user
  names, registry paths and hosts are never put into the object. The check **details** of the acceptance run are
  console-only; only fixed check names plus pass/fail are written.
- **What validates what.** For `lane-evidence.json`, the writer validates the object against the whitelist, serialises it
  as-is, and a SECONDARY check then looks in the output for absolute paths, forward-slash drive paths, `/home`-style paths,
  any `-Redact` value (a printer address) and the user name (only inside the values of pattern-typed fields, so short user
  names do not trip fixed words); if it finds something the write FAILS (`REPORT_WRITE_FAILED`, nothing persisted) and the
  harness exits non-zero. That secondary check does NOT cover the `acceptance.json` lane block: that path is closed-structure
  validation of the FINAL on-disk file (exact keys, literal schema version, integer totals, checks exactly `{name, ok}`,
  lane block against the closed schema; any mismatch deletes the file and fails the run), plus the existing scrubber (applied
  only to the check-name values, before the lane block is inserted, so the closed block is never rewritten) and the
  provider-address leak scan. A failed run persists `status: fail` with at least one reason code.
- **Outside the closed schema.** The node-written `results-*.json` and logs in the evidence folder, and `hardware.json`,
  are NOT closed-schema. They rely on their existing scrubbing and leak scan. Copying evidence into the release record
  therefore still needs a human privacy glance.
- **Console detail is best-effort scrubbed.** Most exception and detail text printed to the console is passed through
  `Protect-LaneText`; the scrubber is a **secondary, console-only** layer. It is NOT the evidence privacy boundary and does
  not guarantee removal of every private path form. Known unhandled forms include forward-slash UNC style, POSIX, `%VAR%`
  and `~` paths, placeholder-prefixed paths, and relative paths containing apostrophes or spaces.
A new lane refuses to start while an unfinished journal exists or the acceptance uninstall key is present, and points at
`Repair-Harness.ps1`.

## Threat model and scope

These controls are an **accident / agent-error control**. They are meant to stop a script or an automated agent from
installing, overwriting, launching or deleting the maintainer's real installation or data by mistake. They are not a
defence against a maintainer, or any process running as the same user, who deliberately bypasses them. There is no
handle-based confinement: every containment check narrows, but does not eliminate, the window between check and use.

## Production-state tripwire

Before the lane (baseline) and after each lane, including from `finally`, the lane snapshots, read-only and without
following reparse points: `%APPDATA%\com.snapmakerstudio.desktop` and `%LOCALAPPDATA%\com.snapmakerstudio.desktop`
(names, sizes, modification times, plus a share-read hash of the Local Storage leveldb files), and the production
engine folder `%LOCALAPPDATA%\SnapmakerStudio` (detect-only).

| Folder | Expectation |
|---|---|
| Roaming `com.snapmakerstudio.desktop` | Stays absent if it was absent; if it existed it is unchanged |
| Local `com.snapmakerstudio.desktop` | May go absent to empty only; if it existed it is unchanged |
| Production engine folder | Unchanged (absent stays absent) |

Any other difference is reported in the evidence and the lane exits non-zero. Findings are **counts and categories only**
(for example "Local entries ADDED: 2", "leveldb files hash-CHANGED: 1"): a file or directory name from a production folder
is never written by the tripwire (the persisted evidence carries only the integer counts, as a closed schema), because
those folders can hold private model names. The tripwire never restores, repairs or deletes anything.

## Recovery

If a run is interrupted, run `tools/harness/Repair-Harness.ps1` (acceptance identity only). Lane journals use harness-owned
shortcut destinations, so recover them with `-ShortcutDir` pointing at that run's `shortcuts` directory under
`<harness root>\run\<runId>`; an upgrade lane has one journal per phase (`<runId>` and `<runId>-u2`). A journal whose
destinations differ from the ones given is treated as corrupt and nothing is changed.

| Exit code | Meaning |
|---|---|
| 0 | Every journal was finalised, or there was nothing to do |
| 1 | Unexpected error (nothing further was attempted) |
| 2 | A journal is missing or corrupt, or its destinations do not match. No destructive action was taken; inspect the harness state manually |
| 3 | A surface needs a manual step: the acceptance install is complete and must be uninstalled, or a compare-and-swap / verification check failed. The journal is kept |

Recovery touches only the fixed acceptance-identity allow-list (uninstall key, remembered-location key, Run value, Start
Menu and Desktop shortcut) and never the production keys or the shared publisher subtree.

## Residuals (known and accepted)

- **Change-and-restore races.** A same-user process that changes a checked path and changes it back between the check and
  the use is not detected.
- **Hostile include side effects.** The rewrap compiles with a pinned, snapshotted NSIS tree; a principal with write access
  to the harness root racing the build could still affect compile-time behaviour. See `tools/release/nsis/PROVENANCE.md`.
- **WebView2 / profile.** The WebView2 runtime itself is shared and is not isolated. The isolated user-data folder is
  confirmed after launch (exactly `<profile>\EBWebView`) and the tripwire watches the production profile. If the shipped
  WebView2 writes a different layout when `WEBVIEW2_USER_DATA_FOLDER` is set, the launch fails closed; the first
  controlled run will confirm the layout and must be reviewed.
- **`update_check.json` is shared state.** The published app resolves its config folder through the OS known-folder API and
  has no state-root override, so the file cannot be redirected. The lane refuses to launch unless the file is absent or
  `auto_check` is `false`, and the tripwire detects a change. A product-side override is a **separate follow-up product
  issue**; the published payload does not have it.
- **Manual interference.** Launching the production exe by hand after the preflight, or using the auto-check UI during a
  harness session, is a detection-only case.
- **Journal content** is validated on read, not on save, and the TEMP-misconfiguration case widens the override allowlist
  for the second layer only (carried debt from the guard review).

## What is NOT proven locally

Production registration, shortcut creation and AUMID, default-path install, upgrade and uninstall of the **real**
installer are exercised only on disposable GitHub-hosted runners. `release-candidate.yml` job `windows-upgrade-smoke` remains
the standing gate that tests the candidate build. `.github/workflows/installer-smoke.yml` is a reusable disposable lane
(GitHub-hosted, `contents: read`) that has no permanent caller and is not part of release gating; its first controlled
run, through a temporary caller, passed on a disposable runner: https://github.com/DVOpenLabs/snapmaker-studio/actions/runs/37019477486 (published v1.1.0 -> v1.2.0
install, upgrade, launch and uninstall, with exact-key, shortcut, AUMID and clean-machine assertions). It is not run on every
release. The
workstation lanes prove the rewrapped acceptance-identity payload and nothing about the production installer. The
synthetic fault barriers in the journal tests validate the recovery state machine only, not OS-crash or power-loss safety.
Whether the WebView2 profile layout, the CDP port ownership check and the uninstall hand-off behave as designed against
the real shipped payload has not been exercised on this workstation; the first controlled run must be reviewed.

## Tests

`tools/harness/HarnessLauncher.Tests.ps1` (Pester 5) uses fixtures and mocks only: no installer, app or product process is
started; registry writes are confined to the scratch hive `HKCU:\Software\SnapmakerStudioHarnessTest\<guid>`; files live
in private temp directories. The one real child process is a harmless `pwsh` that proves environment is applied to the
child only. The file also parse-checks the module and the four scripts, and asserts, narrowly for those five files only,
that none contains a wildcard registration lookup, installer globbing, a session-environment assignment of an isolation
variable, a name-based process stop, a raw `Start-Process`, a production uninstall-key export or import, or an absolute
local path.
