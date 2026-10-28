# Accessory adapters

Evidence label: **fixture-tested**. Not hardware-verified. No device, firmware or service was contacted.

These are parser-only adapters. They take a payload that the host layer already fetched and return
normalised foundation documents. Each payload shape is the one the upstream project publishes, pinned
by git blob SHA and line range (see `backend/tests/adapters/accessory/accessory_contracts.py` and the
`PROVENANCE.md` next to every fixture set). The fixtures were written by hand to those shapes. A contract
test fails if a fixture gains or loses a key the upstream does not publish.

| System | Published contract we parse | What stays unknown |
|---|---|---|
| multiACE (api_version 1) | `GET /multiace/api/preflight/livedata`: `live_slots`, `head_ctx` (`mode`, `head_nozzles`, `head_ace`, `ace_heads`, `feeders`, `manual_heads`, `empty_slots`, `head_nozzle_types`). | Slots that are not RFID or override identified are omitted by multiACE, so a missing slot is unknown, never empty. Nozzle type is unknown on firmware that does not send `head_nozzle_types`. Auth deployment (the docs disagree). |
| AFC-Klipper-Add-On | `GET /printer/afc/status`: `{"status:": {"AFC": {<unit>: {<lane>: lane.get_status(), "system": {...}}, "system": {...}}}}`. | Lane index base (AFC publishes order, so the position in the unit is used). Nozzle diameters. Weight and TD accuracy and where each value comes from. |
| BMCU-Klipper (U1) | Print plan in G-code (`BMCU_PRINT_BEGIN SCHEMA=1`, `REQUIRE`, `MAP`/`BMCU_MAP_TOOL`, `COMMIT`), `BMCU_SET_ENDPOINT`, `BMCU_SET_ROUTE`, `BMCU_ROUTE_CONFIRM`, and panel `GET /api/transport-status` schema 1. | `BMCU_STATUS` output and the panel's per-device `status` object are not published: channel states are only what a `BMCU_ROUTE_CONFIRM` line says. |
| Sidecar (beta preview) | `;SIDECAR:REQUEST/PROCESSED/BLOCKED/REASON` G-code markers; virtual tool `T` is head `T // 4`, lane `T % 4 + 1`; the load-cell reply shape the Pi client builds. | The Pi `state` and `lane-meta` reply bodies are not visible in the published client, so those payloads are reported as unknown. The project itself says the stock-U1 handoff and controller builds are not validated on hardware. |

## Documented drift this package handles

- multiACE docs say `livedata` returns HTTP 409 while a head is manual; the code returns 200 with
  `head_ctx.manual_heads`. Both are read (`docs_409_manual`, `code_manual_heads`). A 409 gives unknown
  heads and lanes, never a default of four.
- AFC's wrapper key is the literal `"status:"` (trailing colon). `"status"` and a Moonraker `result` wrapper
  are tolerated variants, not published shapes.
- Default-branch sources move. Adapter tests are pinned to the blob SHAs above, not to a release.

## Rules these parsers keep

- A head count comes only from a list of physical heads (multiACE `head_nozzles`, AFC `system.extruders`
  names, BMCU endpoint `EXTRUDER=` names). It never comes from a lane or slot count, and a topology built
  from endpoints or extruders alone is not marked complete.
- Unknown stays unknown: unknown version, malformed input, an auth failure or an unpublished body gives
  no topology and `unknowns == ["all"]` (or named unknowns), and nothing from the body is kept.
- Wire indices are converted to 0-based with the base recorded (`index_base_source`).
- Observations use the provider time when the payload has one, otherwise receipt time with the
  `observed_at_is_receipt_time` note. Every adapter declares a finite `ttl_s`.
- No network, no `netguard`, no import from `snapstudio_core.moonraker`.

## Not covered

No real multiACE, AFC, BMCU or Sidecar device or service was exercised. This package only reads setups.
Preflight and firmware capability text read a topology only on the separate topology-aware core branch,
and even there the repair path still cuts per-extruder vectors longer than four to four entries because
it does not pass the logical slot count to `prepare_preserved_values`. Until that is wired, accessory
support must not be described as working for preparation, and legacy preparation is not validated by
this package's output.

Two shapes are Studio's own context and not upstream keys: the Sidecar load-cell wrapper carries the
`unit` that was asked about (the published reply is `{ok, lanes}`), and every payload sits in a
transport envelope (`http_status`, `body`, `kind`, `text`).

A multiACE head list counts as complete only when all four queried heads (`extruder`..`extruder3`)
came back in `head_nozzles`, because upstream drops any head whose nozzle diameter it cannot read.
