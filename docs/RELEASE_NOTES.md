# Snapmaker Studio v1.3.0 — SpoolEase as a third material provider, and stricter provider reads

> **Independent open-source project — not affiliated with or endorsed by Snapmaker.**
> "Snapmaker" is a trademark of its respective owner.

v1.2.0 put your spool notes and nozzle sizes on screen. This release adds a third
place Studio can read spool information from — SpoolEase — and tightens how every
material provider is read.

## SpoolEase, read-only

Settings → Materials provider now offers **SpoolEase** alongside Spoolman and
Bambuddy. Enter its address and the security key shown on its screen (or set in
its own settings), and Studio reads its spool list the same read-only way it
reads the other two.

- The key is kept in memory for the running session only. It is never written to
  Studio's library or settings, and you enter it again after restarting Studio.
- SpoolEase weighs spools on its own scale but cannot see anything a Snapmaker U1
  has printed, so every remaining-weight figure it supplies is treated as an
  estimate. Like an undated figure from any other provider, it can warn, but it
  is never the only reason a send is refused.
- **Status: protocol verified against SpoolEase's source and test fixtures.
  Validation on a real SpoolEase device is pending with a community tester.**
  Protocol notes:
  [SPOOLEASE_PROTOCOL.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.3.0/docs/interop/SPOOLEASE_PROTOCOL.md).

## Provider addresses and timing, for every provider

- **A name is checked by what it resolves to**, not only by how it is spelled. A
  name that resolves only to a public address is refused, with a suggestion to
  enter the provider's own local address; a name that resolves to both a local
  and a public address is read on the local one only.
- Proxies set in your environment or your system are ignored for a provider read.
- The "on your own network" check is stricter for IPv6: 6to4, Teredo and NAT64
  addresses are no longer accepted as local. The check works by address category,
  so it is a real check but not literal proof that an address is on your own
  network.
- **Every provider read has an overall time limit.** A slow or hung device can no
  longer hold a request open.
- **Provider status messages never contain the address you configured.**
- Spoolman's and Bambuddy's "did not answer" message now reads "did not answer in
  time (Studio waited about N seconds)", matching SpoolEase's. Verdicts are
  unchanged.

## Also in this release

- A remaining weight that carries no date now says so — "Nothing records when this
  figure was last updated." — even when there is enough of it for the job.
  Verdicts are unchanged.
- A saved slot mapping may now hold a text spool id, because SpoolEase's own ids
  are text. Existing mappings for Spoolman and Bambuddy need no change.
- Release and build reliability improvements.

## Upgrading

**Windows:** installing v1.3.0 over v1.1.0 upgrades in place — verified with a
silent default-path install of the published v1.1.0 installer followed by this
release's candidate on a disposable GitHub-hosted runner: one registration
afterward, the version updated, the same install location, and a clean
uninstall. That test checks the installation itself; it does not inspect your
saved notes or settings. Upgrading from v1.2.0 uses the same installer path but was not
separately run.

**Linux:** install with `sudo apt install ./<file>.deb` over the existing
package, the same as any `.deb` upgrade.

## Still true

Studio does not slice — Snapmaker Orca does. Studio never starts a print on its
own; every action in Printer Hub is confirmed by you. Everything is local: no
cloud, no account, nothing uploaded off your local network — the one transfer
Studio makes is a sliced job to your own printer, after you confirm it. The
only request beyond your network is the optional check for a newer version on
GitHub, which you start or switch on yourself and which sends none of your
data. Your original files are never modified. Advice is advisory: Studio reports
what it can establish and says "unknown" when it cannot, and it does not promise
a print will work.

Neither installer is code-signed yet — verify the SHA256 on the release page
before running either one.

## Current limitations

- **SpoolEase has not yet been tested against a real device.** Its behaviour is
  verified against its published source and test fixtures only.
- A materials provider that requires a sign-in cannot be read, other than
  SpoolEase's session-only key; Studio has nowhere safe to keep a credential and
  says so rather than storing one.
- An object whose volumes cannot all be represented declines the split and
  crosses whole, with the audit naming what that costs.
- Painted colour is read, but whether two colours meet on a layer is decided by
  the slice, so such colours have a toolhead reserved rather than being called
  simultaneous.

## Verification scope

- The installed Windows application was exercised through its real UI on a clean
  local account using an acceptance copy of the installer: 45 checks, all
  passing. The real installer's own upgrade and uninstall were exercised only on
  a disposable GitHub-hosted runner.
- A real Snapmaker U1 was read through the Windows-installed application,
  read-only: 58 checks, all passing, with no printer-control action called. The
  printer reported that it was printing while these checks ran.
- Reading spools from Spoolman or Bambuddy was checked in automated tests, not
  against the real printer alongside a live provider; SpoolEase was not run
  against real hardware at all.
- One machine, one firmware version. The Linux package was checked on clean
  Ubuntu 22.04 and 24.04 containers, not against the real printer, and Linux has
  not yet had an external user report.

Verification for this release — every count, and what was run against the real
printer — is in
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.3.0/docs/TRUST_STATUS.md).
