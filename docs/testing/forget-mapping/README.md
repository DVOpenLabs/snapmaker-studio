# "Forget saved mapping" in Project Materials: browser check and screenshots

Real Studio engine and this branch's own web UI, driven in **Microsoft Edge (Chromium, headless)** by
`tools/acceptance/forget-mapping-ui.mjs`. All data is made up: an anonymous Spoolman look-alike with five invented spools, a
throwaway preset folder with three invented Snapmaker-style presets, and one empty anonymous 3MF named `example-project.3mf`. Two
saved mappings were written through the engine's own route (one for a single spool, one for a kind of spool). Nothing can reach a
printer, a real provider or an Orca install; any engine request naming another provider address, a printer or discovery is
aborted and fails the run.

**Result: 33/33 checks passed** on the build with #85, #87 and the #89 read-error fix together (`results.json`; #87 alone passes its 26). The saved-mapping file the engine writes is read back after each step to prove what
was, and was not, removed.

| Screenshot | What it shows |
|---|---|
| [01](01-saved-mappings-with-forget.png) | Project Materials with two kinds of saved mapping: "Forget saved mapping" on a spool-specific one, "Forget saved mapping (similar spools)" on the two spools a kind-wide one covers. Nothing is forgotten by merely looking. |
| [02](02-confirmation.png) | The confirmation: named, says which mapping and which preset, says the inventory, Orca presets and project are not changed, and that a mapping saved for similar spools may still apply. Focus is on Cancel. |
| [03](03-failed-removal.png) | A removal whose reply is lost (simulated server error): reported as "Couldn't confirm", not as done; the list is read again and the mappings are still there. |
| [03b](03b-saved-mappings-unreadable.png) | The engine cannot read its saved mappings (another program holds the file; held for real with a byte-range lock): reported as "could not read ... Nothing was changed. Try again in a moment.", not as corruption. The file is byte-identical afterwards and no `.damaged` file exists. The list is left as it was. |
| [04](04-after-forgetting-one-spool.png) | After a real removal: only that mapping left the engine's file, the list was read again, and a chosen spool that rested on a different mapping kept its choice. |
| [05](05-confirmation-similar-spools.png) | The kind-wide confirmation: reaches every such spool, and a spool with a mapping of its own keeps it. |
| [06](06-after-forgetting-similar-spools.png) | After forgetting the kind-wide mapping: the choice that rested on it is cleared and the note says which slot. |

Also checked and passing: Cancel and Escape remove nothing and return focus to the control that opened the prompt; a refused
removal ("That saved mapping has changed since it was shown. Nothing was forgotten.") is shown plainly and removes nothing; the
request names exactly one mapping and the preset that was shown; focus is never lost to the page body.

On a build that also has the inventory picker (#85), the script additionally chooses a spool through "Choose another spool" and checks
that forgetting the mapping it rested on clears that choice.

Not covered: the Tauri window, WebKitGTK, a screen reader, and a real Spoolman/SpoolEase device.

Run it: `PYTHON=py node tools/acceptance/forget-mapping-ui.mjs --out <folder>` (needs Edge and `npm install` in `tools/acceptance`).

[07](07-picker-choice-selected.png) shows a spool chosen through the inventory picker (#85) before its saved mapping is forgotten.
