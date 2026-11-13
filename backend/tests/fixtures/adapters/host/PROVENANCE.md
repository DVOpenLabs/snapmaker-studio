# Host adapter fixtures: provenance

**None of these files is a capture from a real printer or server.** Each is either copied in
shape from a named, versioned upstream source (below) or hand-written and labelled as such.
Evidence label: **fixture-tested**. No hardware, no network. Upstream blobs are immutable git
blob SHAs; "develop"/"dev" branch names are not proof for any stable firmware release.

## Per-fixture sources

| Fixture | Shape source (repo, blob, lines) |
|---|---|
| `moonraker_stock/u1-klipper-340b4232/upstream_default_shape.json` | Snapmaker/u1-klipper `klippy/extras/print_task_config.py` blob `340b4232`: `LOGICAL_EXTRUDER_NUM=32`, `PHYSICAL_EXTRUDER_NUM=4` (lines 8-9), `DEFAULT_PRINT_TASK_CONFIG` (lines 25-63): per-filament arrays 4 long, `extruder_map_table` 32 long, integer `filament_color`, hex-string `filament_color_rgba` (RRGGBB then AA: lines 236-237, 331); `get_status` (line 529) returns the whole dict |
| `moonraker_paxx/paxx-synthetic-1/*` | stock shape above plus `filament_spool_id`, a list Paxx SpoolLink subscribes to: paxx12-snapmaker-u1/SnapmakerU1-Extended-Firmware `spoollink.py` blob `9becbee2` (branch develop), lines 93-135; updates are diffs and a missing field is not a clear |
| `octoprint/*/moonraker_compat.json` | Snapmaker/u1-moonraker `moonraker/components/octoprint_compat.py` blob `bd68e0a4`: `OCTO_VERSION = '1.5.0'` (line 26); `_get_version` (lines 189-199) returns `server`, `api: '0.1'`, `text: 'OctoPrint (Moonraker <version>)'` |
| `octoprint/*/version_no_api_key.json` | OctoPrint docs (dev branch = 2.0 docs) blob `4c57bad4`, lines 55-106: with `X-OctoPrint-Api-Version` the reply has no `api` key |
| `octoprint/*/version_body.json` | same OctoPrint docs blob, `{api, server, text}` form; the `1.9.3` value is hand-written |

## Hand-written, not from an upstream source

- `moonraker_stock/moonraker-0.9/*` and `moonraker_paxx/paxx-synthetic-1/*` cases (loaded, empty
  entries, crossed/missing `extruder_map_table`, partial/missing `filament_spool_id`,
  disconnected, malformed, unknown version) are Studio-authored variations on the shapes above.
  The directory name is a label, not a measured firmware.
- `hypothetical_thirty_two_logical_*`: **hypothetical.** Studio does not know that any firmware
  reports 32 filament entries; upstream defaults are 4. They exercise the parser's size handling
  only.
- `system_info_identifiers.json`: `SYNTH-...`, `00:00:5E:...`, `192.0.2.x` are reserved or
  documentation values, present only to prove they are not surfaced.
- `malformed_arrays.json` contains a literal `NaN`; Python's loader accepts it, a strict parser
  does not. Intentional.
- Each file is an envelope `{source_version, received_at, bundle[, note]}`; `bundle` holds replies
  as they arrive on the wire (wrapped in `result` for Moonraker). Layout:
  `<system>/<version>/<case>.json`.

## Still an assumption (not verified against a saved source)

- The `/printer/objects/query` nesting `result.status.<object>` is Moonraker's documented form;
  the Moonraker docs blob (u1-moonraker `docs/web_api.md` lines 912-938) is NOT in the saved
  contracts folder, so this is unverified here.
- `/printer/objects/list`, `/server/info` (`moonraker_version`, `components`) and
  `/machine/system_info` field names rest on Moonraker documentation not saved with the contracts.
- Whether stable Paxx firmware (not `develop`) exposes `filament_spool_id` the same way.
- The integer `filament_color` (upstream names it `ARGB_COLOR`, line 336, and packs
  `(alpha<<24)|RGB`, lines 661-692). Studio chooses not to convert it: a colour known only from the
  integer is unknown.
- OctoPrint stable-release version negotiation (only the dev/2.0 docs were read).
- Whether any real U1 reports `filament_spool_id`, `extruders_used` or similar beyond what the
  source files define; no device was contacted.
