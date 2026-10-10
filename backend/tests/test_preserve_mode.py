"""Creator-setting preservation contract, using a programmatically tuned 3MF."""
from __future__ import annotations

import copy
import json
import re
import shutil
import struct
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace
from pathlib import Path

from snapstudio_core.config_io import dump_project_settings, load_project_settings
from snapstudio_core.container import ThreeMF
from snapstudio_core.convert import _settings_summary, convert_to_u1
from snapstudio_core.filaments import PER_FILAMENT_KEYS
from snapstudio_core.preserve import CATEGORY_A, config_diff, display_value
from snapstudio_core import repair as repair_module
from snapstudio_api import service
from snapstudio_api.server import build_server


SETTINGS = "Metadata/project_settings.config"


def _creator_project(tmp_path, *, multi=False):
    source = tmp_path / "creator.3mf"
    shutil.copy2("../examples/sample_cube_foreign.3mf", source)
    tm = ThreeMF.open(source)
    cfg = load_project_settings(tm.read_part(SETTINGS))
    tuned = {
        "nozzle_temperature": ["235"] * 4,
        "nozzle_temperature_initial_layer": ["240"] * 4,
        "nozzle_temperature_range_high": ["250"] * 4,
        "nozzle_temperature_range_low": ["205"] * 4,
        "retraction_length": ["0.8"], "retraction_speed": ["35"],
        "filament_retraction_length": ["0.8"], "filament_retraction_speed": ["35"],
        "outer_wall_speed": "42", "inner_wall_speed": "88", "sparse_infill_speed": "120",
        "outer_wall_acceleration": "2100", "fan_max_speed": ["85"], "fan_min_speed": ["20"],
        "slow_down_layer_time": ["9"], "enable_support": "1", "support_type": "tree(auto)",
        "support_threshold_angle": "38", "layer_height": "0.16", "filament_flow_ratio": ["0.97"],
        "wall_loops": "4", "sparse_infill_density": "18%", "top_surface_pattern": "monotonic",
        "seam_position": "rear", "ironing_type": "top", "brim_type": "outer_only",
        "z_hop": ["0.2"] * 4, "z_hop_types": ["Normal"] * 4,
        "z_hop_when_prime": ["1"] * 4, "prime_tower_width": "45", "prime_volume": "61",
        "wipe_tower_x": ["40"], "wipe_tower_y": ["40"], "wipe_tower_wall_type": "rounded",
        "wipe_tower_extra_spacing": "117%", "print_sequence": "by object",
        "hot_plate_temp": ["72"], "hot_plate_temp_initial_layer": ["78"],
        "filament_type": ["PETG"], "curr_bed_type": "High Temp Plate",
        "default_bed_type": "High Temp Plate", "gcode_comments": "1",
        "single_extruder_multi_material_priming": "1", "wipe_tower_filament": "0",
        "different_settings_to_system": ["enable_support;print_sequence"],
        "print_settings_id": "0.20mm Standard @BBL X1C",
        "filament_settings_id": ["Creator PETG"], "filament_vendor": ["Creator"],
        "default_filament_profile": ["Creator PETG"],
    }
    cfg.update(tuned)
    if multi:
        cfg.update({
            "filament_colour": ["#ff0000", "#00ff00", "#0000ff", "#ffffff"],
            "filament_type": ["PETG", "PETG", "PETG", "PETG"],
            "flush_volumes_matrix": list(range(16)), "flush_volumes_vector": list(range(8)),
            "prime_tower_width": "47", "wipe_tower_x": ["41"], "wipe_tower_y": ["42"],
        })
    tm.replace_part(SETTINGS, dump_project_settings(cfg))
    tm.save(source)
    return source, cfg


def _prepared(result):
    return load_project_settings(ThreeMF.open(result.output_path).read_part(SETTINGS))


