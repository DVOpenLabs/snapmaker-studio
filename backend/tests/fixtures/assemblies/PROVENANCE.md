# Assembly fixtures: provenance

Every file here is synthetic and documentation-derived. None is a capture from a real printer,
spool provider, library or model file.

- `six_tile.json`: a six-tile road-and-water diorama invented for these tests (three plates, two tiles
  each, two shared roles). Names, ids and gram figures are made up. The spool ids belong to a provider
  called `synthetic`; no such service exists.
- `slot_usage_tile.json`: shaped like the output of `snapstudio_core.project_compare.slot_usage`
  (slots numbered from 1, `sliced_g` per slot) as documented in that module. Hand-written.
- `gcode_facts_tile.json`: shaped like the `slots` list of `snapstudio_core.gcode.read_facts`
  (tools numbered from 0, `grams` per slot). Hand-written.

Evidence label: fixture-tested.
