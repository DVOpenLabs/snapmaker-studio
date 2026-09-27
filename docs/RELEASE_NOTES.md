# Snapmaker Studio v1.1.0 — Linux detects Orca, the nozzle stops being a mystery

> **Independent open-source project — not affiliated with or endorsed by Snapmaker.**
> "Snapmaker" is a trademark of its respective owner.

> **Correction, 2026-09-26:** two items below describe what Studio's engine
> can do, not what the desktop app shows. Recording your own spool notes, and
> confirming a nozzle size yourself when firmware does not answer, are both
> supported by the engine, but the v1.1.0 desktop app has no screen for either
> yet. Reading the fitted nozzle live from your printer works in the app as
> described. Screens for both are next on the
> [roadmap](https://github.com/DVOpenLabs/snapmaker-studio/blob/main/docs/ROADMAP.md).

Everything you already know about Studio — read a project, check it against
your printer, prepare a copy, hand it to Snapmaker Orca, read the sliced job
back — is unchanged and still local-first. This release closes several
long-standing gaps between what Studio could tell you and what your printer
and your slicer actually know.

## Snapmaker Orca is now found automatically on Linux

The Windows-only limitation from v1.0.0 is gone. Studio finds Snapmaker Orca
and related tools on Linux by reading their `.desktop` files correctly, and
no longer confuses a similarly-named tool for the one you actually have
installed.

## The fitted nozzle is no longer unknowable

Stock Snapmaker U1 firmware does publish the fitted nozzle diameter — Studio
just wasn't asking for it. Now it reads the live reading from your printer,
or accepts your own confirmation when firmware doesn't answer, and always
tells you which of the two it used. A size comparison against your project
now lines up toolhead by toolhead where the data supports it, instead of
only checking whether the same sizes exist somewhere.

## An optional daily update check

Off by default. Turn it on in Help, and Studio checks GitHub for a newer
release once a day — the same request the manual "Check GitHub now" button
already made, so nothing new leaves your machine either way.

## Local spool tracking, with no Spoolman or Bambuddy required

When you haven't set up a network material provider, you can now record
what's on a spool yourself — material, colour, vendor, remaining weight —
and Studio treats your own note with the same care as a network provider: a
printer that has physically confirmed a slot is empty can never be
overridden by a stale note.

## Community hardware verification

`u1convert verify-printer` produces a read-only, redacted evidence bundle
anyone can attach to a GitHub issue to help verify a printer or a bug
report, without exposing their network address.

## Read on Linux, against a real Snapmaker U1

Beyond the automated suites, this release's engine was also run directly on
Linux against a physical Snapmaker U1 on the local network — reachability,
identification, firmware capabilities, loaded filament, and the full
project-versus-printer comparison, all read-only. See
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.1.0/docs/TRUST_STATUS.md)
for exactly what that covered.

## Upgrading

**Windows:** installing v1.1.0 over an existing install works exactly as
before — verified with an in-place upgrade test that confirms the
installation ends up reporting the new version, at the same location, with
your data kept and nothing left duplicated.

**Linux:** install with `sudo apt install ./<file>.deb` over the existing
package, the same as any `.deb` upgrade.

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

## Current limitations

Things Studio does not do yet.

- A materials provider that requires a sign-in cannot be read; Studio has
  nowhere safe to keep a credential and says so rather than storing one.
- An object whose volumes cannot all be represented declines the split and
  crosses whole, with the audit naming what that costs.
- Painted colour is read, but whether two colours meet on a layer is decided
  by the slice, so such colours have a toolhead reserved rather than being
  called simultaneous. Several attempts to prove this from tool-change data
  alone were tried and found unreliable; the honest "reserve a toolhead"
  answer stands until Studio reads the actual extrusion moves.

## Data boundaries

Information your printer, provider or file does not supply, which Studio
refuses to invent.

- Remaining filament is known only where something tracks it — a network
  provider, or your own note. Studio never estimates one on its own.

## Verification scope

Implemented and tested, with limited real-hardware or outside-user coverage
so far.

- One machine, one firmware version verified on real hardware. The
  read-only verification generalises; the sample does not.
- The nozzle-size comparison's toolhead-by-toolhead check was verified live
  on a printer with the same size fitted on every toolhead; a genuinely
  mismatched multi-nozzle setup was exercised only in automated tests, not
  against real hardware.
- Linux has been run against a real Snapmaker U1's engine directly, but not
  yet through the full provider-backed hardware harness, and has not yet
  had an external user report.

Verification for this release — every count, and what was run against the
real printer — is in
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.1.0/docs/TRUST_STATUS.md).
