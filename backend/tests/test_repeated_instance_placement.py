"""Issue 93: the placement check judges every build item, not every object id.

One object used by two build items is two places on the plate. The check used to key by object id, so
every instance took the LAST item's footprint and an instance far off the plate could read "inside".
"""
from __future__ import annotations

import zipfile

import pytest

from snapstudio_core import placement, plate_placement as pp, scene
from tests import scene_fixtures as fx

REV = "ab" * 32
SETTINGS = "Metadata/model_settings.config"


def _plain(tmp_path, items, name="p.3mf", with_part_record=True):
    """One cube object `1` used by `items`, with the part record the issue's reproduction carries."""
    extra = {}
    if with_part_record:
        extra[SETTINGS] = fx.model_settings_xml({"1": [("1", "normal_part")]}, [(1, [("1", 0), ("1", 1)])])
    return fx.three_mf(tmp_path / name, fx.model_xml([fx.cube_object("1", 10)], items), extra)


def _rows(report):
    return {row["item_index"]: row for row in report["items"]}


@pytest.mark.parametrize("record", [True, False])
@pytest.mark.parametrize("order", [(500, 100), (100, 500)])
def test_an_in_bounds_instance_cannot_hide_an_off_plate_one(tmp_path, record, order):
    path = _plain(tmp_path, [("1", fx.tf(order[0], 100, 0)), ("1", fx.tf(order[1], 100, 0))],
                  with_part_record=record)
    report = pp.assess(str(path))
    off_item = order.index(500)
    assert report["available"] and report["item_count"] == 2
    assert len(report["off_plate"]) == 1 and report["off_plate"][0]["item_index"] == off_item
    rows = _rows(report)
    assert rows[off_item]["off_plate"] is True and rows[1 - off_item]["off_plate"] is False
    assert rows[off_item]["position"]["x"] == 505.0 and rows[1 - off_item]["position"]["x"] == 105.0
    assert rows[off_item]["edges"] == "right"
    assert [rows[i]["instance_index"] for i in (0, 1)] == [0, 1]
    assert rows[0]["instance_count"] == 2 and rows[0]["object_id"] == "1"
    # the summary names the instance, and does not claim everything is inside
    assert "1 of 2 placed instances" in report["summary"]
    assert f"object 1, instance {off_item + 1} of 2" in report["summary"]
    assert "inside" not in report["summary"]


def test_both_instances_off_the_plate_are_both_reported(tmp_path):
    path = _plain(tmp_path, [("1", fx.tf(500, 100, 0)), ("1", fx.tf(-40, 100, 0))])
    report = pp.assess(str(path))
    assert [row["item_index"] for row in report["off_plate"]] == [0, 1]
    assert {row["edges"] for row in report["off_plate"]} == {"right", "left"}


def test_every_instance_inside_says_so_per_instance(tmp_path):
    report = pp.assess(str(_plain(tmp_path, [("1", fx.tf(50, 50, 0)), ("1", fx.tf(150, 50, 0))])))
    assert report["off_plate"] == [] and report["summary"] == (
        "Every placed instance sits inside the Snapmaker U1's printable area.")


def test_the_engine_placement_check_reports_each_instance(tmp_path):
    path = _plain(tmp_path, [("1", fx.tf(500, 100, 0)), ("1", fx.tf(100, 100, 0))])
    objects = placement.read_objects(str(path))["objects"]
    assert [(o["item_index"], o["instance_index"], o["instance_count"]) for o in objects] == [(0, 0, 2), (1, 1, 2)]
    assert objects[0]["footprint"]["min_x"] == 500.0 and objects[1]["footprint"]["min_x"] == 100.0
    # the part record is present, so read_objects reads the footprint from it for BOTH items
    assert all(o["footprint"] for o in objects)


def test_multiple_components_are_measured_per_instance(tmp_path):
    path = fx.bambu_project(tmp_path / "b.3mf", parts=2, items=[("100", fx.tf(500, 100, 0)), ("100", fx.tf(100, 100, 0))],
                            plates=[(1, [("100", 0), ("100", 1)])])
    report = pp.assess(str(path))
    rows = _rows(report)
    # two 10 mm cubes 20 mm apart: 30 mm wide, starting at the item's translation
    assert rows[0]["bounds_mm"]["min"][0] == 500.0 and rows[0]["bounds_mm"]["max"][0] == 530.0
    assert rows[1]["bounds_mm"]["min"][0] == 100.0 and rows[1]["bounds_mm"]["max"][0] == 130.0
    assert [row["item_index"] for row in report["off_plate"]] == [0]


