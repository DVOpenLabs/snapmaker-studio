# Automation capability audit

**Run 2026-08-23** on the development machine, to establish what can actually be
automated before any task is handed to a person.

The audit exists because the previous sprint returned five items as "human
actions" that were not human actions. Four of the five turned out to be tool
problems.

## Environment

| | |
|---|---|
| OS | Windows 11 Pro, 10.0.26200 |
| Shell | PowerShell 5.1 and pwsh 7 |
| Elevation | **Not administrator** — everything below works unelevated |
| Python | 3.11 / 3.12 / 3.13 / 3.14 via the `py` launcher |
| Node | 24.11 |
| Rust | stable, cargo present |
| .NET | present |
| Package managers | Chocolatey present (needs admin for most installs); winget app alias present; no Scoop |

## What was available and unused

| Capability | Status | How it is used now |
|---|---|---|
| **WebView2 remote debugging** | Runtime 151 present | The decisive find. `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=…` exposes the *installed* app's webview to any CDP client, so the shipped build can be driven and asserted against without pixel-poking |
| **playwright-core** | Installed on demand, no browser download | Attaches over CDP with `connectOverCDP`. Used by `tools/acceptance` and `tools/demo` |
| **Windows UI Automation** | `UIAutomationClient` loads in PowerShell | Available for native windows. Written and kept at `tools/acceptance/open-file-dialog.ps1`, though the case it was written for turned out to be unreachable (see below) |
| **FFmpeg** | Absent — installed portable, unelevated | Screen-region capture via `gdigrab`, used to record the demo |
| **GitHub CLI** | Authenticated as the repository owner | Releases, API, repository metadata |
| **Chrome / Edge** | Both present | Available for browser automation; not needed once CDP-into-WebView2 worked |
| **Local network** | Reachable | A real Snapmaker U1 was found and read from — see below |
| **OBS** | Absent | Not needed; FFmpeg region capture was sufficient |

## Isolation discovered along the way

`WEBVIEW2_USER_DATA_FOLDER` and Studio's own `SNAPSTUDIO_DATA_DIR` give an
automated run its own webview profile and engine library. That matters for more
than tidiness: the first CDP session showed the maintainer's real model names in
the Recent list, which the project's own rules forbid putting in screenshots.
Both harnesses now isolate by default.

## What is genuinely unreachable, and why

**The native file picker.** Not "hard" — unreachable. Tauri's dialog plugin was
invoked directly through `window.__TAURI_INTERNALS__` and the call blocked
without ever creating a window; every top-level window on the desktop was
enumerated while the call was pending and no dialog existed. UI Automation cannot
find a window that was never created, and neither can anything else.

The fix was not to fake it. The shell now accepts a model path on its command
line — which a `.3mf` file association and "Open with" need anyway — so the
harness hands the app a project the same way Windows would. A real limitation
turned into a real feature.

## Printer access

A U1 was found on the LAN by the same discovery Studio itself uses. Read-only
only: `/server/info`, `/printer/info`, `/printer/objects/list`,
`/printer/objects/query`. No control call was made, and the read-only client
contains none.

That single session found a real defect — `loaded_filaments()` did not recognise
the parallel-array shape the firmware actually reports — and confirmed that the
fitted nozzle genuinely is not reported by any of the machine's 196 Klipper
objects, which is the fact the whole preflight honesty rule rests on.

## Result

| Previously "human" | Now |
|---|---|
| Record the 90-second demo | Automated — `tools/demo/record.ps1` |
| Twelve installed-build acceptance checks | Automated — 45 checks in the base shape (up to 63 across all branches), `tools/acceptance/run.ps1` |
| Real U1 read-only verification | Automated — `tools/hardware/verify.ps1`, 13 checks; the first run found a real bug |
| Code signing | Researched and prepared; only a form submission remains |
| Ecosystem outreach | **Posted** 2026-08-23 on the maintainer's explicit instruction — four notes, URLs in [../innovation-fund/ECOSYSTEM_OUTREACH.md](../innovation-fund/ECOSYSTEM_OUTREACH.md). The judgement of *whether* to introduce yourself to a peer is the maintainer's; once they made it, sending the notes was not a human action. |

## Revisited in the beta.24 sprint

Two of the five moved again.

**Real-hardware verification** was done by hand the first time and is now a
script, so it is part of the release gate rather than a one-off. It runs against
the installer that will be published, and it is read-only by construction: the
allowed routes are asserted against a deny-list before the first request.

**Ecosystem outreach** was returned as a human gate on the grounds that outreach
carries the maintainer's name. That reasoning was right about *the decision* and
wrong about *the act*. Once the maintainer had decided, writing four tailored
notes and posting them was ordinary work. The lesson generalises: when something
looks like a human gate, separate the judgement from the execution, and hand back
only the judgement.

**What genuinely remains** is smaller than it was: submitting a form that
represents the maintainer legally, posting under their name in a community
channel, and physical acts on the printer.
