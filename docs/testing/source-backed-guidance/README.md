# Source-backed guidance: screenshots

These screenshots show the "Adjusted for U1 project compatibility" notes in the Prepare summary after
this change. Each changed setting now carries a short plain-language reason and a label for where the
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
