"""Studio's own declarations must not defeat a confirmed preset on a slot that shares it.

Measured on Orca 2.3.6: a declared print value is copied, with its declaration, to every slot
using the same installed preset. In Preserve, Studio declares the creator's temperatures on the
slots it did not map. If one of those shares a preset with a mapped slot, that declaration would
propagate into the mapped slot. Studio therefore withdraws ITS OWN declarations from the whole
same-preset group - and never one the source project made.
"""
from __future__ import annotations

import pytest

from snapstudio_core import materials_fidelity as mf
from snapstudio_core import project_materials as pm
from snapstudio_core.convert import convert_to_u1
from tests.test_project_materials import (MATTE, SNAPSPEED, _cfg, _prepared, _project, catalog,  # noqa: F401
                                          profiles)

PETG = "Generic PETG @U1"
# slots: 1 and 2 already name the real Matte preset (slot 2 gets the person's confirmation), slot 3 is PETG
SHARED = dict(filament_settings_id=[MATTE, "Generic PLA @BBL H2D", PETG],
              filament_vendor=["Snapmaker", "Snapmaker", "Generic"])


def _run(tmp_path, catalog, name, confirmed, cfg=None, mode="preserve"):
    src = _project(tmp_path, cfg or _cfg(**SHARED), name=f"{name}.3mf")
    return convert_to_u1(str(src), out_dir=str(tmp_path / name), prepare_mode=mode,
                         confirmed_presets=confirmed, filament_catalog=catalog,
                         confirmed_colours={1: "#00AA11"} if confirmed and 1 in confirmed else None)


def test_a_studio_added_declaration_is_withdrawn_from_the_whole_group(tmp_path, catalog):
    plain = _prepared(convert_to_u1(str(_project(tmp_path, _cfg(**SHARED), "p.3mf")), out_dir=str(tmp_path / "p")))
    assert plain["different_settings_to_system"][1:4] == ["nozzle_temperature"] * 3     # what Studio adds today
    res = _run(tmp_path, catalog, "a", {1: MATTE})
    entries = _prepared(res)["different_settings_to_system"]
    # slots 1 and 2 are now one Matte group: Studio's declaration is gone from BOTH, so the preset decides
    assert entries[1] == "" and entries[2] == ""
    assert entries[3] == "nozzle_temperature"        # slot 3 is on another preset and is left alone
    withdrawn = {w["slot"]: w for w in res.settings_summary["project_materials"]["fidelity"]["slots"]
                 if w["declarations"]["withdrawn_studio_added"]}
    assert set(withdrawn) == {0, 1}
    assert {s["declarations"]["withdrawn_reason"] for s in withdrawn.values()} == {"shared_preset_group"}
    assert res.validated_ok is True


def test_a_source_authored_declaration_is_preserved_and_the_guard_still_applies(tmp_path, catalog):
    cfg = _cfg(**SHARED, different_settings_to_system=["", "nozzle_temperature", "", "", ""])
    res = _run(tmp_path, catalog, "b", {1: MATTE}, cfg)
    entries = _prepared(res)["different_settings_to_system"]
    assert entries[1] == "nozzle_temperature"        # the source declared it on slot 1: never removed
    assert entries[2] == ""                          # only Studio's own was withdrawn from slot 2
    rec = res.settings_summary["project_materials"]["fidelity"]
    slot1 = rec["slots"][0]["declarations"]
    assert slot1["source"] == ["nozzle_temperature"] and slot1["retained"] == ["nozzle_temperature"]
    assert slot1["withdrawn_studio_added"] == []
    # a vendor declaration from the source that conflicts across the group still blocks Preserve
    conflicted = _cfg(filament_settings_id=[MATTE, MATTE, PETG], filament_vendor=["Yoopai", "Snapmaker", "Generic"],
                      different_settings_to_system=["", "filament_vendor", "", "", ""])
    blocked = _run(tmp_path, catalog, "c", {2: PETG}, conflicted)
    assert blocked.blocked is True and blocked.output_path == ""


def test_slots_on_different_presets_lose_nothing(tmp_path, catalog):
    cfg = _cfg(filament_settings_id=[SNAPSPEED, "Generic PLA @BBL H2D", PETG], filament_vendor=["S", "S", "G"])
    res = _run(tmp_path, catalog, "d", {1: MATTE}, cfg)
    entries = _prepared(res)["different_settings_to_system"]
    assert entries[1] == "nozzle_temperature"        # slot 1 is on SnapSpeed, the confirmed slot is on Matte
    assert entries[2] == ""                          # the confirmed slot itself
    assert entries[3] == "nozzle_temperature"
    rec = res.settings_summary["project_materials"]["fidelity"]
    assert rec["withdrawn_groups"] == []
    assert rec["slots"][0]["declarations"]["declared_by_studio"] == ["nozzle_temperature"]


