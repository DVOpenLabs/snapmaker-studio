# Snapmaker Studio v1.4.0 — find a model, then know if your U1 can print it now

> **Independent open-source project — not affiliated with or endorsed by Snapmaker.**
> "Snapmaker" is a trademark of its respective owner.

Browse MakerWorld or Printables inside Studio, download with the site's own button, and
Studio adds the file to your library and checks it against your actual U1.

## What changed

- **Ready Now.** A new page sorts the newest 50 projects in your library into *Needs
  preparation*, *Needs attention*, *Can't determine*, *One change away* and *Ready now*,
  each with the top reason and the next step. It reads your U1 once per check and never
  changes anything on it. A loaded spool of the right material in a different colour can
  stay *Ready now* with a visible colour warning. When the amount of filament was not
  checked it says "Amount not checked". Anything Studio cannot answer is *Can't determine*.
- **Model Connect.** Find Models opens model sites in a Studio browser with its own
  sign-in, kept apart from Studio. Press a site's download button for a `.3mf` or `.stl`
  and Studio saves it, adds it to your Design Library and shows **Added from <site>** with
  Check for U1, Prepare and Open project. Studio never sees your password, cookies or
  tokens. "Clear site data" signs you out of the model sites and leaves Studio's own
  settings alone.

## What has not changed

Studio does not slice and never starts a print. Ready Now does not scan folders, read model
pages or add the page you are looking at.

## Limits

Printables downloads are verified. MakerWorld is verified live only where
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.4.0/docs/TRUST_STATUS.md)
says so. A file from a host Studio has not allowlisted is refused with a plain message.
Downloads and "Clear site data" are available on Windows and Linux, not macOS. The size limit
(512 MiB) is checked after a download finishes, and a download abandoned part-way can leave a
partial file in Studio's downloads folder.

## Verify your download

- Windows: `Snapmaker.Studio_1.4.0_x64-setup.exe` — 21,858,277 bytes — SHA256 `e90c06f23677ed2b05485a5e20ace43c98eea65fd7603ee047d5eadd9909e505`
- Linux: `snapmaker-studio_1.4.0_amd64_7cae89042649.deb` — 25,857,442 bytes — SHA256 `48315182919c458f51382d101f7352e6375d63484a0c3f3e29bc2c294d5a680e`

Verification for this release is in
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.4.0/docs/TRUST_STATUS.md).
