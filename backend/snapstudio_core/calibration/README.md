# Palette calibration input and history

DitherForge TXT accepts `#RRGGBB 1.9 Label`, a label without TD, and the
`td=1.9` form. Lines starting with `# `, `;` or `//` are comments. Missing TD
is explicitly nominal (1.0), never a measurement. Invalid or conflicting TD
is not replaced with a nominal value. The earlier Studio `td Label` syntax
remains readable for compatibility.

Kromacut v2 `.kpal` files are JSON objects with `version: 2`, `colors`,
optional `colorNames` and optional `disabledColors` indices. Indices remain
in their original positions. Disabled colours are shown but receive no
physical reading or owned-filament suggestion. The earlier Studio `palette`
row representation remains readable; it is not the upstream export format.
Palette-library arrays and unsupported schema versions are not evaluated.

The screen accepts TXT, JSON and KPAL. Physical observations and owned spool
colours start empty. Changing the palette or the calibration basis clears
observations and invalidates an in-flight result. File reads also have an
identity guard, so an older import cannot replace a later selection.

The visible basis includes family, layer height, first-layer height, nozzle,
material, palette source and an optional user-entered model/revision label.
These fields participate in the basis hash. The label is not a verified model
file identity. Omitted first-layer/model/source data on older history remains
unknown. This changes no database schema: extended basis data stays in the
existing saved comparison payload. History is local, newest first, up to 50;
viewing it never reapplies old readings to current input.

The results are advisory RGB comparisons. No printer, spectrometer or
physical calibration is performed. Tests use synthetic fixtures conforming
to pinned upstream contracts, rather than captured physical readings.

Contract references:
- [DitherForge README](https://github.com/rtwfroody/ditherforge/blob/4d3552a434e8084d9b5fe573959a3493325be29f/README.md)
- [Kromacut palette manager](https://github.com/vycdev/Kromacut/blob/94874755426ee7f33b3684a5544e7fab0e2e73f7/src/lib/paletteManager.ts)


Review follow-up: every explicit TD token is checked, repeated td= assignments
are refused, and leading/fallback values must agree. A blank material is refused;
only an omitted material retains the legacy PLA default. Blank model labels become
unknown. The expanded basis/palette documents change their hashes: pre-change
identities are not reproduced, and old saved comparisons are left untouched.
A numeric leading label such as `#FF0000 2 Tone` is interpreted as TD 2 by the
documented upstream grammar, rather than a label beginning with the number 2.
