"""Published upstream key sets the accessory fixtures must match.

Every set cites the upstream repository, git blob SHA and line range it was read from
(blobs fetched by SHA, so the citation is immutable). Nothing here is observed from a device.
"""

# decay71/multiACE: web/backend/main.py blob d19bc7a2, `_live_slots_async` lines 1204-1229.
MULTIACE_LIVE_SLOT = {"ace", "slot", "material", "color"}
# docs/LOADOUT_API.md blob bac8805b sec 1 (required) and main.py `_head_mode_context` lines 1312-1330 (allowed).
MULTIACE_CTX_REQUIRED = {"mode", "head_nozzles", "head_ace", "ace_heads", "feeders"}
MULTIACE_CTX_ALLOWED = MULTIACE_CTX_REQUIRED | {
    "ace_head", "manual_heads", "head_nozzle_types", "pickup_cleaning", "max_copies", "copies_strict",
    "empty_slots", "bg_available", "bg_heads"}
MULTIACE_MANUAL_OR_FEEDER = {"head", "material", "color"}

# AFCProject/AFC-Klipper-Add-On: extras/AFC_lane.py blob f6b98e2c `get_status` lines 2183-2235.
AFC_LANE_KEYS = {
    "name", "unit", "hub", "extruder", "buffer", "buffer_status", "lane", "map", "load", "prep", "selector",
    "tool_loaded", "loaded_to_hub", "material", "remember_spool", "spool_id", "color", "filament_name",
    "multi_color_hexes", "initial_weight", "weight", "extruder_temp", "bed_temp", "runout_lane",
    "filament_status", "filament_status_led", "status", "dist_hub", "td1_td", "td1_color", "td1_scan_time",
    "endstops"}
# extras/AFC.py blob 9553d159 `_webhooks_status` lines 2577-2612.
AFC_UNIT_SYSTEM_KEYS = {"type", "hub_loaded"}
AFC_SYSTEM_KEYS = {"current_load", "num_units", "num_lanes", "num_extruders", "spoolman", "td1_present",
                   "lane_data_enabled", "current_toolchange", "number_of_toolchanges", "extruders", "hubs",
                   "buffers", "led_state"}
AFC_WRAPPER = "status:"        # line 2612: web_request.send({"status:": {"AFC": str}})

# jarczakpawel/BMCU-Klipper: docs/COMMANDS.md blob 2bc051ed (commands) lines 61-96, 311-345, 527-534, 581-650.
BMCU_COMMANDS = {"BMCU_PRINT_BEGIN", "BMCU_PRINT_REQUIRE", "BMCU_PRINT_MAP", "BMCU_MAP_TOOL", "BMCU_PRINT_COMMIT",
                 "BMCU_SET_ENDPOINT", "BMCU_SET_ROUTE", "BMCU_SET_OUTPUT", "BMCU_ROUTE_CONFIRM"}
BMCU_PARAMS = {"SCHEMA", "RESET", "TOOL", "DEVICE", "CHANNEL", "MATERIAL", "COLOR", "NAME", "DRIVER", "EXTRUDER",
               "SHARED_PATH_GROUP", "ENDPOINT", "STATE"}
# web/bmcu_panel_server.py blob bd2d86ae lines 1980-2045.
BMCU_PANEL_KEYS = {"schema", "devices", "error"}
BMCU_PANEL_DEVICE_KEYS = {"schema", "name", "online", "process_online", "socket_online", "updated_at", "status",
                          "error"}

# dcan999/Sidecar-Beta: host/pi/runtime/sc_watchd.py blob c1e93fb4 lines 9-11, 264-267.
SIDECAR_MARKERS = {"SIDECAR:REQUEST", "SIDECAR:PROCESSED", "SIDECAR:BLOCKED", "SIDECAR:REASON"}
# host/pi/ui/source/src/lib/sidecarApi.ts blob 6d9823fc lines 123-142 (load-cell lanes), 37-39 (error shape).
SIDECAR_LOADCELL_KEYS = {"ok", "lanes"}     # `unit` is Studio request context in the wrapper, not a reply key
SIDECAR_LOADCELL_LANE_KEYS = {"raw_g", "net_g"}
SIDECAR_ERROR_KEYS = {"ok", "error", "detail", "_http"}

#: Studio transport envelope keys (not upstream): `http_status`, `body`, `kind`, `text`.
ENVELOPE_KEYS = {"http_status", "body", "kind", "text", "unit"}
