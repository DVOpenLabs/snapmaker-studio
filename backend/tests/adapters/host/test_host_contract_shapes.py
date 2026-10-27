"""Fixture shapes checked against the saved upstream contract (u1-klipper print_task_config.py blob 340b4232).

Evidence label: fixture-tested. The key set below is copied from DEFAULT_PRINT_TASK_CONFIG (lines 25-63);
`filament_spool_id` is the field Paxx SpoolLink subscribes to (blob 9becbee2 lines 93-135).
"""
from __future__ import annotations

import json
import pathlib

FIXTURE = (pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "adapters" / "host" / "moonraker_stock"
           / "u1-klipper-340b4232" / "upstream_default_shape.json")

PHYSICAL, LOGICAL = 4, 32
DEFAULT_KEYS = {
    "filament_vendor", "filament_type", "filament_sub_type", "filament_color", "filament_color_rgba",
    "filament_color_multi", "filament_official", "filament_sku", "filament_edit", "filament_exist",
    "filament_soft", "extruder_map_table", "extruders_used", "extruders_replenished", "time_lapse_camera",
    "auto_bed_leveling", "flow_calibrate", "flow_calib_extruders", "shaper_calibrate",
    "auto_replenish_filament", "replenish_ignore_color", "filament_entangle_detect",
    "filament_entangle_sen", "end_led_turn_off", "end_unload_filament", "reprint_info",
}
ALLOWED_KEYS = DEFAULT_KEYS | {"filament_spool_id"}
PER_FILAMENT = ("filament_vendor", "filament_type", "filament_sub_type", "filament_color", "filament_color_rgba",
                "filament_color_multi", "filament_official", "filament_sku", "filament_edit", "filament_exist",
                "filament_soft", "extruders_used", "extruders_replenished", "flow_calib_extruders",
                "end_unload_filament")


def _cfg() -> dict:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return doc["bundle"]["print_task_config"]["result"]["status"]["print_task_config"]


def test_keys_are_a_subset_of_the_upstream_default_plus_paxx_spool_id():
    assert set(_cfg()) <= ALLOWED_KEYS
    assert set(_cfg()["reprint_info"]) <= DEFAULT_KEYS


def test_per_filament_arrays_are_physical_length_and_the_map_table_is_logical_length():
    cfg = _cfg()
    for key in PER_FILAMENT:
        assert len(cfg[key]) == PHYSICAL, key
    assert len(cfg["extruder_map_table"]) == LOGICAL
    assert cfg["extruder_map_table"][:PHYSICAL] == [0, 1, 2, 3] and set(cfg["extruder_map_table"][PHYSICAL:]) == {0}
    assert len(cfg["reprint_info"]["extruder_map_table"]) == LOGICAL


def test_integer_colour_is_an_integer_and_rgba_is_an_eight_hex_string():
    cfg = _cfg()
    assert all(isinstance(c, int) and not isinstance(c, bool) for c in cfg["filament_color"])
    assert all(isinstance(c, str) and len(c) == 8 for c in cfg["filament_color_rgba"])