def test_preserve_keeps_creator_quality_and_accounts_for_every_change(tmp_path):
    src, before = _creator_project(tmp_path)
    result = convert_to_u1(str(src))
    after = _prepared(result)
    assert result.prepare_mode == "preserve" and result.schema_version == "convert/2"
    for key in CATEGORY_A:
        if key in before:
            assert after[key] == before[key], key
    # Representative process, filament, support, cooling, speed and flow values remain exact.
    # Single-value per-filament settings are replicated to the four creator colours.
    replicated = {
        key for key, value in before.items()
        if key in PER_FILAMENT_KEYS and isinstance(value, list) and len(value) == 1
    }
    for key in replicated:
        assert after[key] == [before[key][0]] * len(before["filament_colour"]), key
    for key in ("retraction_length", "retraction_speed", "filament_retraction_length",
                "filament_retraction_speed", "outer_wall_speed", "inner_wall_speed",
                "sparse_infill_speed", "outer_wall_acceleration", "fan_max_speed",
                "fan_min_speed", "slow_down_layer_time", "slow_down_min_speed",
                "enable_support", "support_type", "support_threshold_angle", "layer_height",
                "filament_flow_ratio", "wall_loops", "top_surface_pattern", "seam_position",
                "ironing_type", "brim_type", "hot_plate_temp"):
        if key in replicated:
            assert after[key] == [before[key][0]] * len(before["filament_colour"]), key
        else:
            assert after[key] == before[key], key
    compat_changed = result.settings_summary["compat_changed"]
    mapped_to_u1 = result.settings_summary["mapped_to_u1"]
    changed = {item["key"] for item in compat_changed}
    assert {"printer_model", "printer_settings_id", "print_settings_id"} <= changed
    print_settings = next(item for item in compat_changed if item["key"] == "print_settings_id")
    assert print_settings["old"] == "0.20mm Standard @BBL X1C"
    assert print_settings["new"] == after["print_settings_id"]
    assert "@Snapmaker U1" in after["print_settings_id"]
    resize = next(item for item in mapped_to_u1 if item["key"] == "filament_retraction_length")
    assert resize["old"] == before["filament_retraction_length"]
    assert resize["new"] == after["filament_retraction_length"]
    assert "filament_retraction_length" not in changed
    assert all(d["key"] in changed | {x["key"] for x in mapped_to_u1}
               | {x["key"] for x in result.settings_summary["could_not_carry"]}
               for d in config_diff(before, after))
    assert result.settings_summary["source_has_creator_settings"] is True
    assert result.settings_summary["summary_schema"] == "settings-summary/2"
    assert len(result.settings_summary["source_config_sha256"]) == 64


def test_recommended_is_opt_in_and_print_sequence_contract(tmp_path):
    src, before = _creator_project(tmp_path)
    preserve = convert_to_u1(str(src), prepare_mode="preserve")
    recommended = convert_to_u1(str(src), prepare_mode="recommended")
    assert _prepared(preserve)["print_sequence"] == "by object"
    assert any("collision check" in w for w in preserve.settings_summary["warnings"])
    assert _prepared(recommended)["print_sequence"] == "by layer"
    assert _prepared(recommended)["nozzle_temperature"] != before["nozzle_temperature"]
    assert any(x["key"] == "nozzle_temperature" for x in recommended.settings_summary["compat_changed"])
    assert not any(x["key"] == "nozzle_temperature" for x in recommended.settings_summary["mapped_to_u1"])
    preview = preserve.settings_summary["recommended_changes"]
    assert preview
    # Preview is the complete real recommended pipeline delta, including the
    # identity/preset work that a profile-swap-only preview missed.
    # "Optional" is precise: Recommended's result differs from the Preserve copy being made now. What both modes
    # change to the same value is already applied and is not offered again.
    applied, full = _prepared(preserve), _prepared(recommended)
    actual_delta = {x["key"] for x in config_diff(before, full)}
    assert {x["key"] for x in preview} == {k for k in actual_delta if applied.get(k, "<absent>") != full.get(k, "<absent>")}
    assert {"nozzle_temperature", "different_settings_to_system", "print_sequence"} <= actual_delta
    # Recommended no longer stamps a legacy "Snapmaker PLA" identity over the filaments:
    # Orca replaced the carried print values from that preset. Identity changes only when
    # the person confirms an installed preset for a slot (Project Materials).
    # (The arrays are widened to the U1's four toolheads; every value is still the creator's.)
    prepared = _prepared(recommended)
    for key in ("filament_settings_id", "filament_vendor", "default_filament_profile"):
        assert set(prepared[key]) == set(before[key]), key


def test_dry_run_starter_and_multimaterial_preservation(tmp_path):
    src, before = _creator_project(tmp_path, multi=True)
    dry = convert_to_u1(str(src), dry_run=True)
    assert dry.output_path == "" and dry.validated_ok and dry.settings_summary["compat_changed"]
    assert not list(tmp_path.glob("creator_SnapmakerU1*.3mf"))
    assert not src.with_suffix(".orig.3mf").exists()
    result = convert_to_u1(str(src))
    after = _prepared(result)
    for key in ("prime_tower_width", "wipe_tower_x", "wipe_tower_y", "flush_volumes_matrix", "flush_volumes_vector"):
        assert after[key] == before[key]

    stl = tmp_path / "tiny.stl"
    stl.write_bytes(
        b"\0" * 80 + struct.pack("<I", 1)
        + struct.pack("<3f", 0, 0, 0)  # normal
        + struct.pack("<3f", 0, 0, 0)
        + struct.pack("<3f", 1, 0, 0)
        + struct.pack("<3f", 0, 1, 0)
        + struct.pack("<H", 0)
    )
    starter = convert_to_u1(str(stl))
    assert starter.prepare_mode == "starter"
    assert starter.settings_summary["warnings"] == [
        "This STL does not include creator slicer settings. Studio will use a U1 starter profile unless you choose another Orca profile."]


