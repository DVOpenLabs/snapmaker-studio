# Project Materials: usage notes, beyond-toolheads note, foreign-preset sentence

Real-browser check (Microsoft Edge, Chromium, headless; dark and light) of the read-only additions for #39. Script:
`tools/acceptance/materials-usage.mjs` (Windows; run with `--out <folder>`). **17/17 checks passed**, see [results.json](results.json).

## What is real and what is not

- **Real:** the Studio engine and web UI from this branch, running locally, in Edge.
- **Fixture, not the reporter's data:** an anonymous Spoolman look-alike on `127.0.0.1:7912` with five invented spools, and two
  invented five-colour projects (one readable, one whose object list is not well-formed). Nothing comes from the reporter's
  SpoolEase, spools or files.
- **Fail-closed:** any engine request naming another provider, a printer, or discovery fails the run; none occurred.

## Not run

- The packaged Tauri window (this is the web UI in Edge, not the shipped app).
- WebKitGTK / Linux.
- Snapmaker Orca: no prepared copy was opened in Orca, so whether the `nozzle_volume_type` removal makes the
  "newer version, values replaced" notice go away is **not confirmed**.
- A real SpoolEase, Spoolman or Bambuddy instance; a screen reader.

## Evidence

| Screenshot | Shows |
|---|---|
| `01-five-colours-*` | Five colours: "5 materials, 1 beyond the U1's 4 toolheads" note and per-slot usage lines (page cut off by the long candidate lists) |
| `01b-slot-5-no-reference-*` | The fifth slot: "found no object, part, colour change or setting ... does not prove it is unused, and Studio does not remove it"; no remove or merge control |
| `02-spool-without-preset-bambu-*` | A spool chosen on a slot whose preset is a Bambu one: the existing sentence, the caveat, then how to choose a Snapmaker preset |
| `03-unreadable-project-*`, `03b-slot-5-unknown-*` | Unreadable object list: colours nothing else references stay "Studio cannot tell", never "unused" |
