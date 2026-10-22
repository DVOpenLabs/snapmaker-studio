"""Snapmaker Orca import compatibility rules.

Each rule exists because leaving a value alone produces a worse print or a broken
import on a U1. The tests therefore check two things per rule: that it fires when
it should, and — more importantly — that it stays out of the way when the value
is the creator's deliberate choice. A compatibility pass that quietly overrides
intent is a bug, not a feature.
"""
from __future__ import annotations

import json
import zipfile

from snapstudio_core import orca_import
from snapstudio_core.container import ThreeMF


# --- exclude object ---------------------------------------------------------

def test_exclude_object_is_enabled_when_off():
    cfg = {"exclude_object": "0"}
    changes = orca_import.apply_compatibility(cfg)
    assert cfg["exclude_object"] == "1"
    change = next(c for c in changes if c["key"] == "exclude_object")
    assert change["old"] == "0"
    assert "adaptive" in change["explanation"].lower() or "cancel" in change["explanation"].lower()


def test_exclude_object_already_on_is_not_reported_as_a_change():
    cfg = {"exclude_object": "1"}
    assert [c for c in orca_import.apply_compatibility(cfg) if c["key"] == "exclude_object"] == []


def test_exclude_object_is_added_when_the_key_is_missing_entirely():
    cfg = {}
    orca_import.apply_compatibility(cfg)
    assert cfg["exclude_object"] == "1"


# --- brim -------------------------------------------------------------------

def test_automatic_brim_is_turned_off():
    cfg = {"brim_type": "auto_brim"}
    changes = orca_import.apply_compatibility(cfg)
    assert cfg["brim_type"] == "no_brim"
    assert any(c["key"] == "brim_type" for c in changes)


def test_a_brim_the_creator_chose_is_left_alone():
    """This is the line the rule must not cross: automatic means "slicer decides",
    an explicit brim means the creator decided."""
    for chosen in ("outer_brim", "inner_brim", "outer_and_inner", "brim_ears", "no_brim"):
        cfg = {"brim_type": chosen}
        orca_import.apply_compatibility(cfg)
        assert cfg["brim_type"] == chosen


# --- tree support with variable layer height --------------------------------

def test_tree_support_with_adaptive_layers_becomes_hybrid():
    cfg = {"adaptive_layer_height": "1", "support_type": "tree(auto)",
           "support_style": "organic"}
    changes = orca_import.apply_compatibility(cfg)
    assert cfg["support_style"] == "tree_hybrid"
    assert any(c["key"] == "support_style" for c in changes)


def test_tree_support_without_adaptive_layers_is_untouched():
    cfg = {"adaptive_layer_height": "0", "support_type": "tree(auto)",
           "support_style": "organic"}
    orca_import.apply_compatibility(cfg)
    assert cfg["support_style"] == "organic"


def test_adaptive_layers_without_tree_support_is_untouched():
    cfg = {"adaptive_layer_height": "1", "support_type": "normal(auto)",
           "support_style": "grid"}
    orca_import.apply_compatibility(cfg)
    assert cfg["support_style"] == "grid"


def test_a_support_style_outside_the_tree_family_is_untouched():
    cfg = {"adaptive_layer_height": "1", "support_type": "tree(auto)",
           "support_style": "default"}
    orca_import.apply_compatibility(cfg)
    assert cfg["support_style"] == "default"


# --- filament array validity ------------------------------------------------

def test_empty_adaptive_volumetric_entries_are_filled():
    cfg = {"filament_adaptive_volumetric_speed": ["1", "", "1", ""]}
    orca_import.apply_compatibility(cfg, filament_count=4)
    assert "" not in cfg["filament_adaptive_volumetric_speed"]
    assert len(cfg["filament_adaptive_volumetric_speed"]) == 4


def test_filament_arrays_are_resized_to_the_slot_count():
    cfg = {"filament_flush_temp": ["220"]}
    orca_import.apply_compatibility(cfg, filament_count=4)
    assert cfg["filament_flush_temp"] == ["220", "220", "220", "220"]


def test_over_long_filament_array_is_trimmed():
    cfg = {"filament_flush_temp": ["220"] * 8}
    orca_import.apply_compatibility(cfg, filament_count=4)
    assert len(cfg["filament_flush_temp"]) == 4


def test_self_index_is_renumbered_positionally_not_copied():
    """Slot N has to say N. Padding it from a neighbour would be silently wrong."""
    cfg = {"filament_self_index": ["1", "1", "1"]}
    orca_import.apply_compatibility(cfg, filament_count=4)
    assert cfg["filament_self_index"] == ["1", "2", "3", "4"]


def test_correct_self_index_is_not_touched():
    cfg = {"filament_self_index": ["1", "2", "3", "4"]}
    changes = orca_import.apply_compatibility(cfg, filament_count=4)
    assert not [c for c in changes if c["key"] == "filament_self_index"]


def test_filament_arrays_are_left_alone_when_the_slot_count_is_unknown():
    cfg = {"filament_flush_temp": ["220"]}
    orca_import.apply_compatibility(cfg, filament_count=0)
    assert cfg["filament_flush_temp"] == ["220"]


def test_an_all_empty_array_is_not_invented_into_values():
    """With nothing to fill from, Studio must not make a number up."""
    cfg = {"filament_adaptive_volumetric_speed": ["", ""]}
    orca_import.apply_compatibility(cfg, filament_count=2)
    assert cfg["filament_adaptive_volumetric_speed"] == ["", ""]


# --- raft expansion ---------------------------------------------------------

