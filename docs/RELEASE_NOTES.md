# Snapmaker Studio v1.5.0 — Project Materials

> **Independent open-source project — not affiliated with or endorsed by Snapmaker.**
> "Snapmaker" is a trademark of its respective owner.

Which real spool is in which colour slot, and which installed Snapmaker Orca preset goes with it,
is now part of preparing a project (#39). Studio shows what the model asks for, suggests spools from
your inventory, and writes your choices into a prepared copy. You pick every one of them.

**Model → the materials and colours it needs → suggested spools from your inventory → the installed
Orca preset you confirm → review → Prepare.**

## Project Materials

- **It appears on Prepare whenever the project has filament slots**, whether or not the
  compatibility check found anything. Nothing on the page waits for a check result.
- **Top spool candidates, with the reasons.** For each slot Studio lists the best three spools
  from your provider (Spoolman, SpoolEase or Bambuddy) and says why: material match, whether the
  subtype could be compared, colour distance, and whether the filament left looks like enough
  (always marked as an estimate Studio cannot fully trust).
- **Nothing is chosen for you.** No spool is selected automatically and no preset is confirmed
  silently. Studio may suggest a generic preset; it never applies one on its own.
- **You choose the physical spool**, then the installed Orca preset for it. The spool's colour is
  carried into the prepared copy.
- **Remember a mapping** for one spool or for similar spools. It is saved only after the prepared
  copy was actually written, and it is checked again every time: a preset that was deleted,
  renamed, replaced or no longer fits is not applied.
- **Review before Prepare.** A plain-language summary lists, per slot, what was mapped, what
  changed, what was kept and what the preset controls. Spool details are labelled as what you
  selected, not as read from the file.
- **Same-preset safety.** Snapmaker Orca copies a declared value to every slot that uses the same
  preset. Studio removes only its own declarations from such a group, and stops (writing nothing,
  and saying why) if the project's own vendor or type declarations would be copied onto a slot they
  do not belong to.
- **Recommended mode no longer silently writes the legacy "Snapmaker PLA" preset.** A slot keeps
  the project's own filament identity unless you confirmed an installed preset for it.

## Snapmaker Orca's own presets

Studio reads the filament presets installed with Snapmaker Orca and can check each one against the
U1 and your nozzle size. A preset Studio verifies that way is shown as **Proven**, and a confirmed
Orca preset is the verified path: Snapmaker Orca applies its temperature, flow and cooling.

## Presets you made yourself — an important limit

- Studio can find compatible filament presets you created in Snapmaker Orca, map a spool to one,
  and remember that mapping.
- They are shown as **"Confirmed by you"** and **"Manual check in Orca required"**, never as Proven.
- In testing, when Snapmaker Orca opened a project that names a preset someone made, it kept the
  project's own values and showed the preset as modified, rather than applying the preset's own
  temperature, flow and cooling (in one profile it also showed a "Customized Preset" prompt).
- **Studio therefore does not say Orca will apply those values.** Check the filament in Snapmaker
  Orca before slicing.

## Not in this release

- Creating custom Orca presets.
- Changing or decrementing anything in your spool provider.
- Choosing a spool for you.
- Writing print parameters of its own.
- Keeping a project's arbitrary print parameters underneath a different preset.

Studio does not slice and does not start prints: Snapmaker Orca slices, and anything sent to your
printer is something you confirm.

## Verify your download

- Windows: `Snapmaker.Studio_1.5.0_x64-setup.exe` — 21,944,474 bytes — SHA256 `d443f64f5167239f1422c719882cf245cff5d00d40c55fb67fc5a1e497b84e82`
- Linux: `snapmaker-studio_1.5.0_amd64_5245cf9f9664.deb` — 25,944,098 bytes — SHA256 `7fca28d9d4e2558f8a6bdc765b121e2290c54abd39e2a1b9b2efaeea6d923e5a`

Neither installer is code-signed yet; verify the hash before you run it. Verification for this
release is in
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.5.0/docs/TRUST_STATUS.md).
