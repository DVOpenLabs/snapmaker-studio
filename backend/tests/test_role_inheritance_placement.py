"""Printing roles propagate down through assemblies (one rule, ``roles``), seen through the service entry
points: preflight, Ready Now analysis, and the scene, for the placed footprint and height.

A 300 mm column sits under a nested assembly next to a 10 mm printable sibling. If the volume's role says it
does not print, it must not make the object look too tall; if no role says so (missing record), or the
records conflict, it counts."""
from __future__ import annotations

import pytest

from snapstudio_api import service
from snapstudio_core import plate_placement as pp, scene
from tests import scene_fixtures as fx
from tests.test_travel_and_move_writer import _facts

SETTINGS = "Metadata/model_settings.config"
HELPER_ROLES = ["negative_part", "modifier_part", "support_blocker", "support_enforcer"]
REV = "ab" * 32


def pillar(oid, height, origin=(40.0, 0.0, 0.0)):
    """A 10 x 10 mm column `height` tall: tall, but small enough to sit on the plate sideways."""
    ox, oy, oz = origin
    verts = [(ox, oy, oz), (ox + 10, oy, oz), (ox + 10, oy + 10, oz), (ox, oy + 10, oz),
             (ox, oy, oz + height), (ox + 10, oy, oz + height), (ox + 10, oy + 10, oz + height),
             (ox, oy + 10, oz + height)]
    return f'<object id="{oid}" type="model">{fx.mesh_xml(verts, fx.CUBE_TRIS)}</object>'


def nested_assembly(tmp_path, records: dict, name="nested.3mf"):
    """Root object 100 = printable mesh 1 (10 mm) + assembly 5; assembly 5 = mesh 3 (300 mm).
    ``records`` is the settings objects: {object id: [(part id, subtype), ...]}."""
    sub = fx.sub_model_xml([fx.cube_object("1", 10), pillar("3", 300)])
    assembly = fx.composite_object("5", [("3", "/3D/Objects/o.model", None)])
    top = fx.composite_object("100", [("1", "/3D/Objects/o.model", None), ("5", None, None)])
    root = fx.model_xml([assembly, top], [("100", fx.tf(20, 20, 0))])
    settings = fx.model_settings_xml(records, [(1, [("100", 0)])])
    return str(fx.three_mf(tmp_path / name, root, {"3D/Objects/o.model": sub, SETTINGS: settings}))


def on_assembly(role):
    return {"100": [("1", "normal_part"), ("5", role)]}


def on_nested_record(role):
    return {"100": [("1", "normal_part"), ("5", "normal_part")], "5": [("3", role)]}


U1 = {"printer_id": "snapmaker_u1"}


def bed_fit_check(path, monkeypatch):
    monkeypatch.setattr(service, "printer_facts", _facts(U1))
    return next(c for c in service.preflight(path, "h")["checks"] if c["id"] == "bed.fit")


def ready_placement(path):
    target = service._placement_target({"identity": U1})
    service._READY_CACHE.clear()
    return service._ready_analysis(path, target, need_placement=True)[2]


@pytest.mark.parametrize("where", [on_assembly, on_nested_record], ids=["on_assembly", "on_nested_record"])
@pytest.mark.parametrize("role", HELPER_ROLES)
def test_a_helper_role_applies_to_everything_beneath_it(tmp_path, monkeypatch, role, where):
    path = nested_assembly(tmp_path, where(role))
    # preflight: the 300 mm helper volume is not height the print has
    check = bed_fit_check(path, monkeypatch)
    assert check["result"] == "ok" and check["confidence"] == "confirmed", check["evidence"]
    # Ready Now: the same placement, from the cached analysis
    placement = ready_placement(path)
    [row] = placement["items"]
    assert row["bounds_mm"]["max"][2] == 10.0 and row["bounds_mm"]["max"][0] == 30.0
    assert pp.over_height(placement) == [] and placement["off_plate"] == []


@pytest.mark.parametrize("role", HELPER_ROLES)
def test_the_scene_and_the_footprint_agree_that_the_volume_does_not_print(tmp_path, role):
    path = nested_assembly(tmp_path, on_assembly(role))
    sc = scene.build_scene_dict(path, REV)
    leaf = next(n for n in sc["nodes"] if n["resource"]["object_id"] == "3")
    assert leaf["printable"] is False and leaf["role_context"] not in (None, "part")
    top = next(n for n in sc["nodes"] if n["id"] == "b0")
    assert top["bounds_mm"]["max"][2] == 10.0                      # the scene's world bounds: printing parts only
    [row] = pp.assess(path)["items"]
    assert row["bounds_mm"]["max"] == top["bounds_mm"]["max"]


