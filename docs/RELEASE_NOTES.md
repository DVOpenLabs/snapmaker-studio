# Snapmaker Studio v1.5.1 — clearer Prepare, honest plate and tower checks, easier spool choices, accessible controls

> **Independent open-source project — not affiliated with or endorsed by Snapmaker.**
> "Snapmaker" is a trademark of its respective owner.

A release on top of v1.5.0. More Bambu Studio projects now prepare, and when Studio cannot prepare one it says
why in plain words. Studio is more careful about what it claims for projects with several plates and for the
prime tower. Project Materials is easier to use with a real spool inventory, Prepare says why a setting changed,
and two screens work from the keyboard and with a screen reader. Your original files are still never modified,
Studio still does not slice, and it never starts a print without your confirmation. Studio is advisory: a copy
Studio prepares still needs a look in Snapmaker Orca before you slice, and none of this promises a successful print.

## Prepare: more projects, clearer answers

- **More Bambu Studio projects prepare.** Studio now keeps six more per-object settings that Snapmaker Orca 2.4.0
  reads in the same words: infill pattern, skeleton and skin infill density, top and bottom shell layers, and
  brim type. Every value is checked first, and anything else is still refused rather than guessed.
- **A part used more than once in an object no longer counts as corrupt.** A real mismatch between the parts and
  the object is still refused.
- **When Studio refuses a file, it says why in plain language** — which settings or structure, on which object —
  and what to do next. The technical wording is kept in a collapsed "Technical details" area.
- **Files Studio will not prepare are marked everywhere.** The Doctor, your library, the Dashboard and Projects
  lists, Ready Now, the Compatibility check, the Validation Center and the command line all say "Review in Orca
  first" instead of calling the file ready or sending it to Prepare.
- **Projects with blank values Snapmaker Orca 2.4.0 cannot read** are named in plain language instead of being
  passed on.
- **No `.orig.3mf` file is left beside your original.** The original was never modified; the extra copy was only a
  leftover. The command-line `repair` and `optimize` commands still keep their snapshot.
- **Prepare says why a setting changed**, and whether the statement is Studio's own check or advice to verify in
  Snapmaker Orca.

## Plates, objects and the prime tower: what Studio checks, and what it does not

- **Several plates from a printer with a different plate size.** When every object's whole footprint lies inside
  the plate area its project names for it, Studio lays each plate's objects out on the U1's plate grid (moves
  only; rotation, scale and painting untouched), in both modes. Otherwise nothing is moved and the copy says why.
- **No false green for multi-plate projects.** Studio checks that each plate fits the U1 on its own. It does not
  check where the plates sit, so the Object placement card, Ready Now and the Project Doctor say that Snapmaker
  Orca can still list an object as Outside and to review the project there.
- **A prime tower outside the printable area is reported, never moved.** Both modes keep your project's own tower
  position. Studio does not estimate how far a tower reaches; any other tower is "not verified".
- **Studio no longer recommends Arrange as a remedy.** Every message and guide page now says to review the project
  in Snapmaker Orca before slicing.
- **Plate count comes from the plates the project declares**, so a project with several plates is no longer counted
  as one, and a prepared copy is no longer reported as not validated because the count appeared to drop.
- **Bed fit and placement.** Each object's size and the instances' placement are reported separately, several small
  separated objects are no longer summed into one "too big" object, and each placed copy of a repeated object is
  judged on its own.
- **"Use Studio's U1 starter settings instead" keeps your support settings** when the model itself marks where it
  needs support. When the model marks nothing, the Prepare summary tells you before you open the copy that
  Snapmaker Orca will open with supports off.

## Project Materials

- **Choose any spool from your inventory.** Each slot can open your provider's whole spool list, searchable by
  vendor, material, colour or id, showing colour, vendor, material, spool id, weight status and the status of the
  mapped Orca preset.
- **Studio says when a spool leaves the preset alone.** If you pick a spool but no Orca preset, the slot and the
  review say the project's existing filament preset will remain.
- **Forget a saved mapping.** The confirmation says what is forgotten and what is not changed (your inventory,
  your Orca presets and the project).
- **A saved-mappings file that is briefly locked is no longer treated as damaged.** Studio retries, and if it still
  cannot read the file it changes nothing and asks you to try again.

## Easier to use with a keyboard or screen reader

- **Printer actions.** The confirmation for Start, Cancel print and Emergency stop is a proper dialog: it has a
  name and description, starts on **Cancel**, and Escape only dismisses it. It names the printer (and the file for
  Start) and is withdrawn if the printer changes or can no longer take the action.
- **Tool tabs.** The tab rows for Compatibility / Source Check and Print Quality / First Layer work with the arrow
  keys, Home and End, show a clear focus outline, and wrap on narrow windows.

## User guide

- The in-app Help and Get Started pages link to the task-first user guide, which shows where each statement comes
  from and which version of Studio it was checked against. Its screenshots were captured from v1.5.0 and have not
  been retaken.

## Known limits

- Studio does not move objects between plates, does not move the prime tower, and does not rearrange a project's
  plates beyond the move described above. For a project made for a printer with a larger bed that Studio cannot
  re-grid, the objects keep the creator's positions, so Snapmaker Orca can list an object as Outside even when its
  plate fits. In our test, Arrange all plates did not fix it; the object had to be moved by hand.
- Both modes keep your project's own prime tower position, which can lie outside the U1's printable area when the
  project was made for a larger bed. Studio says so but does not move it. Whether Snapmaker Orca keeps that position
  when it opens a copy prepared with the starter settings has not been verified.
- The starter-settings mode resets a multi-nozzle flush table to zeros. Check the tower in Orca's preview and open
  Flushing volumes if you use them.
- Opening a copy in Snapmaker Orca is not a slice, and a slice is not a print. Studio does not slice and cannot
  promise a successful print.

## Verify your download

- Windows: `Snapmaker.Studio_1.5.1_x64-setup.exe` — 22,558,688 bytes — SHA256 `736469c9d3c6a08e2e01908027e39586730ce3b96830503f38d45f5f05b693fc`
- Linux: `snapmaker-studio_1.5.1_amd64_f0c0cd533627.deb` — 26,119,328 bytes — SHA256 `d7f7671e9acfaa861f31e6c9f0cbdad1f05a1c334825d95aef1d949b49593c53`

Neither installer is code-signed yet; verify the hash before you run it. Verification for this
release is in
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.5.1/docs/TRUST_STATUS.md).
