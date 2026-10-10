# What is in the U1 base project, and why

`u1_base_project_settings.json` is the project settings every prepared U1 copy
starts from. It was captured from a real Snapmaker Orca project, which is why it
is large: a project file states most of its presets' values inline.

That inline restatement is mostly harmless and mostly pointless. Measured on
Snapmaker Orca 2.3.6, one variable per file: **a value a project states is only
used when the project also declares it deviates.** An undeclared value is replaced
by the preset the project names — `prime_tower_width` 60 came back 30,
`brim_type` `no_brim` came back `auto_brim`, `nozzle_type` `stainless_steel` came
back `hardened_steel`. So a restated preset default is not a setting; it is a
comment the slicer overwrites.

This file exists so the template cannot silently accrete values nobody owns
again. Every key belongs to exactly one group below. `test_template_provenance`
fails if a key appears that belongs to none.

## The groups

### `preset_default` — restated, inherited in practice
The value equals the preset the project names, so Snapmaker Orca would have used
it anyway. Keeping it costs nothing and buys nothing; it is not removed wholesale
only because removal has not been proved safe key by key across the Orca versions
Studio supports.

**Rule:** a new key may join this group only if its value matches the effective
Snapmaker Orca U1 preset. If it does not match, it belongs below.

### `project_structure` — the project describing itself
How many filaments there are, what colour each is, how they purge into each
other, which plate an object is on. Not settings, and not a preset's to own.

`filament_colour`, `filament_settings_id`, `flush_volumes_matrix`,
`flush_volumes_vector`, `filament_maps`, `different_settings_to_system`,
`print_sequence`, `is_custom_defined`, and every key in
`filaments.PER_FILAMENT_KEYS` (one value per slot).

**Rule:** these are written to match the project, never declared as overrides —
except `different_settings_to_system`, which is the declaration itself.

### `target_identity` — which machine and presets this is
`printer_model`, `printer_variant`, `printer_settings_id`, `print_settings_id`,
`filament_settings_id`, `nozzle_diameter`, `version`.

**Rule:** a prepared copy must name a real U1 preset. `u1_identity` owns these.

### `source_carried` — a fact from the project being prepared
The five settings `prusa.CARRIED` translates, plus the brim type that follows
from the brim width. A project sliced at 0.15 mm with four walls should not
arrive at 0.2 mm with two.

**Rule:** every one of these is declared in `different_settings_to_system`, or it
does not reach the slicer. `convert._carry_source_settings` does that.

### `studio_compatibility` — values that stop Orca misbehaving on a U1
`exclude_object`, `brim_type`, `support_style`, `filament_self_index`,
`raft_first_layer_expansion`. `orca_import.apply_compatibility` owns these and
says why for each.

**Rule:** declared, always. Undeclared they were measured to be discarded.

### `studio_optimization` — a value the user asked for
Whatever an optimization profile in `data/optimizations/` sets, in optimize mode
only.

**Rule:** declared, always.

### `no_preset_equivalent` — a project-level value no preset defines
Plate settings, wipe-tower geometry, and the rest of what a project states that
no printer, process or filament preset has an entry for. These cannot be
inherited because there is nothing to inherit from.

**Rule:** a new key may join this group only if no effective U1 preset defines
it.

## What was removed, and why

Eight keys were removed on 2026-08-26. Each differed from the preset the template
names, had no owning feature anywhere in Studio, and — being an undeclared
deviation — was replaced by Snapmaker Orca on load. So none of them had ever
reached a print.

| key | template said | preset says | owner |
|---|---|---|---|
| `machine_start_gcode` | dated `20251222` | dated `20260128` | printer |
| `machine_end_gcode` | ` PRINT_END\nTIMELAPSE_STOP` | the full by-object block | printer |
| `layer_change_gcode` | an older variant | the current one | printer |
| `nozzle_type` | `stainless_steel` | `hardened_steel` | printer |
| `default_print_profile` | `0.20mm Standard @Snapmaker` | a profile this Orca does not have | printer |
| `enable_pressure_advance` | `1` | `0` | filament |
| `supertack_plate_temp` | `35` | `40`, and absent in 2.3.5 | filament |
| `supertack_plate_temp_initial_layer` | `35` | `40`, and absent in 2.3.5 | filament |

The machine's own start and end G-code are the sharpest of these: they are what
the printer runs, they belong to the installed printer preset which tracks the
firmware, and Studio was shipping a five-week-old snapshot of them.

## The presets this was measured against

Snapmaker Orca **2.3.6** (installed) and **2.3.5** (portable build), inheritance
resolved:

```
printer   Snapmaker U1 (0.4 nozzle) <- fdm_U1 <- fdm_toolchanger <- fdm_klipper
process   0.20 Standard @Snapmaker U1 (0.4 nozzle) <- fdm_process_U1_0.20
                                                   <- fdm_process_U1_common
                                                   <- fdm_process_U1
filament  Snapmaker PLA SnapSpeed @U1 <- Snapmaker PLA SnapSpeed @U1 base
```

The **process** preset is byte-identical between the two builds. Three inherited
values moved: `machine_start_gcode`, and `supertack_plate_temp` /
`supertack_plate_temp_initial_layer` which do not exist in 2.3.5 at all.

**Studio does not read these files at runtime and must not start.** That would be
a second preset resolver to keep in step with every Orca release. Studio knows
what it changed because Studio made the change — `preset_deviation` declares
exactly that. The preset files are audit evidence for this document, nothing more.

## `nozzle_volume_type` is left out of prepared copies

The base project has no `nozzle_volume_type`, and neither do the Snapmaker Orca 2.3.5 and 2.3.6 projects committed as test
fixtures. Bambu Studio 2.08 and OrcaSlicer 2.4.2 projects (including one OrcaSlicer file that names a U1) carry it, for
example `["Standard"]`. `orca_import.apply_compatibility` therefore removes it, and any declaration of it in
`different_settings_to_system`, from every prepared copy in every mode. This is based on those fixtures and on a reporter's
screenshot of a "newer version, values replaced" notice; it is **not confirmed in Snapmaker Orca** that leaving the key out
removes the notice.