def test_a_missing_role_is_a_normal_part_and_counts(tmp_path, monkeypatch):
    path = nested_assembly(tmp_path, {"100": [("1", "normal_part")]})        # no record for the assembly
    check = bed_fit_check(path, monkeypatch)
    assert check["result"] == "attention" and "300" in check["evidence"] and "height limit" in check["evidence"]
    assert pp.over_height(ready_placement(path))


def test_conflicting_records_are_unknown_and_count_never_falsely_small(tmp_path, monkeypatch):
    path = nested_assembly(tmp_path, {"100": [("1", "normal_part"), ("5", "modifier_part"), ("5", "normal_part")]})
    check = bed_fit_check(path, monkeypatch)
    assert check["result"] == "attention" and "300" in check["evidence"]
    sc = scene.build_scene_dict(path, REV)
    leaf = next(n for n in sc["nodes"] if n["resource"]["object_id"] == "3")
    assert leaf["printable"] is None                                          # the scene reports unknown
    assert pp.over_height(ready_placement(path))                              # the footprint cannot prove it away


def test_a_child_cannot_print_again_beneath_a_non_printing_assembly(tmp_path, monkeypatch):
    # the assembly is a modifier; the record for its child says normal_part: the modifier still wins
    records = {"100": [("1", "normal_part"), ("5", "modifier_part")], "5": [("3", "normal_part")]}
    path = nested_assembly(tmp_path, records)
    assert bed_fit_check(path, monkeypatch)["result"] == "ok"
    assert pp.assess(path)["items"][0]["bounds_mm"]["max"][2] == 10.0


# --- whole-model extents and the other size consumers share the rule -------------------------------------

SEAM_WORDS = ["precise_seam_center", "precise_seam_left", "precise_seam_right",
              "precise_seam_enforced", "precise_seam_blocked", "precise_seam_neutral"]


@pytest.mark.parametrize("role", HELPER_ROLES + SEAM_WORDS)
def test_every_consumer_of_the_extents_agrees_that_a_helper_volume_does_not_count(tmp_path, monkeypatch, role):
    from snapstudio_core import geometry, layout
    from snapstudio_core.intelligence import project_info
    path = nested_assembly(tmp_path, on_assembly(role))
    assert project_info(path)["dimensions_mm"] == {"x": 10.0, "y": 10.0, "z": 10.0}      # overall extents
    assert [i["dimensions"]["z"] for i in geometry.build_item_dims(path)] == [10.0]       # placed items
    assert layout.assess_layout(path)["status"] == "pass"                                  # plate-fit layout
    check = bed_fit_check(path, monkeypatch)                                               # preflight
    assert check["result"] == "ok" and check["confidence"] == "confirmed"
    assert pp.over_height(ready_placement(path)) == []                                     # Ready Now
    sc = scene.build_scene_dict(path, REV)                                                 # scene
    assert next(n for n in sc["nodes"] if n["resource"]["object_id"] == "3")["printable"] is False


def test_the_overall_extents_still_count_everything_when_no_role_says_otherwise(tmp_path):
    from snapstudio_core.intelligence import project_info
    path = nested_assembly(tmp_path, {"100": [("1", "normal_part")]})
    assert project_info(path)["dimensions_mm"]["z"] == 300.0


@pytest.mark.parametrize("word", SEAM_WORDS)
def test_orcas_precise_seam_helpers_are_known_non_printing_roles(tmp_path, monkeypatch, word):
    from snapstudio_core.assignments import MODIFIER, ROLE_UNKNOWN, role_of
    assert role_of(word) == MODIFIER and role_of(word) != ROLE_UNKNOWN
    path = nested_assembly(tmp_path, on_nested_record(word))
    assert bed_fit_check(path, monkeypatch)["result"] == "ok"
    sc = scene.build_scene_dict(path, REV)
    assert "UNKNOWN_VOLUME_ROLE" not in [l["code"] for l in sc["limitations"]]


def test_an_unrecognised_role_word_stays_conservative(tmp_path, monkeypatch):
    path = nested_assembly(tmp_path, on_assembly("precise_seam_sideways"))
    assert bed_fit_check(path, monkeypatch)["result"] == "attention"                       # counts: 300 mm tall
    from snapstudio_core.intelligence import project_info
    assert project_info(path)["dimensions_mm"]["z"] == 300.0
