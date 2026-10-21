# Snapmaker Studio v1.6.0 — A job you can pick up again, and sizes Studio will not guess

> **Independent open-source project — not affiliated with or endorsed by Snapmaker.**
> "Snapmaker" is a trademark of its respective owner.

This release keeps a job's files together so you can pick it up after a restart, says "not checked" when it
cannot establish a model's real size, makes printer setup explicit, and prepares more projects made in Bambu
Studio.

## A job you can pick up again

- **This job keeps its project, prepared copy and sliced G-code together.** After a restart Studio shows what
  it recorded, checks the files only when you ask, and reopens only what is unchanged (plus a changed file you
  name).
- **Every file says where it stands:** recorded, checked, reopened or left out. A file that was not reopened
  keeps its old fingerprint, labelled as the earlier record. A saved fingerprint is history, not proof that a
  file was reopened or is unchanged.
- **A settings receipt on After slicing** for the original, the prepared copy and the sliced file, with the
  sliced file's settings read strictly from its G-code.
- **Refreshed Home, This job and After slicing screens.**

## Explicit printer setup

- A profile with no printer address is "not set up" until you save one in Settings. Studio no longer looks up
  `U1.local` on its own, and "Not set up" and "Could not reach <address>" are different messages.
- The address you type is a draft until you press Save.
- Printer controls are unchanged: Studio does not contact a printer on its own until you set one up, and anything that controls it
  still waits for your confirmation. Studio never starts a print by itself.
- The interface loads no fonts from the internet. Studio says your files and checks stay on this computer. Studio does not contact a printer on its own until you set one up, and features you start yourself (the
  update check, the model browser, Auto-detect) can reach beyond this computer.

## Sizes Studio will not guess

Bed fit, the readiness "Fits the print bed" check, the print-success estimate, the first-layer footprint checks
and the Scale Doctor used the raw numbers stored in a 3MF mesh. A file that declares inches, or that rotates or
scales its objects through a placement transform, could be reported at the wrong size.

Studio now first decides whether those numbers are the physical size. When that is not established, each of
these says **"not checked"** and why, instead of a verdict, and a project whose bed fit is not checked does not
show as ready. STL files are unchanged (assumed millimetres).

**Not covered yet:** the Object placement card and layout still read raw coordinates; volume, material and cost
for files that declare a non-millimetre unit are not corrected; declared units are not converted; and a
near-identity scale can be labelled "rotated".

## More projects prepare — and refusals are plain

- Six more per-object settings from Bambu Studio projects are kept when Snapmaker Orca 2.4.0 reads them in the
  same words: infill pattern, skeleton and skin infill density, top and bottom shell layers, and brim type. Every
  value is checked first; anything else is still refused rather than guessed.
- A project that uses the same part more than once in one object is no longer refused as corrupt.
- A project Studio can read but would refuse to prepare is called that everywhere — the Doctor, Ready Now, the
  library, the Validation Center and the command line — and points you to review the original in Snapmaker Orca.
  When Prepare refuses a file, the message says which settings or structure, on which object, and what to do next.
- Preparing a copy no longer leaves a `<name>.orig.3mf` file beside your original. Your original is never modified.
- A project with blank (`nil`) per-part values is named in plain language and not prepared. This is a precaution:
  opening such a file in the Snapmaker Orca 2.4.1 interface did not show it failing to load, so Studio does not
  claim that blank values stop Orca from loading a file.

## What was checked, and what was not

Snapmaker Orca 2.4.1 opened prepared copies of test projects in an isolated profile. **That is loading only:**
nothing was sliced and nothing was printed. Four of the six newly kept per-object settings showed their prepared
values there; the two infill densities could not be located in the interface and are not confirmed. A repeated
part loaded and listed its parts.

Read-only checks against a real Snapmaker U1 passed (78/78), including the Spoolman- and Bambuddy-seeded provider
checks, with no printer-control action called. This printer's four toolheads all carry the same 0.4 mm nozzle, no
real SpoolEase device has been tested, and the Linux-installed app was not run against the real printer.

**Known limitation.** Copies prepared from Compatibility may not appear in This job or the Prepared copy column of the settings receipt. The receipt can still compare the original project with sliced G-code. A fix is planned for the next patch.

Studio is advisory. It does not slice, it does not promise a successful print, and anything sent to your printer
is something you confirm.

## Verify your download

- Windows: `Snapmaker.Studio_1.6.0_x64-setup.exe` — 22,444,501 bytes — SHA256 `d39b1321579376bb7b804531c25343c22dde109889e4a44a7639122ecf0a98f0`
- Linux: `snapmaker-studio_1.6.0_amd64_ab507e531bb8.deb` — 26,004,974 bytes — SHA256 `aaf13a23becc624ffff04d4fd4e317b886b81fa82c7b61c44f6075ea2cd62cfc`

Neither installer is code-signed yet; verify the hash before you run it. Verification for this
release is in
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.6.0/docs/TRUST_STATUS.md).
