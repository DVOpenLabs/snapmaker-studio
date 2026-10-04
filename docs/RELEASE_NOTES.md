# Snapmaker Studio v1.3.1 — fixes for v1.3.0 reports

> **Independent open-source project — not affiliated with or endorsed by Snapmaker.**
> "Snapmaker" is a trademark of its respective owner.

A small release that fixes three things people hit with v1.3.0.

## What changed

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
this release, and Studio's certificate checking is untouched. A real-device
confirmation of SpoolEase is still pending from a user; until then the
SpoolEase integration is checked against SpoolEase's published source and
fixtures, not a physical device.

## Verify your download

- Windows: `Snapmaker.Studio_1.3.1_x64-setup.exe` — 21,817,159 bytes — SHA256 `5e545c00720d55ee83bd5dc970b5b69a29c5beffcd0136b8b428cb452ed8171e`
- Linux: `snapmaker-studio_1.3.1_amd64_8daea1f6a027.deb` — 25,804,666 bytes — SHA256 `4388fcd7ce2fcdbf278d710767bab71d9a90cd9925115fbbf535b321f674d5dc`

Verification for this release is in
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.3.1/docs/TRUST_STATUS.md).