def test_without_project_materials_nothing_is_withdrawn(tmp_path, catalog):
    res = convert_to_u1(str(_project(tmp_path, _cfg(**SHARED), "n.3mf")), out_dir=str(tmp_path / "n"))
    assert _prepared(res)["different_settings_to_system"][1:4] == ["nozzle_temperature"] * 3
    assert "project_materials" not in res.settings_summary
    only_colour = _run(tmp_path, catalog, "n2", None)
    assert _prepared(only_colour)["different_settings_to_system"][1:4] == ["nozzle_temperature"] * 3


def test_fidelity_separates_source_studio_added_and_withdrawn(tmp_path, catalog):
    cfg = _cfg(**SHARED, different_settings_to_system=["", "nozzle_temperature", "", "", ""])
    res = _run(tmp_path, catalog, "f", {1: MATTE}, cfg)
    rec = res.settings_summary["project_materials"]["fidelity"]
    s1, s2, s3 = (s["declarations"] for s in rec["slots"])
    # slot 1: the source's own declaration stays
    assert (s1["source"], s1["retained"], s1["declared_by_studio"], s1["withdrawn_studio_added"]) == \
        (["nozzle_temperature"], ["nozzle_temperature"], [], [])
    # slot 2 (the confirmed slot): Studio's declaration was added and then withdrawn
    assert (s2["source"], s2["retained"], s2["declared_by_studio"], s2["withdrawn_studio_added"]) == \
        ([], [], [], ["nozzle_temperature"])
    # slot 3 is on another preset: Studio's declaration stays and is labelled as Studio's
    assert (s3["source"], s3["declared_by_studio"], s3["withdrawn_studio_added"]) == \
        ([], ["nozzle_temperature"], [])
    assert rec["withdrawn_groups"] == [{"preset": MATTE, "slots": [0, 1], "keys": ["nozzle_temperature"]}]
    assert ("Slots 1 and 2 use 'Snapmaker PLA Matte @U1'. Studio removed its own nozzle-temperature "
            "declarations from this shared-preset group so Snapmaker Orca can apply the installed "
            "preset consistently.") in rec["lines"]
    # the source's own declaration is reported on its own line
    assert ("Slot 1: the project's own declaration of nozzle_temperature remains. Studio does not remove "
            "declarations the source made.") in rec["lines"]


def test_the_group_line_names_the_slots_the_preset_and_the_declarations(tmp_path, catalog):
    cfg = _cfg(filament_settings_id=[MATTE, MATTE, PETG], filament_vendor=["A", "A", "G"])
    res = _run(tmp_path, catalog, "g", {1: MATTE}, cfg)
    rec = res.settings_summary["project_materials"]["fidelity"]
    assert ("Slots 1 and 2 use 'Snapmaker PLA Matte @U1'. Studio removed its own nozzle-temperature "
            "declarations from this shared-preset group so Snapmaker Orca can apply the installed "
            "preset consistently.") in rec["lines"]
    assert rec["withdrawn_groups"] == [{"preset": MATTE, "slots": [0, 1], "keys": ["nozzle_temperature"]}]
    # the per-slot withdrawal line is not repeated for slots the group line covers
    assert not any(l.startswith("Slot 1: Studio did not declare") for l in rec["lines"])


def test_group_withdrawal_keeps_a_source_declaration_and_says_so_separately(tmp_path, catalog):
    cfg = _cfg(filament_settings_id=[MATTE, MATTE, PETG], filament_vendor=["A", "A", "G"],
               different_settings_to_system=["", "filament_flow_ratio", "", "", ""])
    res = _run(tmp_path, catalog, "h", {1: MATTE}, cfg)
    entries = _prepared(res)["different_settings_to_system"]
    assert entries[1] == "filament_flow_ratio" and entries[2] == ""
    rec = res.settings_summary["project_materials"]["fidelity"]
    assert any("Slot 1: the project's own declaration of filament_flow_ratio remains." in l for l in rec["lines"])


def test_same_preset_groups_helper(catalog):
    cfg = _cfg(filament_settings_id=[MATTE, "Generic PLA @BBL H2D", MATTE])
    assert pm.same_preset_groups(cfg, catalog, "0.4") == {MATTE: [0, 2]}
    assert pm.same_preset_groups(cfg, None, "0.4") == {}
