# P4 — Palette calibration

**Evidence: fixture-tested.** Palette parsing and color comparisons use synthetic fixtures. No printer, physical calibration target, or measurement device was used.

Calibration accepts DitherForge TXT rows (`#RRGGBB td label`, with `td=<number>` also accepted) and Kromacut palette JSON v2. A missing TD becomes `1.0` with `derived` provenance and is shown in the UI as **nominal, not measured**. Unrecognized Kromacut versions remain opaque and are not evaluated.

Every comparison has a frontlit or backlit basis. The basis ID hashes its family, layer height, nozzle size, and material, so frontlit and backlit inputs never share an ID. A changed layer height creates a different basis; prior runs remain in the local `calibration` store and each run exposes its `inputs_revision`.

Palette targets are labeled simulated. Optional physical color readings are kept in a separate field. Owned-filament colors use the existing `material_plan.colour_distance` calculation and are displayed as advisory alternatives only; this is a simple RGB distance, not a perceptual or print guarantee.

The UI accepts pasted text or a local `.txt` / `.json` file. File contents are read in the browser and posted only to Studio's loopback API. No external service or printer connection is used.

## P4 acceptance status

1. DitherForge TD forms and the derived default: **DONE**.
2. Kromacut v2 decode; other versions unknown: **DONE**.
3. Frontlit and backlit basis separation: **DONE**.
4. Layer-height change invalidates via a new basis and `inputs_revision`; prior history retained: **DONE**.
5. Physical and simulated values remain separate: **DONE**.
6. Owned-filament alternatives use `material_plan.colour_distance` and advisory labels: **DONE**.
7. The `calibration` store uses `open_store`; newer versions are refused without replacing data: **DONE**. Failed-migration rollback is provided by the shared store transaction contract; P4-specific rollback injection was not added.
8. Immutable `calibration_basis_id` is exposed in each result and included in `inputs_revision`: **DONE**.

Limitations: palette JSON v2 support is limited to the documented `{version: 2, palette: [{label, color, td?}]}` shape. Physical readings are manually entered values; the app does not measure color. History stores evaluated runs locally, but the current screen does not yet provide a history browser.
