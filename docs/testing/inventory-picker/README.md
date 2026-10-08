# "Choose another spool": keyboard and notice verification

Real-browser check of the Project Materials inventory picker, operated **only from the keyboard**, with anonymous made-up
data. Script: `tools/acceptance/inventory-picker-keyboard.mjs` (Windows; Edge/Chromium; run with `--out <folder>`).

**21/21 checks passed.**

## What is real and what is not

- **Real:** the Studio engine and web UI from this branch, running locally, in Microsoft Edge (Chromium).
- **Fixture, not the reporter's data:** an anonymous Spoolman look-alike on `127.0.0.1:7912` serving five invented spools,
  and two invented 3-slot projects (one naming a filament preset per slot, one naming none). Nothing here comes from the
  #39 reporter's SpoolEase, spools or files.
- **Not tested:** a real SpoolEase, Spoolman or Bambuddy instance; Orca opening a prepared copy; the Tauri window or
  WebKitGTK for this picker (the printer-confirmation prompt has its own Linux run in `../linux-webkitgtk-dialog`); a screen reader.
- **Fail-closed:** the run aborts any engine request naming another provider, a printer other than the loopback address,
  or network discovery. (An earlier run correctly blocked four `/preflight` requests that carried the
  default printer name; the script now seeds the loopback address first, as the other acceptance scripts do.)

## Per case

| Result | Case |
|---|---|
| PASS | Enter on 'Choose another spool' opens the list |
| PASS | focus moves to the search box |
| PASS | the search box narrows the list from the keyboard |
| PASS | Tab reaches the PETG spool row |
| PASS | Enter on a different-material spool asks for confirmation and selects nothing |
| PASS | the engine's warning is shown |
| PASS | focus moves to Cancel, the safe answer |
| PASS | Escape cancels the confirmation |
| PASS | nothing was selected by cancelling |
| PASS | focus returns to the spool row after Escape |
| PASS | Enter on Cancel closes the confirmation and keeps the list open |
| PASS | focus returns to the spool row after Cancel |
| PASS | Shift+Tab reaches 'Use this spool anyway' |
| PASS | only after confirming is the spool selected |
| PASS | the list closes once a spool is chosen |
| PASS | focus returns to 'Choose another spool' |
| PASS | the no-preset notice names the project's existing preset |
| PASS | with no existing preset the notice does not claim one will remain |
| PASS | no request named another provider, a printer, or discovery |
| PASS | the provider look-alike was read and never written |
| PASS | no unexpected console errors |

Evidence: [results.json](results.json), [picker open](01-picker-open-keyboard.png),
[material warning](02-material-warning-keyboard.png), [spool selected with the no-preset notice](03-selected-with-notice.png),
[project with no existing preset](04-no-existing-preset.png).

## Scope note

The expanded colour-reference inspection (object, part, painted, colour-change, process-role and sliced-usage evidence) lives
only in the read-only `snapstudio_core.project_compare` support tool. The app's normal colour analysis (Colours & Materials
and the colour plan) is unchanged by this work.
