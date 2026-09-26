# Installing Snapmaker Studio on Windows

The Windows installer is **currently unsigned** (no code-signing certificate
yet), so Windows SmartScreen will likely show a warning:

> **Windows protected your PC**
> App: (the installer's name)
> Publisher: Unknown publisher

This is expected for an unsigned build from a new publisher. It does not by
itself mean the file is unsafe — but you should still take normal
precautions: verify the checksum below before running anything.

## Download only from the official release

Only download the installer from the official GitHub Releases page:

- https://github.com/DVOpenLabs/snapmaker-studio/releases

The exact current filename, size, and SHA256 are in
[docs/RELEASE_METADATA.md](RELEASE_METADATA.md), which is kept in sync with
the release itself. Do not run installers for this app obtained from
anywhere else.

## Verify the download (SHA256)

Before installing, confirm the file's SHA256 checksum matches the value
published in [docs/RELEASE_METADATA.md](RELEASE_METADATA.md) for the release
you downloaded:

```powershell
Get-FileHash -Algorithm SHA256 ".\<downloaded-installer>.exe"
```

If the printed hash does not match, **do not run the installer** — delete it
and download again from the official Releases page.

## About the SmartScreen warning

Because this build is unsigned, SmartScreen may warn you. Only proceed if you
trust the source (the official GitHub release) and you have verified the
checksum above. If anything looks off — the checksum doesn't match, or you got
the file from somewhere other than the official release — do not continue.

## Install steps

1. Download the installer from the official Releases page above.
2. Verify the SHA256 (see above). If it doesn't match, stop and re-download.
3. Run the installer. On the SmartScreen prompt, choose **More info → Run anyway**
   only after you have verified the checksum and trust the source.
4. Launch **Snapmaker Studio** from the Start menu. No account or cloud is needed.

## Uninstall steps

1. Open **Settings → Apps → Installed apps** (or **Apps & features**).
2. Find **Snapmaker Studio** in the list.
3. Choose **Uninstall** and confirm. You can also use the uninstall entry in the
   Start menu folder, if present.

Studio is local-first: it runs on your machine, has no account and no cloud, and
sends nothing off your local network. Uninstalling does not delete your project
data (`%LOCALAPPDATA%\SnapmakerStudio`) — remove that folder yourself if you
want it gone too.

## Upgrading

Download the new installer, verify its checksum, and run it — installing over
an existing Studio upgrades it in place at the same location and keeps your
data. There is no in-app auto-update; check the Releases page for new versions.

## Code signing (planned)

Code signing is planned before any wider public launch (readiness plan:
[windows-code-signing.md](windows-code-signing.md)). Code signing
identifies the publisher and generally improves trust, but note that newly
signed files can still take time to build SmartScreen reputation, so a warning
may persist for a while even after signing. Microsoft Store distribution may also
be evaluated later as an additional trusted channel.

_Studio is local-first; nothing leaves your local network._
