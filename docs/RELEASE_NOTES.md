# Snapmaker Studio v1.0.0 — two platforms, one release

> **Independent open-source project — not affiliated with or endorsed by Snapmaker.**
> "Snapmaker" is a trademark of its respective owner.

Snapmaker Studio now runs on Linux, and a long-standing Windows bug is fixed.
Everything else you already know about Studio — read a project, check it
against your printer, prepare a copy, hand it to Snapmaker Orca, read the
sliced job back — is unchanged and still local-first.

## Linux, as a self-contained package

A `.deb` for Ubuntu 22.04 and 24.04 (x86_64). No Python, no Node.js, no Rust
— the engine ships as a frozen binary sidecar, and `apt` only needs
`libwebkit2gtk-4.1-0` and `libgtk-3-0`, both standard GTK/WebKitGTK runtime
libraries.

Install with `sudo apt install ./<file>.deb`, upgrade the same way, remove
with `sudo apt remove`. Your project data lives at
`~/.local/share/SnapmakerStudio` (or `$XDG_DATA_HOME`), created with
permissions readable only by you, and removing the package does not delete
it. Full guide, including known limitations and troubleshooting:
[docs/linux-install.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.0.0/docs/linux-install.md).

Verified: installing on genuinely clean Ubuntu 22.04 and 24.04 containers
(no prior checkout, no development tools), launching the real app under a
real display and window manager, and closing its real window — 35 checks
passing on each.

**Known limitation:** Snapmaker Orca is not auto-detected on Linux yet.
After Prepare, the handoff button will offer Orca's download page even if
you already have it installed — open your prepared file in Orca yourself.

## Fixed: closing the window now actually quits Studio

Since beta.13, closing Studio's main window silently left the process and
its engine running in the background on Windows — confirmed against a real
built release binary, not inferred from code alone. Every earlier
"zero-orphan" proof only covered a process being killed outright, never the
ordinary act of closing the window. Closing the window now reliably exits
Studio and its engine, on both platforms.

## Upgrading

**Windows:** installing v1.0.0 over an existing v0.9.0 install works exactly
as before — verified with an in-place upgrade test that confirms the
installation ends up reporting version 1.0.0, at the same location, with
your data kept, and nothing left duplicated.

**Linux:** this is the first Linux release, so there is nothing to upgrade
from yet.

## Still true

Studio does not slice — Snapmaker Orca does. Studio never starts a print on
its own; every action in Printer Hub is confirmed by you. Everything is
local: no cloud, no account, nothing uploaded off your local network — the
one transfer Studio makes is a sliced job to your own printer, after you
confirm it. Your original files are never modified; preparing always writes
a copy. Advice is advisory: Studio reports what it can establish and says
"unknown" when it cannot, and it does not promise a print will work.

Neither installer is code-signed yet — verify the SHA256 on the release page
before running either one.

## Known limitations

- Snapmaker Orca auto-detection is Windows-only for now (see above).
- No in-app update notification on either platform; check the Releases page.
- The fitted nozzle cannot be read from stock firmware, and free storage is
  not reported by it either.
- Remaining filament is known only where something tracks it — Spoolman or
  Bambuddy, read-only, local-network only.
- Painted colour is read, but whether two colours meet on a layer is decided
  by the slice, so such colours have a toolhead reserved rather than being
  called simultaneous.
- One machine, one firmware version verified on real hardware. The
  read-only verification generalises; the sample does not.
- Linux has not yet been run against a real Snapmaker U1, and has not yet
  had an external user report.

Verification for this release — every count, and what was run against the
real printer — is in
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.0.0/docs/TRUST_STATUS.md).
Installing and verifying the download:
[windows-install.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.0.0/docs/windows-install.md) ·
[linux-install.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.0.0/docs/linux-install.md).
Materials providers in detail:
[MATERIAL_PROVIDERS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.0.0/docs/MATERIAL_PROVIDERS.md).
