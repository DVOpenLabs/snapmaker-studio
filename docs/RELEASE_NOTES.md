# Snapmaker Studio v1.4.1 — a readable spool picker

> **Independent open-source project — not affiliated with or endorsed by Snapmaker.**
> "Snapmaker" is a trademark of its respective owner.

A small release for what a SpoolEase user reported in #39: the spool drop-down was hard to read in
the dark theme, unsorted, and could not tell similar spools apart.

## What changed

- **A readable, searchable spool picker.** Settings → Materials provider replaces the operating
  system's drop-down with a Studio list. Each spool is described in words: vendor, material and
  subtype, colour name, the provider's ID and the weight status (for example
  `Yoopai PLA Matte — Red · #124 · 250 g estimated`, or `weight unknown`), with a swatch as an
  extra and never the only signal.
- **Sorted the same way every time:** vendor, material family, subtype, colour, then ID.
- **Type to narrow the list** (vendor, material, colour or `#id`), and use the arrow keys, Home/End,
  Enter and Escape. A list of a hundred spools or more works.

## What has not changed

Which spool is in which slot still means what is loaded now, and Studio still never changes your
provider or printer. Choosing a spool per project, and carrying that choice into a prepared file,
is not part of this release.

## Verify your download

- Windows: `Snapmaker.Studio_1.4.1_x64-setup.exe` — 21,867,496 bytes — SHA256 `989cc6214cd71536fd3a3f0951fdafaba7b9b929a413ee0cbac24fb0cb096966`
- Linux: `snapmaker-studio_1.4.1_amd64_482737819f3c.deb` — 25,867,028 bytes — SHA256 `3d6049787a4db908d74fa4b80f16fad986fbc549c8d83daf93da00160564761c`

Verification for this release is in
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.4.1/docs/TRUST_STATUS.md).
