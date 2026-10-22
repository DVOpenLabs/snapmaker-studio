# Source-backed guidance: screenshots

These screenshots show the "Adjusted for U1 project compatibility" notes in the Prepare summary as first
implemented. They were captured before a later review repair and have not been recaptured: the Exclude Object
note in them still reads "the original had it off", which is withdrawn. The current wording is "the original did
not have it turned on" (the file may simply not mention the setting), and the nozzle volume type note now
describes only what Studio did. Treat the screenshots as showing the layout and source labels, not the final text.

Each changed setting now carries a short plain-language reason and a label for where the
statement comes from:

- **Studio's check** - Studio did or checked this itself (for example a value outside its valid range was
  replaced with the U1 default).
- **Verify in Snapmaker Orca** - advice to check the setting in Snapmaker Orca. It makes no claim about how
  Snapmaker Orca behaves.

Files: `prepare-notes-top-*`, `prepare-notes-bottom-*` and `prepare-compat-section-full-*`, each in light and
dark themes. The project and settings are a synthetic local fixture; no real printer, address or model name
appears.

## How they were captured

Edge via Playwright against the local Vite dev server, with web fonts and off-machine hosts blocked.
The capture script reported no violations and no console errors (React SVG attribute warnings from the
sidebar are unrelated and ignored).

## Not verified

- The packaged Tauri window on Windows and Linux WebKitGTK; only Edge was used.
- Screen-reader output.
- Snapmaker Orca behavior. The labels never assert it.
- One older sentence outside this change (`preset_deviation.py`: "declared to Snapmaker Orca, which resets an
  undeclared value...") still describes Orca behavior. It is unchanged here and left for a separate review.
