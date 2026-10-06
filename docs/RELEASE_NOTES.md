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

Printables and MakerWorld downloads are verified live, and so is MakerWorld sign-in with
Google (it opens a small Studio sign-in window with no access to Studio, which closes itself).
Apple and Facebook sign-in use the same path and are not yet verified. The other approved sites
keep browsing until they are verified. A file from a host Studio has not allowlisted is
refused with a plain message. Details:
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.4.0/docs/TRUST_STATUS.md).
Downloads and "Clear site data" are available on Windows and Linux, not macOS. The size limit
(512 MiB) is checked after a download finishes, and a download abandoned part-way can leave a
partial file in Studio's downloads folder.

## Verify your download

- Windows: `Snapmaker.Studio_1.4.0_x64-setup.exe` — 21,861,080 bytes — SHA256 `0a94e5a89e88496fa65e3295140efa0e9bd7bef4317e28695509caee00ff237f`
- Linux: `snapmaker-studio_1.4.0_amd64_e5eafdc323e6.deb` — 25,862,448 bytes — SHA256 `c1b031d4e9b51ee3a46515e727285ac59d41b002b840bf01e573058b398e1701`

Verification for this release is in
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.4.0/docs/TRUST_STATUS.md).