def test_negative_raft_expansion_is_restored_from_the_u1_profile():
    cfg = {"raft_first_layer_expansion": "-2"}
    changes = orca_import.apply_compatibility(cfg)
    assert float(cfg["raft_first_layer_expansion"]) >= 0
    assert cfg["raft_first_layer_expansion"] == orca_import.u1_template()[
        "raft_first_layer_expansion"]
    assert any(c["key"] == "raft_first_layer_expansion" for c in changes)


def test_valid_raft_expansion_is_untouched():
    cfg = {"raft_first_layer_expansion": "3"}
    orca_import.apply_compatibility(cfg)
    assert cfg["raft_first_layer_expansion"] == "3"


def test_unparseable_raft_expansion_is_left_alone():
    cfg = {"raft_first_layer_expansion": "auto"}
    orca_import.apply_compatibility(cfg)
    assert cfg["raft_first_layer_expansion"] == "auto"


# --- reporting --------------------------------------------------------------

def test_every_change_carries_an_old_value_a_reason_and_an_explanation():
    cfg = {"exclude_object": "0", "brim_type": "auto_brim",
           "raft_first_layer_expansion": "-1"}
    for change in orca_import.apply_compatibility(cfg):
        assert "old" in change and "new" in change
        assert change["reason"]
        assert change["explanation"]
        assert change["category"] == "orca-compatibility"


def test_a_clean_u1_project_produces_no_changes():
    cfg = {"exclude_object": "1", "brim_type": "no_brim",
           "raft_first_layer_expansion": "2", "support_style": "default"}
    assert orca_import.apply_compatibility(cfg) == []


# --- slice cache ------------------------------------------------------------

def _project(tmp_path, extra=None):
    p = tmp_path / "p.3mf"
    parts = {
        "3D/3dmodel.model": '<model unit="millimeter"><build/></model>',
        "Metadata/project_settings.config": json.dumps({"printer_model": "Snapmaker U1"}),
    }
    parts.update(extra or {})
    with zipfile.ZipFile(p, "w") as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return ThreeMF.open(p)


def test_slice_cache_is_removed(tmp_path):
    tm = _project(tmp_path, {
        "Metadata/plate_1.gcode": "G1 X0\n",
        "Metadata/plate_1.json": "{}",
        "Metadata/plate_2.gcode": "G1 X0\n",
    })
    removed = orca_import.strip_slice_cache(tm)
    assert len(removed) == 3
    assert not any(p.endswith(".gcode") for p in tm.list_parts())
    assert all(r["reason"] for r in removed)


def test_plate_images_are_kept(tmp_path):
    """The plate picture is how a person recognises their own project."""
    tm = _project(tmp_path, {
        "Metadata/plate_1.png": "img",
        "Metadata/plate_1_small.png": "img",
        "Metadata/plate_1.gcode": "G1\n",
    })
    orca_import.strip_slice_cache(tm)
    assert "Metadata/plate_1.png" in tm.list_parts()
    assert "Metadata/plate_1_small.png" in tm.list_parts()


def test_unrelated_parts_are_kept(tmp_path):
    tm = _project(tmp_path, {"Metadata/plate_1.gcode": "G1\n"})
    orca_import.strip_slice_cache(tm)
    assert "3D/3dmodel.model" in tm.list_parts()
    assert "Metadata/project_settings.config" in tm.list_parts()


def test_project_without_slice_cache_reports_nothing_removed(tmp_path):
    assert orca_import.strip_slice_cache(_project(tmp_path)) == []


def test_removed_parts_do_not_come_back_when_saved(tmp_path):
    tm = _project(tmp_path, {"Metadata/plate_1.gcode": "G1\n"})
    orca_import.strip_slice_cache(tm)
    out = tmp_path / "out.3mf"
    tm.save(out)
    with zipfile.ZipFile(out) as z:
        assert "Metadata/plate_1.gcode" not in z.namelist()


# --- end to end through the real conversion ---------------------------------

def test_conversion_applies_compatibility_and_strips_the_cache(tmp_path):
    from snapstudio_core.convert import convert_to_u1

    src = tmp_path / "foreign.3mf"
    settings = {
        "printer_model": "Bambu Lab X1 Carbon",
        "filament_colour": ["#FF0000", "#00FF00"],
        "filament_type": ["PLA", "PLA"],
        "nozzle_diameter": ["0.4", "0.4"],
        "exclude_object": "0",
        "brim_type": "auto_brim",
    }
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("3D/3dmodel.model", '<model unit="millimeter"><build/></model>')
        z.writestr("Metadata/project_settings.config", json.dumps(settings))
        z.writestr("Metadata/plate_1.gcode", "G1 X0\n")

    result = convert_to_u1(str(src), out_dir=str(tmp_path / "out"))
    with zipfile.ZipFile(result.output_path) as z:
        assert "Metadata/plate_1.gcode" not in z.namelist()
        after = json.loads(z.read("Metadata/project_settings.config"))
    assert after["exclude_object"] == "1"
    assert after["brim_type"] == "no_brim"


def test_compatibility_changes_are_explained_in_the_conversion_summary(tmp_path):
    """A user must be able to see why their brim setting changed."""
    from snapstudio_core.convert import convert_to_u1

    src = tmp_path / "foreign2.3mf"
    settings = {"printer_model": "Bambu Lab X1 Carbon", "brim_type": "auto_brim",
                "filament_colour": ["#FF0000"], "filament_type": ["PLA"]}
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("3D/3dmodel.model", '<model unit="millimeter"><build/></model>')
        z.writestr("Metadata/project_settings.config", json.dumps(settings))

    result = convert_to_u1(str(src), out_dir=str(tmp_path / "out"))
    reported = {c["key"] for c in result.settings_summary["compat_changed"]}
    assert "brim_type" in reported