def test_support_heavy_creator_values_survive(tmp_path):
    src, before = _creator_project(tmp_path)
    tm = ThreeMF.open(src)
    cfg = load_project_settings(tm.read_part(SETTINGS))
    for key in [k for k in cfg if k.startswith("support_")]:
        cfg[key] = f"creator-{key}"
    tm.replace_part(SETTINGS, dump_project_settings(cfg)); tm.save(src)
    after = _prepared(convert_to_u1(str(src)))
    for key, value in cfg.items():
        if key.startswith("support_"):
            assert after[key] == value, key


def test_summary_copy_guard_and_large_values(tmp_path):
    src, _ = _creator_project(tmp_path)
    tm = ThreeMF.open(src)
    cfg = load_project_settings(tm.read_part(SETTINGS))
    source_gcode = "creator-user-path " + "x" * 400
    cfg["machine_start_gcode"] = source_gcode
    cfg["time_lapse_gcode"] = "bambu private-macro"
    tm.replace_part(SETTINGS, dump_project_settings(cfg)); tm.save(src)
    result = convert_to_u1(str(src))
    blob = json.dumps(result.settings_summary).lower()
    assert not any(word in blob for word in ("optimized", "safe settings", "we fixed", "best", "ready", "clean"))
    assert source_gcode not in blob and "private-macro" not in blob
    start = next(x for x in result.settings_summary["compat_changed"] if x["key"] == "machine_start_gcode")
    assert start["old"] == f"machine G-code replaced with U1 machine G-code ({len(source_gcode)} chars)"
    discarded = next(x for x in result.settings_summary["could_not_carry"] if x["key"] == "time_lapse_gcode")
    assert set(discarded) == {"key", "reason"}
    assert display_value("secret", key="printhost_api_key") == "[redacted]"


def test_per_extruder_vectors_keep_distinct_creator_slots(tmp_path):
    src, _ = _creator_project(tmp_path)
    tm = ThreeMF.open(src)
    cfg = load_project_settings(tm.read_part(SETTINGS))
    cfg.update({
        "nozzle_temperature": ["210", "220", "230", "240"],
        "nozzle_temperature_initial_layer": ["211", "221", "231", "241"],
        "nozzle_temperature_range_high": ["215", "225", "235", "245"],
        "nozzle_temperature_range_low": ["205", "215", "225", "235"],
        "z_hop": ["0.1", "0.2", "0.3", "0.4"],
        "z_hop_types": ["Normal", "Spiral", "Auto Lift", "Normal"],
        "z_hop_when_prime": ["0", "1", "2", "3"],
    })
    tm.replace_part(SETTINGS, dump_project_settings(cfg)); tm.save(src)
    after = _prepared(convert_to_u1(str(src)))
    for key in ("nozzle_temperature", "nozzle_temperature_initial_layer",
                "nozzle_temperature_range_high", "nozzle_temperature_range_low",
                "z_hop", "z_hop_types", "z_hop_when_prime"):
        assert after[key] == cfg[key], key


def test_per_extruder_vector_unusual_size_is_accounted_for(tmp_path):
    src, _ = _creator_project(tmp_path)
    tm = ThreeMF.open(src)
    cfg = load_project_settings(tm.read_part(SETTINGS))
    cfg["nozzle_temperature"] = ["210", "220", "230"]
    tm.replace_part(SETTINGS, dump_project_settings(cfg)); tm.save(src)
    result = convert_to_u1(str(src))
    after = _prepared(result)
    assert after["nozzle_temperature"] == ["210", "220", "230", "230"]
    resize = next(x for x in result.settings_summary["mapped_to_u1"] if x["key"] == "nozzle_temperature")
    assert resize["old"] == ["210", "220", "230"] and resize["new"] == after["nozzle_temperature"]
    assert "carried over" in resize["reason"] and "preserved" in resize["reason"]
    assert "changed" not in resize["reason"]
    assert not any(x["key"] == "nozzle_temperature" for x in result.settings_summary["compat_changed"])
    assert any("nozzle_temperature had 3 slots" in warning for warning in result.settings_summary["warnings"])


