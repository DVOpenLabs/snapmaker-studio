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
| DitherForge | Application tag and variant, build item count, object part files, triangle and painted-triangle counts, paint extruders (documented 1-2 character `paint_color`), object names and extruders from `model_settings.config`, `filament_colour`, `filament_type`, `printer_settings_id`, `print_settings_id` | Every other member and settings key, by name and SHA-256 | Longer `paint_color` strings, geometry beyond counts, settings JSON and collection TXT (written beside the 3MF, not inside it). Reader: `creative/generators.py`, evidence `fixture-tested`, upstream commit in PROVENANCE.md. |
| Kromacut | Application `Kromacut_Print`, layer and first-layer height metadata, colour layer object count, assembly object, parts with extruders, base materials, `filament_colour`, `layer_height`, `initial_layer_print_height` | Every other member, including `Metadata/kromacut.config` | The `kromacut.config` payload and mesh geometry are not interpreted. Format learned from AGPL source; no code copied. Evidence `fixture-tested`. |
| SindriCAD | Application `SindriCAD`, body count, body names with palette slot (`pindex`) and 1-based extruder, palette base materials, per-face paint, `filament_colour`, `filament_type` | Every other member and settings key | Longer `paint_color` strings and geometry beyond counts. A body whose extruder disagrees with its palette slot is flagged. Format learned from AGPL source; no code copied. Evidence `fixture-tested`. |

## Evidence references

- FOrcaSlicer: upstream `src/libslic3r/PrintConfig.cpp` source blob `755c1a69f8439d0beb6367e009306d098f67b29a`, cited locations 2175, 2185, 4067, 4076, 4087, 4664 and 4725; published project research records the physical-versus-filament nozzle distinction and key families.
- LixNix: upstream `src/libslic3r/PrintConfig.cpp` source blob `686a931f69c8f65441d865274c31647ff17f152b`, lines 5600 and 5622; `src/libslic3r/Slicing.hpp` source blob `c69b7e2c0be813a55b61f092cb2ce49168ee928f`, lines 212-289.
- FullSpectrum: inspected v0.9.12 source and packaging notes describe `Metadata/project_settings.config`, the `mixed_filament_definitions` key and compact row tokens. `doc/fullspectrum-3mf-packaging.md` lines 74-76 and 162-211. Research entry `xipit-fullspectrum-ui` identifies the exact release and explicitly separates the draft vnext schema.
- ImageMap: inspected `src/libslic3r/TextureMapping.hpp` lines 55-145, 187-238, 538-548, 948-976 and 1034-1110, and README lines 50-103. Research reports that the exact 3MF carrier still needs tracing.
- Lumina: inspected `api/routers/converter.py` lines 192-268, 469, 609, 730 and 832. Research records `/api/files/{file_id}` retrieval, but this reader only hashes a supplied artifact.
- DitherForge: the reader is based on `internal/export3mf/export3mf.go` and `internal/export3mf/bambu.go` (commit 4d3552a, see PROVENANCE.md). Earlier research notes also cited `export3mf.go` lines 15-107 and `internal/export3mf/printers.go` lines 18-65; `printers.go` exists upstream but was not re-read for the reader and the reader does not depend on it.
- Kromacut: `src/lib/export3mf.ts` lines 8-21, 147-160, 259-281, 331-335 and 734-771.
- SindriCAD: `sidecar/project3mf.py` lines 1-23, 130-158 and 203-306.

The contract tests create small in-memory ZIPs through a checked-in helper. They are synthetic fixtures, not captured projects. Test coverage includes malformed and truncated ZIP data, member size and expansion limits, traversal names, duplicate members, malformed XML, unsupported core namespace/version, missing required settings, and opaque unknown members.

## Route and screen (slice 2)

Evidence level: `fixture-tested`. Only synthetic archives have been inspected; no project captured from a real generator has been read.