def test_a_modifier_component_does_not_count_for_either_instance(tmp_path):
    path = fx.bambu_project(tmp_path / "m.3mf", parts=2, roles=["normal_part", "modifier_part"],
                            items=[("100", fx.tf(100, 100, 0)), ("100", fx.tf(150, 100, 0))],
                            plates=[(1, [("100", 0), ("100", 1)])])
    rows = _rows(pp.assess(str(path)))
    assert rows[0]["bounds_mm"]["max"][0] == 110.0 and rows[1]["bounds_mm"]["max"][0] == 160.0
    assert pp.assess(str(path))["off_plate"] == []


def _nested(tmp_path, xs):
    inner = fx.composite_object("5", [("1", None, "-1 0 0 0 1 0 0 0 1 0 0 0")])      # mirror x
    outer = fx.composite_object("6", [("5", None, fx.tf(30, 0, 0))])
    root = fx.model_xml([fx.cube_object("1", 10), inner, outer], [("6", fx.tf(x, 50, 0)) for x in xs])
    return fx.three_mf(tmp_path / "n.3mf", root)


def test_nested_component_transforms_compose_per_instance(tmp_path):
    path = _nested(tmp_path, [0, 400])
    rows = _rows(pp.assess(str(path)))
    # mirror -> x in [-10, 0]; +30 -> [20, 30]; plus the item's own x
    assert (rows[0]["bounds_mm"]["min"][0], rows[0]["bounds_mm"]["max"][0]) == (20.0, 30.0)
    assert (rows[1]["bounds_mm"]["min"][0], rows[1]["bounds_mm"]["max"][0]) == (420.0, 430.0)
    assert [row["item_index"] for row in pp.assess(str(path))["off_plate"]] == [1]
    footprints = [o["footprint"] for o in placement.read_objects(str(path))["objects"]]
    assert [(f["min_x"], f["max_x"]) for f in footprints] == [(20.0, 30.0), (420.0, 430.0)]


def _fixtures(tmp_path):
    return {
        "repeated": _plain(tmp_path, [("1", fx.tf(500, 100, 0)), ("1", fx.tf(100, 100, 0))]),
        "repeated_no_record": _plain(tmp_path, [("1", fx.tf(100, 100, 0)), ("1", fx.tf(-40, 90, 0))],
                                     name="q.3mf", with_part_record=False),
        "components": fx.bambu_project(tmp_path / "c.3mf", parts=3,
                                       items=[("100", fx.tf(20, 30, 0)), ("100", fx.tf(300, 30, 0))],
                                       plates=[(1, [("100", 0), ("100", 1)])]),
        "nested": _nested(tmp_path, [0, 400]),
        "single": fx.bambu_project(tmp_path / "s.3mf", parts=1, items=[("100", fx.tf(300, 60, 0))],
                                   plates=[(1, [("100", 0)])]),
    }


def test_per_instance_results_match_the_scene_contracts_world_bounds(tmp_path):
    for name, path in _fixtures(tmp_path).items():
        sc = scene.build_scene_dict(str(path), REV)
        report = pp.assess(str(path))
        by_id = {n["id"]: n for n in sc["nodes"]}
        assert report["item_count"] == len([n for n in sc["nodes"] if n["parent_id"] is None]), name
        for row in report["items"]:
            top = by_id[f"b{row['item_index']}"]
            assert top["bounds_mm"]["min"] == pytest.approx(row["bounds_mm"]["min"], abs=1e-3), name
            assert top["bounds_mm"]["max"] == pytest.approx(row["bounds_mm"]["max"], abs=1e-3), name
            lo, hi = top["bounds_mm"]["min"], top["bounds_mm"]["max"]
            assert pp._overhang({"min": lo, "max": hi}, report["bed"]) == row["overhang_mm"], name
            assert row["off_plate"] == any(v > 0 for v in row["overhang_mm"].values()), name


