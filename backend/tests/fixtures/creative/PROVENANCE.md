# Creative fixture provenance

Every archive used by the creative tests is generated at test time by `zip_factory.py` in this folder.
All are SYNTHETIC: built by our own code from the documented output shape, never captured from a real
generator run and never copied from an upstream repository. Evidence label: `fixture-tested`.

Upstream files below were read on 2026-11-01 (default branch head at that time) to learn the output
FORMAT only (member names, XML element and attribute names, JSON keys and what they mean).

| Tool | Licence | Repository | Commit read | Path read | Used for |
| --- | --- | --- | --- | --- | --- |
| DitherForge | MIT | rtwfroody/ditherforge | 4d3552a434e8084d9b5fe573959a3493325be29f | internal/export3mf/export3mf.go, internal/export3mf/bambu.go | Application tag `ditherforge-<semver>` (generic path) or `BambuStudio-<ver>+ditherforge-<semver>` (Bambu path); `Designer` = `ditherforge`; production-extension `3D/3dmodel.model` whose objects are components pointing at `3D/Objects/object_N.model`; per-triangle `paint_color`; `Metadata/model_settings.config` object names `ditherforge_output` / `ditherforge_output_partN`; `Metadata/project_settings.config` with `filament_colour`, `filament_type`, `printer_settings_id`. Permitted by licence; only shapes are re-implemented, no code or sample copied. |
| Kromacut | AGPL-3.0 | vycdev/Kromacut | 94874755426ee7f33b3684a5544e7fab0e2e73f7 | src/lib/export3mf.ts | FORMAT ONLY: Application `Kromacut_Print`; namespace `xmlns:Kromacut`; metadata `slic3rpe:layer_height`, `slic3rpe:first_layer_height`, `Kromacut:SmoothMeshingStrength`; one `<object>` per colour layer carrying `pid`/`pindex` into one `basematerials`; an assembly object made of components; `Metadata/model_settings.config` parts with `extruder`; `Metadata/kromacut.config`; `project_settings.config` keys `layer_height`, `initial_layer_print_height`, `filament_colour`. No code, comment or sample file copied. |
| SindriCAD | AGPL-3.0 | MakerViking/sindricad | 8b2e9dc4f82fba58b39c206c993534c487cc1eab | sidecar/project3mf.py | FORMAT ONLY: Application `SindriCAD`; namespace `xmlns:m` (material 2015/02) with `m:basematerials`/`m:base`; one object per body with `pid="1" pindex=<slot>`; meshes inline in `3D/3dmodel.model`; per-triangle `paint_color`; `model_settings.config` object `extruder` is 1-based, palette slot and `filament_colour` 0-based. No code, comment or sample file copied. |
| ImageMap (Orca fork) | not read in this slice | - | - | - | No new upstream read. Carrier stays unestablished; see `docs/internal/CREATIVE_COMPAT.md`. |
| Lumina Layers | GPL | not read in this slice | - | - | No new upstream read. Only the artifact identity is reported. |

DitherForge paths: upstream `internal/export3mf/` holds `export3mf.go`, `bambu.go` and `printers.go`
(checked with `gh api repos/rtwfroody/ditherforge/contents/internal/export3mf`). The reader was based on
`export3mf.go` and `bambu.go` at the commit in the table (journey slice). The first slice's research notes also
cited `printers.go` lines 18-65; that file was NOT re-read for the journey slice and the reader does not depend
on it. `docs/internal/CREATIVE_COMPAT.md` lists the same three-way split.

Things the upstream source did NOT establish, so the reader does not claim them: the `kromacut.config`
payload, how ImageMap or Lumina mark their 3MF output, and anything about files written by older or newer
releases than the commits above. Settings JSON and collection TXT sidecars mentioned for DitherForge in
earlier research are written beside the 3MF, not inside it, so they are out of scope for a 3MF reader.

Journey-fix slice (same upstream commits, no new read): `make_ditherforge_bambu` follows `bambu.go` at 4d3552a (`buildBambuMainModel`: outer object 2, component `p:path` object_1.model with objectid 1; `buildBambuModelSettings`: object 2, part id 1; inner object id 1) and `make_ditherforge` follows `export3mf.go` (object id 2+i, `<part id="1">`). `make_kromacut` follows `export3mf.ts` at 9487475 (mesh objects in the root model; assembly components without `p:path`; part id equals the component object id). All three remain SYNTHETIC; no genuine export was available or tested. Upstream sources were fetched read-only with `gh api` for format only.
