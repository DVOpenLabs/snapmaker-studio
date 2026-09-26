# Code signing policy

Snapmaker Studio is an independent, MIT-licensed open-source project maintained in
public at <https://github.com/DVOpenLabs/snapmaker-studio>.

This page exists because signing programs for open-source projects require the
project to publish who can release code and how. It is also simply useful: anyone
downloading an installer should be able to see how it was produced.

## Project

| | |
|---|---|
| Name | Snapmaker Studio |
| Repository | <https://github.com/DVOpenLabs/snapmaker-studio> |
| Licence | MIT |
| Distribution | GitHub Releases, free of charge |
| Platforms | Windows 10/11 x64; Linux x86_64 (`.deb`) |

## Team and roles

| Role | Who | Responsibility |
|---|---|---|
| Author | Kunal Khurana (@DeadlyVirusIn) | Writes and commits code |
| Reviewer | Kunal Khurana (@DeadlyVirusIn) | Reviews changes before release |
| Approver | Kunal Khurana (@DeadlyVirusIn) | Approves a signing request for a release |

This is a single-maintainer project; the same person holds all three roles.

SignPath Foundation requires that "all team members must use multi-factor
authentication for both SignPath and source code repository access". No signing
service account exists yet, so this page does not claim one is protected. **The
maintainer must confirm MFA is enabled on the GitHub account and enable it on the
SignPath account at creation**; this sentence is replaced with a statement of fact
once both are true.

## How a release is produced

1. Every change lands on `main` through the checks in
   `.github/workflows/ci.yml`: the Python engine suite, the end-to-end
   `u1convert selfcheck`, the desktop unit tests, `tsc --noEmit`, a production
   Vite build, and `cargo check`.
2. The Windows installer is built from that source with
   `npm run release:windows`, which freezes the Python engine with PyInstaller
   and bundles it with the Tauri shell into an NSIS installer.
3. Installed-build acceptance runs against the produced installer
   (`tools/acceptance/run.ps1`) — install, launch, drive the real UI, uninstall,
   verify cleanup.
4. The installer's SHA256 is recorded in
   [docs/RELEASE_METADATA.md](RELEASE_METADATA.md) and published on the release.
5. Verification state for the build is recorded in
   [docs/TRUST_STATUS.md](TRUST_STATUS.md), which distinguishes automated checks
   from ones still pending.

Binaries are built only from this repository's own source.

## What ships in the installer

- `snapmaker-studio-desktop.exe` — the Tauri shell, built from `desktop/src-tauri`.
- `snapstudio-api.exe` — the Python engine from `backend/`, frozen with
  PyInstaller.
- An NSIS uninstaller.

No third-party proprietary component is bundled. Third-party dependencies are the
declared packages in `desktop/package.json`, `desktop/src-tauri/Cargo.toml` and
`backend/pyproject.toml`. Snapmaker Orca is *not* bundled — Studio launches it if
the user has installed it separately. See
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Privacy

Snapmaker Studio runs entirely locally. It has no account, sends no telemetry, and
uploads nothing. It reads files the user opens and, when the user configures a
printer address, makes read-only requests to that printer on the local network.
See [docs/SECURITY.md](SECURITY.md).

## Uninstall

Uninstall from Windows Settings → Apps, or run `uninstall.exe` in the install
directory. This removes the application and its sidecar; it is verified as part of
the acceptance run.

## Attribution

If code signing is provided by the SignPath Foundation, this project will display:

> Free code signing provided by [SignPath.io](https://signpath.io), certificate by
> [SignPath Foundation](https://signpath.org).

## Honest note on what signing changes

Signing an installer replaces the "unknown publisher" SmartScreen warning with one
that names a verified publisher, and begins accumulating SmartScreen reputation.
It does not remove the warning immediately —
[Microsoft's own documentation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
states that EV certificates no longer bypass SmartScreen either. Reputation builds
over clean installs. This project will not claim otherwise.

## Application to SignPath Foundation — prepared

Everything the Foundation asks for is written down. What remains is a form
submission that legally represents the maintainer, which is theirs to send.

**Apply at:** <https://signpath.org/apply>
**Terms (the eligibility list below is taken from them):** <https://signpath.org/terms>

### Eligibility, answered

| Criterion | This project |
|---|---|
| No malware | A local-first pre-print checker. No network egress in the pipeline, no telemetry, no account. |
| OSI-approved licence | MIT. |
| No proprietary code | None. Dependencies are declared in `desktop/package.json`, `desktop/src-tauri/Cargo.toml` and `backend/pyproject.toml`, and listed in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). |
| Maintained | Active; see the commit history and [CHANGELOG.md](../CHANGELOG.md). |
| Released in signable form | Windows NSIS installer, published on GitHub Releases with a SHA256. |
| Documented | [README.md](../README.md), [docs/windows-install.md](windows-install.md), [docs/ARCHITECTURE.md](ARCHITECTURE.md), and the verification record in [TRUST_STATUS.md](TRUST_STATUS.md). |
| Sign your own project only | Single maintainer; signing team and maintenance owner are the same person. |
| Sign your own binaries only | Built from this repository by `npm run release:windows`. |
| No hacking tools | Nothing in the product exploits or circumvents anything. The printer interface is read-only except for actions the user explicitly confirms. |
| Respect user privacy | No data transfer occurs except read-only requests to a printer address the user enters. See the Privacy section above and [SECURITY.md](SECURITY.md). |
| Announce system changes | The installer creates its own program directory and Start-menu entry, and nothing else. |
| Provide uninstallation | `uninstall.exe` and Windows Settings → Apps; removal is asserted by the acceptance harness. |
| Code signing policy published | This page. |
| Team roles listed | Above. |
| Attribution | Above; it will be displayed on the README and the release page once signing is active. |
| MFA on all accounts | **Outstanding — the one thing not yet true.** See the note under Team and roles. |

### Prepared form answers

- **Project name:** Snapmaker Studio
- **Project URL:** <https://github.com/DVOpenLabs/snapmaker-studio>
- **Licence:** MIT
- **Description:** A local-first desktop application that reads a 3D project file,
  explains the print risks it can prove, compares the project against the user's
  own Snapmaker U1 over the local network, prepares a corrected copy without
  modifying the original, and hands that copy to a slicer. No account, no cloud,
  no telemetry, and nothing sent off the user's local network.
- **Artifacts to be signed:** the Windows NSIS installer
  (`Snapmaker.Studio_<version>_x64-setup.exe`) and the two executables it
  contains, `snapmaker-studio-desktop.exe` and `snapstudio-api.exe`.
- **Build system:** GitHub, built from `main`; release build is
  `npm run release:windows` (PyInstaller + Tauri + NSIS).
- **Code signing policy URL:** this page.

### CI integration, once approved

Signing runs as a step in a release workflow, after the existing CI checks and the
installer build, using SignPath's GitHub Action with the project's signing policy
and an API token held as a repository secret. The token is never written to the
repository, and the workflow signs only the artifact produced by the build in the
same run.

### The irreducible step

Submitting the application at <https://signpath.org/apply> accepts terms on the
maintainer's behalf and requires their name and email. Enabling MFA on the
resulting account is the same kind of act. Nothing else about signing is
outstanding.