def test_plates_are_assigned_per_instance_when_the_object_is_repeated(tmp_path):
    # one object, two instances, one on each plate
    settings = fx.model_settings_xml({"1": [("1", "normal_part")]}, [(1, [("1", 0)]), (2, [("1", 1)])])
    path = fx.three_mf(tmp_path / "mp.3mf", fx.model_xml([fx.cube_object("1", 10)],
                       [("1", fx.tf(50, 50, 0)), ("1", fx.tf(400, 50, 0))]), {SETTINGS: settings})
    report = pp.assess(str(path))
    assert report["plate_count"] == 2 and report["unresolved_objects"] == []
    assert [(p["plate"], p["item_indexes"]) for p in report["plate_fit"]] == [(1, [0]), (2, [1])]
    assert all(p["fits"] for p in report["plate_fit"])


def test_an_oversized_plate_flags_only_its_own_instance(tmp_path):
    big = fx.cube_object("1", 300)
    settings = fx.model_settings_xml({"1": [("1", "normal_part")], "2": [("2", "normal_part")]},
                                     [(1, [("1", 0)]), (2, [("2", 0)])])
    path = fx.three_mf(tmp_path / "ov.3mf", fx.model_xml([big, fx.cube_object("2", 10)],
                       [("1", fx.tf(0, 0, 0)), ("2", fx.tf(400, 0, 0))]), {SETTINGS: settings})
    report = pp.assess(str(path))
    assert [row["item_index"] for row in report["off_plate"]] == [0]


def test_an_instance_the_plate_records_cannot_place_is_unresolved_not_guessed(tmp_path):
    # the record names the object on a plate without saying which of its two instances
    settings = fx.model_settings_xml({"1": [("1", "normal_part")]}, [(1, [("1", None)]), (2, [("2", 0)])])
    settings = settings.replace('<object id="1">', '<object id="1">', 1)
    path = fx.three_mf(tmp_path / "amb.3mf", fx.model_xml([fx.cube_object("1", 10), fx.cube_object("2", 10)],
                       [("1", fx.tf(50, 50, 0)), ("1", fx.tf(80, 50, 0)), ("2", fx.tf(200, 50, 0))]),
                       {SETTINGS: settings})
    report = pp.assess(str(path))
    assert sorted(u["item_index"] for u in report["unresolved_objects"]) == [0, 1]


# --- the fix still works, instance by instance ---------------------------------------------------

def _item_transforms(path):
    with zipfile.ZipFile(path) as archive:
        return placement.build_items(archive.read("3D/3dmodel.model").decode("utf-8"))


def test_prepare_placed_copy_moves_every_instance_by_the_same_amount(tmp_path):
    src = _plain(tmp_path, [("1", fx.tf(-5, 100, 0)), ("1", fx.tf(100, 100, 0))])
    original = src.read_bytes()
    result = pp.prepare_placed_copy(str(src), out_dir=str(tmp_path / "out"))
    assert result["ok"] is True, result.get("reason")
    assert result["objects_moved"] == 2 and result["offset_mm"] == {"x": 6.0, "y": 0.0}
    assert result["after"]["off_plate"] == []
    assert src.read_bytes() == original                      # the original is never modified
    before = [placement.parse_transform(i["transform"]) for i in _item_transforms(src)]
    after = [placement.parse_transform(i["transform"]) for i in _item_transforms(result["output_path"])]
    assert [round(a[3][0] - b[3][0], 4) for a, b in zip(after, before)] == [6.0, 6.0]
    assert result["verification"]["passed"] is True


def test_prepare_placed_copy_handles_an_item_with_no_transform(tmp_path):
    src = _plain(tmp_path, [("1", None), ("1", fx.tf(60, 0.5, 0))])
    report = pp.assess(str(src))
    assert [row["item_index"] for row in report["off_plate"]] == [0, 1]
    result = pp.prepare_placed_copy(str(src), out_dir=str(tmp_path / "out"))
    assert result["ok"] is True, result.get("reason")
    assert result["verification"]["passed"] is True and result["after"]["off_plate"] == []


def test_prepare_placed_copy_refuses_when_one_move_cannot_fix_instances(tmp_path):
    src = _plain(tmp_path, [("1", fx.tf(500, 100, 0)), ("1", fx.tf(100, 100, 0))])
    result = pp.prepare_placed_copy(str(src), out_dir=str(tmp_path / "out"))
    assert result["ok"] is False and "wider than the plate" in result["reason"]
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").iterdir())


def test_a_millimetre_project_with_one_item_per_object_reports_as_before(tmp_path):
    path = fx.plain_cube_3mf(tmp_path / "one.3mf", at=(300, 60, 0))
    report = pp.assess(str(path))
    assert report["summary"].startswith("1 object falls outside")
    assert [row["instance_count"] for row in report["items"]] == [1]
