# Snapmaker Studio v1.2.0 — your spool notes and your nozzle sizes, in the app

> **Independent open-source project — not affiliated with or endorsed by Snapmaker.**
> "Snapmaker" is a trademark of its respective owner.

v1.1.0 taught Studio's engine to keep your own spool notes and a nozzle size you
confirm yourself. This release puts both in the desktop app, with every value
labelled by where it came from — and the printer's own reading always winning.

## Your spool notes

Settings → the Materials provider card → **Your spool notes**. For each slot you
can record the material, subtype, colour, vendor, starting weight, remaining
weight and a free-form note; edit it; clear any field; or remove the note.

- The remaining weight says where it came from: **entered by you**,
  **estimated from what you recorded**, **tracked by your provider**, or **no
  weight recorded**.
- Changing to a different spool — another material, subtype, colour or vendor —
  resets the remaining weight to "no weight recorded". Clearing a field does not.
- **Record filament used** subtracts a job's grams only after you confirm the
  amount, and the result is labelled as an estimate.
- A slot the printer reports empty stays empty, whatever a note says.
- Switching between None, Spoolman and Bambuddy never touches your notes.
- If two notes ever end up stored for the same slot, neither is used: the slot
  reads unknown until you remove one.

## Your nozzle sizes, per printer and per toolhead

Settings → the **Nozzles** card under Printer.

- When the printer reports its fitted nozzles, each toolhead shows the printer's
  reading — **Source: Printer**, **Reported live** — and there is nothing to type
  over it.
- When it does not, or it is offline, you can confirm each toolhead yourself,
  including mixed sizes. A toolhead left as "Not sure" stays unknown. Your
  confirmation is dated, kept per printer, and editable or removable, and it
  survives a restart. Offline, the table uses the U1's four toolheads.
- If a note you saved earlier disagrees with a live reading, both are shown and
  Studio uses the printer's value; **Remove my note** clears yours.
- Preflight, the after-slicing check and the send check use your confirmation
  only when the printer gives no live reading, and flag a disagreement
  separately.
- The comparison is toolhead by toolhead: a proven wrong size or swap is
  flagged; anything that cannot be proven is reported as unknown, never as a
  match.

## Also in this release

- Two printer addresses that mean the same printer — different case, a trailing
  dot, IPv6 forms — are treated as one, so your notes follow the printer.
- A disagreement between your material provider and your own note now names the
  real source, instead of attributing it to the printer.
- Save and Remove all are hidden when there is nothing to save or remove.
- If Studio cannot check the printer at all after a save, it says so plainly
  rather than claiming the printer is unreachable.

## Upgrading

**Windows:** installing v1.2.0 over v1.1.0 upgrades in place — verified
with a silent default-path install of the published v1.1.0
installer followed by this release's candidate: one registration afterward,
the version updated, the same install location, and a clean uninstall. That
test checks the installation itself; it does not inspect your saved notes.

**Linux:** install with `sudo apt install ./<file>.deb` over the existing
package, the same as any `.deb` upgrade.

## Still true

Studio does not slice — Snapmaker Orca does. Studio never starts a print on its
own; every action in Printer Hub is confirmed by you. Everything is local: no
cloud, no account, nothing uploaded off your local network — the one transfer
Studio makes is a sliced job to your own printer, after you confirm it. The
only request beyond your network is the optional check for a newer version on
GitHub, which you start or switch on yourself and which sends none of your
data. Your
original files are never modified. Advice is advisory: Studio reports what it
can establish and says "unknown" when it cannot, and it does not promise a print
will work.

Neither installer is code-signed yet — verify the SHA256 on the release page
before running either one.

## Current limitations

- A materials provider that requires a sign-in cannot be read; Studio has
  nowhere safe to keep a credential and says so rather than storing one.
- An object whose volumes cannot all be represented declines the split and
  crosses whole, with the audit naming what that costs.
- Painted colour is read, but whether two colours meet on a layer is decided by
  the slice, so such colours have a toolhead reserved rather than being called
  simultaneous.
- A "Not sure" entry saved for a toolhead the printer now reports live stays
  stored (it is never used while the live reading exists) and is not offered for
  removal until the printer stops reporting.

## Data boundaries

- Remaining filament is known only where something tracks it — a network
  provider, or your own note. Studio never estimates one on its own.

## Verification scope

- One machine, one firmware version, verified read-only against the
  Windows-installed application: uniform 0.4 mm on all four toolheads.
- A genuinely mixed-nozzle printer was exercised only in automated tests, not
  against real hardware.
- On Linux, the spool-notes and nozzle-confirmation screens were exercised
  through the installed app's local interface on clean Ubuntu 22.04 and 24.04,
  not by driving the UI; the Linux-installed app was not run against the real
  printer.
- Reading spools from Spoolman or Bambuddy was checked in automated tests, not
  against the real printer alongside a live provider.
- Linux has not yet had an external user report.

Verification for this release — every count, and what was run against the real
printer — is in
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.2.0/docs/TRUST_STATUS.md).