- `POST /creative/inspect {path, format?}` (`backend/snapstudio_api/routes_creative.py`). The handler opens one local file for reading only: it must exist, be a regular file and be under the 128 MiB archive cap, otherwise the request is refused with 400 before any parsing. Non-archives, archives with no 3D model part and every container limit error also return 400 with a plain sentence. Nothing is written, renamed or deleted, no slicer or printer is contacted and the handler makes no network request of its own. UNC, device and link-to-share paths are refused before opening; that check is best-effort (see `snapstudio_core/localpath.py`), not a sandbox.
- Generator detection (`format` omitted or `auto`): superseded by the journey slice below. In slice 2 it used only the published settings keys; it now also uses the application tag and file markers of DitherForge, Kromacut and SindriCAD, and never decides from "it is a ZIP". One match is reported as `detected`, a `format` hint as `chosen`, several matches as `ambiguous` (origin not decided, candidates listed) and none as `unknown`. An unknown generator still gets the container identity: every archive member and every settings key is listed as passed through by name and SHA-256.
- The response carries `understood`, `passed_through`, `could_not_interpret` (unknown keys), `missing` (expected keys that were absent), `diagnostics`, simulated `recipes` (`simulated=True`, `execution_supported=False`), `physical_slots_needed`, and `source` with the file name only (never the full path), size, `sha256_before`, `sha256_after` and `unchanged`. The file is hashed from the bytes read and again by re-reading it after the readers ran.
- Desktop: route `/creative` ("Creative import", group Studio+) in `desktop/src/routes/ext/creative.{meta.ts,route.tsx}`; view in `desktop/src/components/creative/`; client in `desktop/src/lib/creativeApi.ts`. The page takes a typed file path (no file picker in this slice) and shows origin, understood, kept untouched, could not interpret, simulated recipes and the unchanged-original line.
- Screenshots in `docs/internal/screens/creative/` come from `capture.mjs`: real engine process, vite dev UI, headless Edge, synthetic archives with relative file names.
- Limits: ImageMap and Lumina are only reachable by the explicit `format` choice because their archives carry no settings keys that identify them. (Slice-2 statement that DitherForge, Kromacut and SindriCAD have no reader is superseded: the journey slice adds readers for all three.) The files are inspected one at a time; there is no batch or folder scan.

## Journey slice: supported formats, prepare and export verification

Evidence level: `fixture-tested`. Upstream sources were read for FORMAT only (owner/repo, commit, path in `backend/tests/fixtures/creative/PROVENANCE.md`): DitherForge (MIT) `rtwfroody/ditherforge` 4d3552a, Kromacut (AGPL-3.0) `vycdev/Kromacut` 9487475, SindriCAD (AGPL-3.0) `MakerViking/sindricad` 8b2e9dc. ImageMap and Lumina were not re-read; they stay manual-only with identity-only reading. Every fixture is generated by `zip_factory.py` and is synthetic.

### Supported formats (`POST /creative/formats {}`; table `SUPPORTED_FORMATS` in `creative/formats.py`)

| Format | Selection | Identified by | Not read |
| --- | --- | --- | --- |
| DitherForge | automatic | Application `ditherforge-<v>` or `+ditherforge-<v>` | long paint strings, geometry, sidecar JSON/TXT |
| Kromacut | automatic | Application `Kromacut_Print`, `xmlns:Kromacut`, or `Metadata/kromacut.config` | kromacut.config payload, geometry |
| SindriCAD | automatic | Application `SindriCAD` | long paint strings, geometry |
| FOrcaSlicer, LixNix, FullSpectrum | automatic | published settings keys (see above) | see reader table |
| OrcaSlicer ImageMap, Lumina Layers | manual only | nothing: no identifying marker | zone shape; provenance |

Markers of several tools in one file give origin `ambiguous`; a chosen format with the wrong shape is refused with a 400 listing what was expected, what the file has, and what to do.

### `POST /creative/prepare {path, format?, out_dir?}`

