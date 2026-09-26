# Release Metadata — canonical source

This file is the single source of truth for the released version, installer name,
size and hash. Update it first on every release.

**One duplication is allowed, on purpose:** the README's download block repeats the
size and SHA256, because telling someone to open a second document before verifying
a download is how verification stops happening. That copy is only safe while it is
checked, so `backend/tests/test_release_docs.py` fails the build if the README and
this file disagree, if a superseded hash survives in a download instruction, if the
app manifests carry a different version, or if `TRUST_STATUS.md` does not lead with
the release named here.

Every *other* document must link here rather than restate these values.

## Current release

| Field | Value |
|---|---|
| Version | v1.0.0 |
| Installer | `Snapmaker.Studio_1.0.0_x64-setup.exe` |
| Size (bytes) | 18,119,559 |
| SHA256 | `e15029af0af2fd268a546000473f21c52c7a5b302556e1cd7fda300b65f8d501` |
| Linux installer | `snapmaker-studio_1.0.0_amd64_3c7bef9f0a34.deb` |
| Linux size (bytes) | 20,676,536 |
| Linux SHA256 | `d5fdb69a9f443a73e682ba3515d7c974e3bf242ce3525f148788822274aae516` |
| Build run | https://github.com/DVOpenLabs/snapmaker-studio/actions/runs/36208710733 |
| Release URL | https://github.com/DVOpenLabs/snapmaker-studio/releases/tag/v1.0.0 |
| Trust status | ACCEPTED — see [docs/TRUST_STATUS.md](TRUST_STATUS.md) |

A stable release, not a prerelease, so GitHub's "latest release" points at it.
Hashes for both files are also published as `SHA256SUMS` on the release.

Note: verify with `Get-FileHash -Algorithm SHA256 <installer>` (Windows) or
`sha256sum <file>.deb` (Linux).

## Previous release

| Field | Value |
|---|---|
| Version | v0.9.0 |
| Installer | `Snapmaker.Studio_0.9.0_x64-setup.exe` |
| Size (bytes) | 17,100,560 |
| SHA256 | `294f7d25d8b1ef0f3fe26df9f83df6fa7482fa86aa998928db2a40335b4d202b` |
| Release URL | https://github.com/DeadlyVirusIn/snapmaker-studio/releases/tag/v0.9.0 |

## Superseded

| Field | Value |
|---|---|
| Version | v0.8.0 |
| Installer | `Snapmaker.Studio_0.8.0_x64-setup.exe` |
| Size (bytes) | 17,011,290 |
| SHA256 | `67776cd1db9f620d3c38e656bf831b0f976e0669ce91398caa998e40cf929af6` |
| Release URL | https://github.com/DeadlyVirusIn/snapmaker-studio/releases/tag/v0.8.0 |

## Superseded

| Field | Value |
|---|---|
| Version | v0.7.2 |
| Installer | `Snapmaker.Studio_0.7.2_x64-setup.exe` |
| Size (bytes) | 16,980,253 |
| SHA256 | `23298efe76a91dab6c026fab49f48d6c953c89cac587c8f76337e9de2ee47d0c` |
| Release URL | https://github.com/DeadlyVirusIn/snapmaker-studio/releases/tag/v0.7.2 |

## Superseded

| Field | Value |
|---|---|
| Version | v0.7.1 |
| Installer | `Snapmaker.Studio_0.7.1_x64-setup.exe` |
| Size (bytes) | 16,969,943 |
| SHA256 | `dddd577dcbd958794f43050c2f1b49687e26952ee0a7ef81c8ff6c04872f5baa` |
| Release URL | https://github.com/DeadlyVirusIn/snapmaker-studio/releases/tag/v0.7.1 |

## Superseded

| Field | Value |
|---|---|
| Version | v0.7.0 |
| Installer | `Snapmaker.Studio_0.7.0_x64-setup.exe` |
| Size (bytes) | 16,971,405 |
| SHA256 | `2a13d73ac19af8dc0457dbead54a2f83c14c83b1d8f74d9746950e3f7b804fbc` |
| Release URL | https://github.com/DeadlyVirusIn/snapmaker-studio/releases/tag/v0.7.0 |

## Superseded

| Field | Value |
|---|---|
| Version | v0.6.2 |
| Installer | `Snapmaker.Studio_0.6.2_x64-setup.exe` |
| Size (bytes) | 16,923,818 |
| SHA256 | `687eabdddff714a614c94f46aa6a4a6a95d0e8a444fbc194c085d8ed9ee740de` |
| Release URL | https://github.com/DeadlyVirusIn/snapmaker-studio/releases/tag/v0.6.2 |

## Superseded

| Field | Value |
|---|---|
| Version | v0.6.1 |
| Installer | `Snapmaker.Studio_0.6.1_x64-setup.exe` |
| Size (bytes) | 16,927,507 |
| SHA256 | `b062ac52e6e935e79267cbd00aee859c3eb39b768f14a6be3856f944472bdb7b` |
| Release URL | https://github.com/DeadlyVirusIn/snapmaker-studio/releases/tag/v0.6.1 |

## Superseded

| Field | Value |
|---|---|
| Version | v0.6.0 |
| Installer | `Snapmaker.Studio_0.6.0_x64-setup.exe` |
| Size (bytes) | 16,900,712 |
| SHA256 | `e85c18a8589574e107e019d99c504fa5f6ccf15f65fd35416b67e0ec3eff461f` |
| Release URL | https://github.com/DeadlyVirusIn/snapmaker-studio/releases/tag/v0.6.0 |

## Superseded

| Field | Value |
|---|---|
| Version | v0.5.0 |
| Installer | `Snapmaker.Studio_0.5.0_x64-setup.exe` |
| Size (bytes) | 16,871,622 |
| SHA256 | `73124b2162ea3581db3237b4e9400d3cb4b9a339bc3bdafb9e5a793c336cf12c` |
| Release URL | https://github.com/DeadlyVirusIn/snapmaker-studio/releases/tag/v0.5.0 |
