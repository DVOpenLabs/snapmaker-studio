# Snapmaker Studio v1.5.1 — clearer Prepare, easier spool choices, accessible controls

> **Independent open-source project — not affiliated with or endorsed by Snapmaker.**
> "Snapmaker" is a trademark of its respective owner.

A small release on top of v1.5.0. It makes Project Materials easier to use with a real spool inventory,
says why Studio changed a setting, and makes two screens work properly from the keyboard and with a
screen reader. Your original files are still never modified, and Studio still does not slice or start prints.

## Project Materials

- **Choose any spool from your inventory.** Each slot can open your provider's whole spool list, searchable
  by vendor, material, color or id, showing color, vendor, material, spool id, weight status and the status
  of the mapped Orca preset.
- **Studio says when a spool leaves the preset alone.** If you pick a spool but no Orca preset, the slot and
  the review now say: "Spool selected, but no Orca preset selected. The project's existing filament preset
  will remain."
- **Forget a saved mapping.** A mapping Studio remembered for one spool, or for similar spools, now has a
  **Forget saved mapping** button. The confirmation says what is forgotten and what is not changed (your
  inventory, your Orca presets and the project).
- **A file Studio could not read is no longer treated as damaged.** If another program briefly holds the
  saved-mappings file, Studio now waits and retries, and if it still cannot read the file it changes nothing
  and tells you to try again. Before, a brief lock could cause the file to be set aside as damaged.

## Prepare: why a setting changed

- The Prepare summary now shows a short reason under each setting Studio changed for the U1, and labels where
  the statement comes from: **Studio's check** (Studio did or checked it itself) or **Verify in Snapmaker
  Orca** (advice to check it there; it makes no claim about how Snapmaker Orca behaves).
- Lists that Studio had to repair (for example one value per filament) say exactly what was done.

## Easier to use with a keyboard or screen reader

- **Printer actions.** The confirmation for Start, Cancel print and Emergency stop is now a proper dialog:
  it has a name and description, starts on **Cancel**, and Escape only ever dismisses it. It names the printer
  (and the file for Start) and is withdrawn if the printer changes or can no longer take the action.
- **Tool tabs.** The tab rows for Compatibility / Source Check and Print Quality / First Layer now work with
  the arrow keys, Home and End, show a clear focus outline, and wrap on narrow windows. Moving along the row
  does not open or re-run a tool; Enter, Space or a click does.

## User guide

- The in-app Help and Get Started pages link to the new task-first user guide, which now shows where each
  statement comes from and which version of Studio it was checked against.
- The guide's screenshots were captured from v1.5.0 and have not been retaken.

## Not in this release

- No change to what Studio writes into a prepared copy beyond the explanations above.
- No new printer actions. Studio does not start prints; anything sent to your printer is something you confirm.

## Verify your download

- Windows: `Snapmaker.Studio_1.5.1_x64-setup.exe` — 21,962,736 bytes — SHA256 `8955097365b12e9eb1405a098c1f6ab345d56d397681a67f0cb08257d1471be3`
- Linux: `snapmaker-studio_1.5.1_amd64_abf20bf0f74d.deb` — 25,954,272 bytes — SHA256 `c5766900437fa9826eefdb970c0ed21894b4f5f4b4795518993677ca6eeed08b`

Neither installer is code-signed yet; verify the hash before you run it. Verification for this
release is in
[TRUST_STATUS.md](https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.5.1/docs/TRUST_STATUS.md).
