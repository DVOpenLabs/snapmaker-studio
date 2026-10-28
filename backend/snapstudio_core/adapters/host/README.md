# Host adapters

Evidence label: **fixture-tested**. Fixtures are copied in shape from named upstream sources
(repo, blob SHA, line range) or hand-written and labelled; no real printer, OctoPrint or
Moonraker was contacted to produce them. Per-fixture sources and the list of unverified
assumptions: `backend/tests/fixtures/adapters/host/PROVENANCE.md`.

## What ships

This package ships **stock Moonraker, Paxx Moonraker and OctoPrint only**. Accessory-style
adapters from the P1a track (multiACE, AFC, BMCU, Sidecar and similar) are not part of this
package: when P1a is absent, those setups are simply not recognised, and Studio says so rather
than guessing a topology.

| Adapter id | Reads | Never claims |
|---|---|---|
| `host.moonraker_stock` | toolhead objects, `print_task_config`, `extruder_map_table`, system info | spool identity |
| `host.moonraker_paxx` | the same, plus `filament_spool_id` | a spool when the id array is missing |
| `host.octoprint` | `/api/version` body | heads, slots or materials (unknown) |

## Rules these adapters keep

- Parsers are network-free. Only `reader.py` fetches, and only through `netguard.local_request`
  (GET, bounded, no redirects, never retried, credentials tied to the configured origin).
- A head count comes only from toolhead objects (`extruder`, `extruder1`, ...). A
  `print_task_config` never names heads, however many entries it has.
- Slots come from the filament arrays (4 long on a stock U1; u1-klipper blob 340b4232). The
  32-long `extruder_map_table` is NOT 32 slots: entries past the filament arrays yield one
  `map_entries_beyond_filament_arrays` diagnostic (field `extruder_map_table:<count>`) and an
  unknown `logical_slots_beyond_filament_arrays`. Studio does not know that any firmware reports 32
  filament entries; the `hypothetical_thirty_two_logical_*` fixtures only exercise size handling.
- Colour comes from `filament_color_rgba` (RRGGBB then AA). The integer `filament_color` is not
  converted. Upstream does define it as ARGB (alpha in the top byte, lines 661-692 of the pinned
  file), but Studio keeps one colour source on purpose: colour from the integer alone stays unknown.
- `GET /api/version` may omit `api` (OctoPrint, with the version-negotiation header); accepted.
- Logical-to-physical bindings come only from `extruder_map_table`. Without it, bindings are
  unknown; identity is never assumed.
- Paxx without `filament_spool_id` leaves spool identity unknown (not cleared, not invented).
- From `/machine/system_info` only `product_info.nozzle_diameter` and `sd_info.total_bytes`
  are read. Device name, serial numbers, MAC and IP addresses are never surfaced.
- Host kind is decided from reply bodies (`classify.py`): OctoPrint from `/api/version`, but a
  `/server/info` carrying `moonraker_version` wins, because Moonraker's `octoprint_compat`
  answers `/api/version` in OctoPrint's shape. A preset `host_type` is never consulted.
- A missing, wrong or insufficient `X-Api-Key` (401/403) is `unavailable`; the request is not
  repeated.

## Bundle format

Adapters read a Studio-defined envelope (`source_version` `host_bundle/1`) of replies the host
layer already fetched: `server_info`, `objects_list`, `print_task_config`, `system_info`
(Moonraker, each optional) or `api_version` (+ optional `server_info`) for OctoPrint. Any other
`source_version` yields every field unknown.

## Disclosed limits

- The Paxx variant is chosen from a `filament_spool_id` array in the reply or by an explicit
  hint; a Paxx machine that omits the array looks like stock, which has the same (unknown) spool
  result. The community-firmware web marker (`moonraker_parse.extended_firmware_from`) is a pure
  helper over already-fetched pages and is not fetched here.
- OctoPrint exposes no toolhead or filament data on the paths Studio allows, so its topology is
  incomplete by design. Requesting an OctoPrint Application Key is not supported; paste an
  existing key.
- Link-local-only hosts are refused by netguard and shown as refused, not unreachable.