def test_mapped_filament_value_substitution_stays_compat_changed():
    before = {"filament_retraction_length": ["0.8", "0.9"]}
    after = {"filament_retraction_length": ["0.8", "replacement"]}
    outcome = SimpleNamespace(report={
        "filament_array_changes": [{
            "key": "filament_retraction_length", "old": before["filament_retraction_length"],
            "new": after["filament_retraction_length"],
            "reason": "resized to match the filament count", "category": "mapped",
        }],
    })

    summary = _settings_summary(before, after, b"test", outcome, "preserve")

    assert [item["key"] for item in summary["compat_changed"]] == ["filament_retraction_length"]
    assert not summary["mapped_to_u1"]


def test_mapped_filament_type_coercions_stay_compat_changed():
    for old, new in (([220], [220.0, 220.0]), ([1], [True, True])):
        before = {"filament_retraction_length": old}
        after = {"filament_retraction_length": new}
        outcome = SimpleNamespace(report={
            "filament_array_changes": [{
                "key": "filament_retraction_length", "old": old, "new": new,
                "reason": "resized to match the filament count", "category": "mapped",
            }],
        })

        summary = _settings_summary(before, after, b"test", outcome, "preserve")

        assert [item["key"] for item in summary["compat_changed"]] == ["filament_retraction_length"]
        assert not summary["mapped_to_u1"]


def test_convert_existing_u1_suffix_does_not_double_output_marker(tmp_path):
    src, _ = _creator_project(tmp_path)
    marked = src.with_name("creator_SnapmakerU1.3mf")
    src.rename(marked)
    result = convert_to_u1(str(marked))
    assert re.fullmatch(r"creator_SnapmakerU1(?:_\d+)?\.3mf", result.output_name)
    assert result.output_name == "creator_SnapmakerU1_2.3mf"
    assert result.output_name.count("_SnapmakerU1") == 1


def test_convert_case_insensitive_u1_suffix_does_not_double_output_marker(tmp_path):
    for stem in ("part_snapmakeru1", "part_SNAPMAKERU1_2"):
        case_dir = tmp_path / stem
        case_dir.mkdir()
        src, _ = _creator_project(case_dir)
        marked = src.with_name(f"{stem}.3mf")
        src.rename(marked)

        result = convert_to_u1(str(marked))

        assert result.output_name.lower().count("snapmakeru1") == 1


def test_preservation_invariant_rejects_unaccounted_mutation(tmp_path, monkeypatch):
    src, _ = _creator_project(tmp_path)
    original_normalize_values = repair_module.normalize_values

    def inject_unaccounted_creator_mutation(cfg):
        changes = original_normalize_values(cfg)
        cfg["outer_wall_speed"] = "synthetically-mutated"
        return changes

    monkeypatch.setattr(repair_module, "normalize_values", inject_unaccounted_creator_mutation)
    try:
        convert_to_u1(str(src))
        assert False, "the independent preservation invariant must reject an unaccounted mutation"
    except ValueError as error:
        assert "outer_wall_speed" in str(error)


def test_api_dry_run_creates_neither_backup_nor_library_record(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    src, _ = _creator_project(tmp_path)
    httpd, token = build_server(port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        headers = {"Content-Type": "application/json", "X-Auth-Token": token}
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/convert",
            data=json.dumps({"path": str(src), "dry_run": True}).encode(), headers=headers)
        with urllib.request.urlopen(request, timeout=5) as response:
            assert json.loads(response.read())["output_path"] == ""
        assert not src.with_suffix(".orig.3mf").exists()
        assert service.library_list()["count"] == 0
    finally:
        httpd.shutdown()


def test_api_prepare_mode_validation_and_legacy_alias():
    httpd, token = build_server(port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{httpd.server_address[1]}/convert"
    headers = {"Content-Type": "application/json", "X-Auth-Token": token}
    sample = str(Path("../examples/sample_cube_foreign.3mf").resolve())
    try:
        bad = urllib.request.Request(endpoint, data=json.dumps({"path": sample, "prepare_mode": "nope"}).encode(), headers=headers)
        try:
            urllib.request.urlopen(bad, timeout=5)
            assert False, "invalid prepare_mode must be rejected"
        except urllib.error.HTTPError as error:
            assert error.code == 400
        legacy = urllib.request.Request(endpoint, data=json.dumps({"path": sample, "prepare_mode": "u1", "dry_run": True}).encode(), headers=headers)
        with urllib.request.urlopen(legacy, timeout=5) as response:
            assert json.loads(response.read())["prepare_mode"] == "recommended"
    finally:
        httpd.shutdown()
