# Creative project reader coverage

Evidence level: `fixture-tested`. Fixtures are hand-written to published shapes, not captures. These readers inspect local bytes only; they do not slice, launch a generator, contact a printer, or alter the source archive. A 3MF manifest records each member name and SHA-256 digest. Unrecognized member bytes are never decoded or rewritten.

## Reader coverage and loss report

| Source format | Understood | Passed through untouched | Could not interpret / limits |
| --- | --- | --- | --- |
| 3MF container | `3D/3dmodel.model` XML identity and `Metadata/project_settings.config` JSON when present | Every other member, named and SHA-256 hashed | Container parts beyond model XML and project settings are not interpreted. Archive paths, duplicate names, sizes, expansion ratio and XML core namespace are checked. |
| FOrcaSlicer settings | Published `fos_filament_nozzle`, `fos_filament_mms_slot`, `fos_physical_nozzle_diameter`, `fos_mms_topology`, `fos_mms_unit_count`, `fos_mms_head_ace`, `mms_system`, `mms_host`, `color_patch_loops`, and `color_patch_enabled` keys | All other config keys are retained by name and digest, including plain `nozzle_diameter` | Unknown `fos_*` keys stay unknown. `nozzle_diameter` is not treated as a physical vector: source research says it becomes per-filament while slicing and `fos_physical_nozzle_diameter` retains the physical vector. Complex topology values are preserved but not interpreted. |
| LixNix Full Multi-Nozzle settings | `extruder_layer_height` and `extruder_layer_height_exact` | Other keys and values | Unpublished `extruder_layer_height*` variants stay unknown. The reader does not calculate effective heights or print outcomes. |
| FullSpectrum 0.9.12 | `mixed_filament_definitions` compact rows; pair IDs and documented `g<ids>` gradient IDs become foundation `VirtualRecipe` project-slot references; `u<stable_id>` is used as the recipe identity when present | Other config keys and all unrecognized row detail | Ratios, pattern semantics, rendering, color and execution are unknown. Recipes always report `simulated=True` and `execution_supported=False`. `physical_slots_needed` counts distinct referenced project slots, while `source_component_ids` preserves their 1-based source IDs; these do not assert physical filament inventory. The draft vnext schema is not read. |
| OrcaSlicer ImageMap | 3MF container artifact identity only | All project settings and unknown archive members by name and digest | ImageMap's exact serialized 3MF carrier and zone shape remain unestablished in the research; the reader reports that shape as unknown and makes no zone compatibility claim. |
| Lumina Layers output | 3MF artifact identity: byte size, SHA-256 and optional opaque file ID | Project settings and unknown archive members by name and digest | Generation provenance, session behavior and file-ID lifetime are unknown. No API is called. |
| DitherForge | No reader in this slice | Not applicable | Research describes 3MF output with per-face painting and split objects, plus settings JSON and collection TXT. Shape-specific parsing is deferred to slice 2. |
| Kromacut | No reader in this slice | Not applicable | Research describes 3MF per-object extruder mapping, layer and first-layer heights, generic material metadata, and optional custom metadata files. Shape-specific parsing is deferred to slice 2. |
| SindriCAD | No reader in this slice | Not applicable | Research describes named bodies, color-slot assignment, per-face paint, base materials, Orca extruder configuration and per-triangle `pindex`. Shape-specific parsing is deferred to slice 2. |

## Evidence references

- FOrcaSlicer: upstream `src/libslic3r/PrintConfig.cpp` source blob `755c1a69f8439d0beb6367e009306d098f67b29a`, cited locations 2175, 2185, 4067, 4076, 4087, 4664 and 4725; published project research records the physical-versus-filament nozzle distinction and key families.
- LixNix: upstream `src/libslic3r/PrintConfig.cpp` source blob `686a931f69c8f65441d865274c31647ff17f152b`, lines 5600 and 5622; `src/libslic3r/Slicing.hpp` source blob `c69b7e2c0be813a55b61f092cb2ce49168ee928f`, lines 212-289.
- FullSpectrum: inspected v0.9.12 source and packaging notes describe `Metadata/project_settings.config`, the `mixed_filament_definitions` key and compact row tokens. `doc/fullspectrum-3mf-packaging.md` lines 74-76 and 162-211. Research entry `xipit-fullspectrum-ui` identifies the exact release and explicitly separates the draft vnext schema.
- ImageMap: inspected `src/libslic3r/TextureMapping.hpp` lines 55-145, 187-238, 538-548, 948-976 and 1034-1110, and README lines 50-103. Research reports that the exact 3MF carrier still needs tracing.
- Lumina: inspected `api/routers/converter.py` lines 192-268, 469, 609, 730 and 832. Research records `/api/files/{file_id}` retrieval, but this reader only hashes a supplied artifact.
- DitherForge: `internal/export3mf/export3mf.go` lines 15-107 and `internal/export3mf/printers.go` lines 18-65.
- Kromacut: `src/lib/export3mf.ts` lines 8-21, 147-160, 259-281, 331-335 and 734-771.
- SindriCAD: `sidecar/project3mf.py` lines 1-23, 130-158 and 203-306.

The contract tests create small in-memory ZIPs through a checked-in helper. They are synthetic fixtures, not captured projects. Test coverage includes malformed and truncated ZIP data, member size and expansion limits, traversal names, duplicate members, malformed XML, unsupported core namespace/version, missing required settings, and opaque unknown members.

## Route and screen (slice 2)

Evidence level: `fixture-tested`. Only synthetic archives have been inspected; no project captured from a real generator has been read.

- `POST /creative/inspect {path, format?}` (`backend/snapstudio_api/routes_creative.py`). The handler opens one local file for reading only: it must exist, be a regular file and be under the 128 MiB archive cap, otherwise the request is refused with 400 before any parsing. Non-archives, archives with no 3D model part and every container limit error also return 400 with a plain sentence. Nothing is written, renamed or deleted, no slicer or printer is contacted and the handler makes no network request. UNC, device and link-to-share paths are refused before opening; that check is best-effort (see `localpath.py`), not a sandbox.
- Generator detection (`format` omitted or `auto`) uses only the published keys each reader knows. One match is reported as `detected`, a `format` hint as `chosen`, several matches as `ambiguous` (origin not decided, candidates listed) and none as `unknown`. An unknown generator still gets the container identity: every archive member and every settings key is listed as passed through by name and SHA-256.
- The response carries `understood`, `passed_through`, `could_not_interpret` (unknown keys), `missing` (expected keys that were absent), `diagnostics`, simulated `recipes` (`simulated=True`, `execution_supported=False`), `physical_slots_needed`, and `source` with the file name only (never the full path), size, `sha256_before`, `sha256_after` and `unchanged`. The file is hashed from the bytes read and again by re-reading it after the readers ran.
- Desktop: route `/creative` ("Creative import", group Studio+) in `desktop/src/routes/ext/creative.{meta.ts,route.tsx}`; view in `desktop/src/components/creative/`; client in `desktop/src/lib/creativeApi.ts`. The page takes a typed file path (no file picker in this slice) and shows origin, understood, kept untouched, could not interpret, simulated recipes and the unchanged-original line.
- Screenshots in `docs/internal/screens/creative/` come from `capture.mjs`: real engine process, vite dev UI, headless Edge, synthetic archives with relative file names.
- Limits: ImageMap and Lumina are only reachable by the explicit `format` choice because their archives carry no settings keys that identify them. DitherForge, Kromacut and SindriCAD have no reader and are not offered. The files are inspected one at a time; there is no batch or folder scan.
