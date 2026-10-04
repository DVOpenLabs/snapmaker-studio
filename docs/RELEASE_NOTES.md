# Snapmaker Studio v1.3.1 — fixes for v1.3.0 reports

> **Independent open-source project — not affiliated with or endorsed by Snapmaker.**
> "Snapmaker" is a trademark of its respective owner.

A small release that fixes three things people hit with v1.3.0.

## What changed

- **Projects with per-object wall or support settings.** A project that sets
  `wall_generator`, `wall_loops`, `support_type` or `support_style` on individual
  objects (common in MakerWorld models) is no longer refused: Snapmaker Orca reads
  those four settings in the same words, so Studio keeps them, only when the value is
  one Orca understands. Any other per-object setting is still left out and named
  rather than guessed at.
- **Real error messages.** When Studio refuses a model for a reason it can
  explain, you now see the reason instead of "internal error". When something
  genuinely goes wrong, the message names its kind so a report can say what
  happened. Studio keeps a small local log that records only where a fault
  happened, never file names or values.
- **SpoolEase on a private name.** A SpoolEase address that is a name resolving
  to a device on your own network (for example one your router serves) is now
  accepted. A name that resolves anywhere else is still refused, and Studio never
  connects to anything off your network.
- **SpoolEase 0.7.** Studio reads the longer spool list that the 0.7 firmware
  sends: several colours or tags on one spool, line breaks in a note, spool
  count and TD. If you type an API key where the security key goes, or use an
  `https://` address, Studio tells you which credential and address it needs.

## What has not changed

Studio reads SpoolEase over its plain-http address with its security key,
read-only. SpoolEase API keys and its secure (https) port are not supported in
this release, and Studio's certificate checking is untouched. A user
running SpoolEase 0.7 firmware has confirmed the connection and that the spool list
reads; the detailed value spot-check is still pending, so the value mapping is checked
against SpoolEase's published source and fixtures and one initial real-device view.

## Verify your download

- Windows: `Snapmaker.Studio_1.3.1_x64-setup.exe` — 21,818,042 bytes — SHA256 `1052f9f1de792c102c62a91033aee5ba56840ebb99ff601b7059affcb7db8619`
- Linux: `snapmaker-studio_1.3.1_amd64_e3279da9d861.deb` — 25,803,624 bytes — SHA256 `fd96a48bfe8f972e29021ef683fb653f49f3e7b089a56e4846dd83763cc88b64`

Verification for this release is in
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.3.1/docs/TRUST_STATUS.md).