Re-inspects, refuses unknown or ambiguous input with an explanation (HTTP 200, `prepared: false`, `refusal`), then calls `service.convert(path, out_dir, "preserve")` and verifies the result: the export is re-opened, members listed with SHA-256, compared by name with the original (kept identical / changed / dropped / added), project-settings keys removed/changed/added, painted-triangle counts before and after, and the original is re-hashed (`original_unchanged`). `out_dir` must be an existing local folder (UNC and device paths refused). With no `out_dir` the copy goes to `creative-prepared` inside Studio's data directory, NOT next to the original (the service's own default is next to the source, which this route deliberately does not use). The route does not call `service.record_conversion`, but `service.convert` itself still writes its Prepare fix-ledger entry in Studio's data directory, so a successful Prepare leaves that ledger entry there. The response names the output file and a generic location label only ("Studio's creative-prepared folder" or "the folder you chose"); no directory path is returned.

Measured behaviour of the existing Prepare on synthetic files (preserve mode):

| Tool shape | Result |
| --- | --- |
| SindriCAD | Copy written. Model, `model_settings.config`, other members kept identical; `project_settings.config` rewritten (settings keys all kept, 64 added); painted triangles 2 of 2. |
| FullSpectrum-keyed / plain 3MF (ImageMap or Lumina chosen) | Copy written. Unknown members kept identical; `project_settings.config` rewritten, no keys removed. |
| DitherForge, Bambu path (`BambuStudio-<v>+ditherforge-<v>`) | Copy written. Geometry, object file, relationships and `model_settings.config` kept identical; `project_settings.config` rewritten; `Metadata/plate_1.json` dropped (Prepare removes `Metadata/plate_*.json` as a stale slice cache, `orca_import.SLICE_CACHE_*`); painted triangles 3 of 3. |
| DitherForge, generic path (`ditherforge-<v>`) | REFUSED by Prepare's structure check, and this is what the exporter really writes: `export3mf.go` gives each part object id 2+i (also for a single mesh: id 2), the component and inner object use that id, and `buildModelSettingsParts` writes `<part id="1">` for every object. Studio reports "part ids ['1'] do not match its component ids ['2']". The check is unchanged and has no producer exemption; such a file is inspect-only and the format table says so (`prepare_limits`). Whether Orca loads that shape is not established here. |
| Kromacut | Copy written (fixed in this slice). The exporter writes colour layers as mesh objects in the root model and an assembly object whose components carry no `p:path`; that is valid 3MF Core. `multipart.validate_archive` looked for mesh objects only in `p:path` files and reported "reference an object that no file defines"; it now also counts mesh objects the root model defines (a component without `p:path` needs a root mesh object; one with `p:path` still needs one in that file). Model, `model_settings.config` and `kromacut.config` kept identical; `project_settings.config` rewritten; no per-triangle paint (colour is by material pid/pindex). |

The Kromacut refusal was a Studio validator defect and is fixed; the DitherForge generic-path refusal is the validator correctly declining a shape it cannot vouch for. Both rows are from synthetic files built from the exporter source, not from captured exports. While fixing this, `<triangle` matching in the existing `p:path` file scan was noticed to count an empty `<triangles></triangles>` as geometry (the root-model scan added here matches `<triangle ` with a space); that older line is left unchanged and listed as a carried observation. The comparison is by part name and hash and says nothing about how a copy slices.

### Journey steps run against the real engine and UI with synthetic archives

`docs/internal/screens/creative/capture.mjs`: real engine process, vite dev UI, headless Edge. Inspect (DitherForge, Kromacut, SindriCAD, ambiguous, unknown), format chooser (ambiguous, SindriCAD chosen, ImageMap manual-only), Prepare refusal (DitherForge generic path, unknown origin), Prepare success with export verification (SindriCAD, Kromacut, DitherForge Bambu path). Not run: any real generator output, Snapmaker Orca, any printer.
