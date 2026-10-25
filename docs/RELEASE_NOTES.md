# Snapmaker Studio v1.7.0 (release candidate) — One job screen, print risk signals and a colour preview

> **Independent open-source project — not affiliated with or endorsed by Snapmaker.**
> "Snapmaker" is a trademark of its respective owner.

> **Release candidate — not published.** These notes describe the candidate named in
> [RELEASE_METADATA.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.7.0/docs/RELEASE_METADATA.md). No v1.7.0 tag, GitHub release or download exists yet. Until one
> does, the published release is v1.6.0.

This release puts a project on one job screen, replaces the readiness percentage with a list of the risks Studio
found, draws a read-only colour preview, tightens the checks that decide whether a project fits the plate, and
updates the update check's TLS dependencies.

## One job screen

- **Opening a project lands on one screen:** the model in the middle, the target, materials and copy settings in a
  pane beside it, and a single button for the next step (create the U1 copy, open it in Snapmaker Orca, compare the
  slice). The copy's file name and folder, and the settings comparison after slicing, appear in the same place.
- Opening or restoring a job never prepares, opens Orca or slices by itself, and every existing check still applies.

## A colour preview

For a millimetre 3MF, Studio draws the model by the filament that prints each part, links each filament to its
toolhead, and lets you compare the project's own colours, the spool colours you have chosen so far, and the colours
read back from the copy Studio wrote. It is read-only. More than four colours stay visible, each in its own colour;
Studio does not remove or merge them. Surface the project does not assign is shown grey. When a preview cannot be
built (another unit, an unreadable file, too much detail, no 3D graphics) Studio says why and shows the plate
instead.

## Print risk signals replace the readiness percentage

The "Print readiness (estimate)" percentage, the star rating and the Studio score are gone. Studio now lists each
risk it found, once per condition, with what it means and what to do, and says what it did and did not check.
Community guidance attaches only to the conditions it actually fits.

## Placement and size checks say what they did not check

- Bed fit reports each object's size and the instances' placement as separate facts; several small, separated
  objects are no longer summed into one "too big" object.
- A copy of a repeated object that hangs off the plate is no longer hidden by one that does not.
- Placement and plate-fit checks are reported as **not checked** for projects whose physical size the file does not
  establish (a non-millimetre unit, or a rotated or scaled object).
- A project with several plates is no longer called ready just because each plate fits on its own.
- Studio no longer recommends Arrange all plates as a fix; it says to review the project in Snapmaker Orca before
  slicing.
- When the bed-fit check could not run, the report says it was not verified instead of reading as a clean result.
- Each setting Studio adjusts when it prepares a copy says why, and labels whether that statement is Studio's own
  check or advice to verify the setting in Snapmaker Orca. The labels make no claim about how Snapmaker Orca behaves.
- The cost line in the Business Doctors says "estimated cost".

## Security

- The update check's TLS dependencies are updated (rustls 0.23.46, rustls-webpki 0.103.16), and it no longer trusts
  the `emSign ECC Root CA - G3` root that webpki-roots 1.0.10 removed (RUSTSEC-2026-0381, the October 2026 eMudhra
  disclosure).
- The update check only follows `releases/latest` and `releases/tag/<tag>` links of this repository.
- If you build Studio from source, Node.js 22.23.4 or a newer fixed line is required.

This does not change what is already installed: people running an earlier release still have its binary until they
install a newer one.

## What was checked, and what was not

The candidate was built once by the project's release-candidate workflow. Its Windows installer and Linux `.deb`
were re-downloaded and checked by SHA256 against the build manifest. The Windows installed-application acceptance
run used an **acceptance copy** of the installer (same application files, separate install identity) on a clean
local account and passed 54/54; that run includes an upgrade from an acceptance copy of v1.6.0, which is **not** a
production upgrade. The real installer's own install, upgrade and uninstall were exercised only on a disposable
GitHub-hosted runner. The Linux package passed its in-container acceptance run and clean-environment validation on
Ubuntu 22.04 and 24.04 (49/49 each).

**Not run for this candidate:** read-only verification against a real Snapmaker U1, the Snapmaker Orca interface
checks, and any real SpoolEase device. Provider checks ran against local mock servers only. Whether a prepared copy
opens correctly in Snapmaker Orca was not re-checked for this candidate.

Studio is advisory. It does not slice, it does not promise a successful print, and anything sent to your printer
is something you confirm.

## Verify your download

These values are for the release candidate. They apply to a v1.7.0 download once it is published; the candidate has
no public download.

- Windows: `Snapmaker.Studio_1.7.0_x64-setup.exe` — 22,748,251 bytes — SHA256 `71c91b0c2cf2ec41d80bc75bff828ff6b35d6ff3fd93764b894676ec9d360b04`
- Linux: `snapmaker-studio_1.7.0_amd64_210d86868882.deb` — 26,325,960 bytes — SHA256 `2af5ceb2f6b08e4f732df8457924ea7e9135c7f9408dda41c688c189298ccabc`

These values repeat the canonical record in
[RELEASE_METADATA.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.7.0/docs/RELEASE_METADATA.md) on purpose:
this file becomes the GitHub release body, and a downloader must be able to verify a hash without opening a second page.

Neither installer is code-signed yet; verify the hash before you run it. Verification status for this candidate is
in [TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.7.0/docs/TRUST_STATUS.md).
