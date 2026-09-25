# Installing Snapmaker Studio on Linux

> **No Linux package has been published in any GitHub Release yet.** This page
> documents a `.deb` build that has been verified in continuous integration —
> it is not an announcement of a release date. If you found this page before a
> Linux download appears on the
> [Releases page](https://github.com/DVOpenLabs/snapmaker-studio/releases),
> there is nothing to install yet — check back there.

## What you get, and what you don't need to install

The `.deb` is self-contained. It bundles the Python engine as a frozen binary
sidecar — you do **not** need to install Python, Node.js, Rust, PyInstaller,
Tauri, or any other build tool. `apt` only needs to satisfy two runtime
libraries the desktop shell links against:

```
Depends: libwebkit2gtk-4.1-0, libgtk-3-0
```

Both are standard GTK/WebKitGTK runtime libraries already present on most
Linux desktops, or installed automatically by `apt` if missing.

## Tested on

| Distro | How it was verified |
|---|---|
| Ubuntu 22.04 (x86_64) | Automated: real `.deb` installed with `apt` on a genuinely clean `ubuntu:22.04` container (no prior checkout, no dev tools), then exercised by 35 automated checks — some launch the real app under a virtual display (Xvfb) with a real window manager (Openbox) and close its real window, others call the local backend directly — all 35 passing |
| Ubuntu 24.04 (x86_64) | Same, on a clean `ubuntu:24.04` container — all 35 passing |

**Not yet tested:** a person clicking through Doctor, Prepare, and the Orca
handoff in the live UI (the automated checks above cover the backend logic
behind those screens, not mouse-driven interaction with them); a real GNOME,
KDE, or other desktop session; a real physical machine or VM (as opposed to a
container); any distro other than Ubuntu 22.04/24.04; upgrading from a
previously published Linux package (none exists yet to upgrade from);
Printer Hub against a real Snapmaker U1 from Linux; and any report from an
external user. This page will be updated as each of those is genuinely
verified.

## Download

Get the `.deb` from the
[official GitHub Releases page](https://github.com/DVOpenLabs/snapmaker-studio/releases)
— never from anywhere else. The exact current filename, size, and SHA256 are
in [docs/RELEASE_METADATA.md](RELEASE_METADATA.md), which is kept in sync
with the release itself. **Use the filename exactly as shown on the Releases
page** in every command below — do not retype or guess it; it will look
something like `snapmaker-studio_<version>_amd64_<short-hash>.deb`.

## Verify the download (SHA256)

Before installing, confirm the file's SHA256 checksum matches the value published
in [docs/RELEASE_METADATA.md](RELEASE_METADATA.md) for the release you downloaded:

```bash
sha256sum snapmaker-studio_<version>_amd64_<short-hash>.deb
```

If the printed hash does not match, **do not install the package** — delete it
and download again from the official Releases page.

## Install

```bash
sudo apt install ./snapmaker-studio_<version>_amd64_<short-hash>.deb
```

Using `apt install ./<file>.deb` (rather than `dpkg -i`) lets `apt` resolve
the two runtime dependencies above automatically if they are not already on
your system.

## Launch

Launch **Snapmaker Studio** from your desktop environment's application menu,
or from a terminal:

```bash
snapmaker-studio-desktop
```

No account or cloud sign-in is needed — Studio is local-first from first launch.

## Upgrade

There is no in-app auto-update on Linux. To upgrade, download the newer
`.deb` from the Releases page, verify its checksum, and install it the same
way:

```bash
sudo apt install ./snapmaker-studio_<new-version>_amd64_<short-hash>.deb
```

`apt` replaces the previous version in place.

## Uninstall

```bash
sudo apt remove snapmaker-studio    # keeps nothing behind but your project data
sudo apt purge snapmaker-studio     # same effect for this package — it ships no conffiles
sudo apt autoremove                 # optional: drops any dependency apt pulled in only for Studio
```

Studio's package does not own your data directory (below), so removing the
app does not delete your projects. Delete
`~/.local/share/SnapmakerStudio` (or your `$XDG_DATA_HOME` equivalent)
yourself if you want that gone too. UI preferences (theme, printer address,
filament price, materials-provider settings) are kept separately, by the
embedded browser view, not in that directory — removing the package does not
clear them, and this page does not yet document where they live on disk.

## Where Studio keeps your data

Studio follows the XDG Base Directory spec on Linux:

- Default: `~/.local/share/SnapmakerStudio`
- If you have `$XDG_DATA_HOME` set to an absolute path: `$XDG_DATA_HOME/SnapmakerStudio`
  (a relative `XDG_DATA_HOME` is treated as unset, since the XDG spec requires
  an absolute path)
- Override for either case: set `SNAPSTUDIO_DATA_DIR` to any path you choose

Studio creates its own default directory (the first two cases above) with
permissions `0700` — readable and writable only by your user. An explicit
`SNAPSTUDIO_DATA_DIR` you point at yourself is left exactly as you made it.

This directory holds your project data (library entries, prepared copies,
reports). It does **not** hold UI preferences — see Uninstall above.

Nothing is ever uploaded off your local network. Local-first means local:
no cloud, no account, no telemetry.

## Handing off to Snapmaker Orca

Studio never slices — Snapmaker Orca does. On Windows, Studio can detect an
installed Snapmaker Orca and offer to open your prepared file in it directly.
**That detection is not yet implemented on Linux.** After Prepare, Studio's
handoff button will always say "Install Snapmaker Orca" — even if you already
have it installed — and link to Orca's own download page instead of launching
it for you. Install or locate Snapmaker Orca yourself, then open your
prepared `.3mf` in it manually. The same applies to Studio's other ecosystem
tool suggestions (OrcaSlicer, FOrcaSlicer, PrusaSlicer, and so on): Studio can
still tell you *which* tool fits your project, it just can't yet detect
whether you already have it on Linux.

## Known limitations

- **Orca auto-detection**: see above — not implemented on Linux yet.
- **No in-app update check**: check the Releases page yourself for new versions.
- **A `python3` package may appear as a side effect of installing this `.deb`
  on a genuinely minimal system** — not because Studio needs it. On a bare
  system, `systemd` recommends `networkd-dispatcher`, which depends on
  `python3-gi`/`python3-dbus`/`python3`; this is normal Ubuntu/Debian
  behaviour unrelated to Studio's own two dependencies listed above, and
  disappears if you install with `apt install --no-install-recommends`.

## Troubleshooting

**The app won't start / exits immediately.** Run it from a terminal
(`snapmaker-studio-desktop`) and read the output — a missing GTK/WebKitGTK
library is the most common cause on a very minimal install; `sudo apt install
--fix-broken` after installing the `.deb` will pull in anything `apt` missed.

**You see extra background processes like `dbus-daemon`, `at-spi2-registryd`,
or `xdg-desktop-portal` after closing Studio.** These are normal desktop
accessibility/portal services your session activates on demand — they are
shared, session-scoped infrastructure that outlives any single app, not
something Studio starts and leaves behind.

**Something else looks wrong.**
[Tell us what it got wrong](https://github.com/DVOpenLabs/snapmaker-studio/issues/new?template=studio-got-this-wrong.yml)
or start a
[discussion](https://github.com/DVOpenLabs/snapmaker-studio/discussions).

---

Studio is **advisory**. It does not slice, does not promise a successful
print, and never controls your printer on its own.
