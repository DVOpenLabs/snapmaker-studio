"""Issue 91: the size of an object is not where it sits.

Size-only statements (how big is each object) and placed statements (where is each instance, on which
plate) are separate facts. Each consumer says which one it uses; a size never claims a position, and the
combined extents of separated objects or plates never become "scale or split" advice.
"""
from __future__ import annotations

import pytest

from snapstudio_api import service
from snapstudio_core import bed_fit, geometry, plate_placement as pp
from snapstudio_core.intelligence import project_info
from tests import scene_fixtures as fx

SETTINGS = "Metadata/model_settings.config"


def box_object(oid, dx, dy, dz, origin=(0.0, 0.0, 0.0)):
    ox, oy, oz = origin
    verts = [(ox, oy, oz), (ox + dx, oy, oz), (ox + dx, oy + dy, oz), (ox, oy + dy, oz),
             (ox, oy, oz + dz), (ox + dx, oy, oz + dz), (ox + dx, oy + dy, oz + dz), (ox, oy + dy, oz + dz)]
    return f'<object id="{oid}" type="model">{fx.mesh_xml(verts, fx.CUBE_TRIS)}</object>'


def project(tmp_path, objects, items, name="p.3mf", settings=None, unit="millimeter"):
    extra = {SETTINGS: settings} if settings else None
    return str(fx.three_mf(tmp_path / name, fx.model_xml(objects, items, unit=unit), extra))


def texts(result):
    return " ".join(f["text"] for f in result["findings"]) + " " + result["overall_text"]


# --- size is per object and before any build item acts on it ----------------------------------------

def test_object_size_ignores_where_the_item_puts_the_object(tmp_path):
    path = project(tmp_path, [box_object("1", 100, 20, 10)],
                   [("1", fx.tf(500, 40, 0)), ("1", "0 1 0 -1 0 0 0 0 1 50 50 0")])      # moved; and turned 90 degrees
    sizes = geometry.object_sizes(path)
    assert sizes == [{"object_id": "1", "instance_count": 2, "dimensions": {"x": 100.0, "y": 20.0, "z": 10.0}}]
    placed = geometry.build_item_dims(path)
    assert placed[0]["dimensions"] == {"x": 100.0, "y": 20.0, "z": 10.0}
    assert placed[1]["dimensions"] == {"x": 20.0, "y": 100.0, "z": 10.0}                   # placed bounds follow the turn


def test_object_size_is_in_millimetres_for_an_inch_project(tmp_path):
    path = project(tmp_path, [box_object("1", 12, 1, 1)], [("1", fx.tf(0, 0, 0))], unit="inch")
    assert geometry.object_sizes(path)[0]["dimensions"] == {"x": 304.8, "y": 25.4, "z": 25.4}
    info = project_info(path)
    assert info["object_sizes_mm"][0]["dimensions_mm"]["x"] == 304.8


def test_project_info_keeps_size_and_placed_apart(tmp_path):
    path = project(tmp_path, [fx.cube_object("1", 10)], [("1", fx.tf(500, 100, 0)), ("1", fx.tf(100, 100, 0))])
    info = project_info(path)
    assert info["dimensions_basis"] == "overall_extents_by_size"
    assert info["object_sizes_mm"] == [{"object_id": "1", "instance_count": 2,
                                        "dimensions_mm": {"x": 10.0, "y": 10.0, "z": 10.0}}]
    placed = info["placed"]
    assert placed["available"] and placed["basis"] == "placed_bounds" and placed["plate_count"] == 1
    assert [i["bounds_mm"]["min"][0] for i in placed["instances"]] == [500.0, 100.0]
    assert placed["combined_extent_mm"] == {"x": 410.0, "y": 10.0}


def test_stl_has_a_size_and_no_position(tmp_path):
    path = str(fx.binary_stl(tmp_path / "c.stl", 20.0))
    info = project_info(path)
    assert info["object_sizes_mm"][0]["dimensions_mm"] == {"x": 20.0, "y": 20.0, "z": 20.0}
    assert info["placed"]["available"] is False and info["placed"]["instances"] == []


# --- translated: a small object moved off the plate -----------------------------------------------------

def test_a_small_object_moved_off_the_plate_is_not_reported_as_fitting(tmp_path):
    path = project(tmp_path, [fx.cube_object("1", 10)], [("1", fx.tf(500, 100, 0))])
    result = service.bed_fit(path)
    assert result["overall_level"] == "risk"
    text = texts(result)
    assert "By size" in text and "small enough" in result["overall_text"]
    assert "By placement" in text and "outside" in text
    assert "too big" not in text.lower() and not any("scale to" in f.lower() for f in result["fixes"])
    assert result["basis"] == "size_and_placement" and result["placement_checked"] is True


def test_the_size_check_alone_claims_no_position(tmp_path):
    out = bed_fit.assess({"x": 10, "y": 10, "z": 10})
    assert out["basis"] == "size" and out["placement_checked"] is False
    assert out["overall_text"].startswith("By size")
    assert "not checked" in out["overall_text"]
    assert all(f["text"].startswith("By size") for f in out["findings"])


def test_a_small_object_inside_the_plate_is_ok_by_size_and_placement(tmp_path):
    path = project(tmp_path, [fx.cube_object("1", 10)], [("1", fx.tf(100, 100, 0))])
    result = service.bed_fit(path)
    assert result["overall_level"] == "ok"
    assert "By placement, every placed instance sits inside the plate" in texts(result)


# --- separated: meshes far apart in their own coordinates, objects close together on the plate ----------

def _separated(tmp_path):
    # Object 2's mesh is authored 500 mm from object 1's; its build item brings it back beside it.
    return project(tmp_path,
                   [box_object("1", 20, 20, 20), box_object("2", 20, 20, 20, origin=(500, 0, 0))],
                   [("1", fx.tf(50, 50, 0)), ("2", fx.tf(-400, 50, 0))])


def test_separated_meshes_are_not_one_big_object(tmp_path):
    path = _separated(tmp_path)
    info = project_info(path)
    assert info["dimensions_mm"]["x"] == 520.0                                  # the overall extents, as before
    assert [o["dimensions_mm"]["x"] for o in info["object_sizes_mm"]] == [20.0, 20.0]
    # the legacy overall figure would say "too big, scale to 52%"; the per-object check does not
    assert bed_fit.assess(info["dimensions_mm"])["overall_level"] == "risk"
    result = service.bed_fit(path)
    assert result["overall_level"] == "ok", texts(result)
    assert result["objects_checked"] == 2
    assert "too big" not in texts(result).lower() and result["fixes"] == []
    assert pp.assess(path)["off_plate"] == []


def test_separated_report_check_is_by_size_per_object(tmp_path):
    check = next(c for c in service.report(_separated(tmp_path))["checks"] if c["name"] == "Fits the print bed")
    assert check["status"] == "pass" and check["detail"].startswith("By size, object ")
    assert "20.0 × 20.0 × 20.0 mm" in check["detail"] and "largest object" in check["detail"]


def test_report_names_the_object_that_is_too_big_by_size(tmp_path):
    path = project(tmp_path, [box_object("1", 20, 20, 20), box_object("2", 300, 20, 20)],
                   [("1", fx.tf(10, 10, 0)), ("2", fx.tf(10, 100, 0))])
    check = next(c for c in service.report(path)["checks"] if c["name"] == "Fits the print bed")
    assert check["status"] == "warn"
    assert check["detail"].startswith("By size, object 2 300.0 × 20.0 × 20.0 mm is larger than the U1 bed")
    result = service.bed_fit(path)
    assert result["overall_level"] == "risk" and "By size, object 2 is too big" in texts(result)


def test_objects_far_apart_on_one_plate_are_a_placement_problem_not_a_size_problem(tmp_path):
    path = project(tmp_path, [fx.cube_object("1", 20), fx.cube_object("2", 20)],
                   [("1", fx.tf(10, 10, 0)), ("2", fx.tf(400, 10, 0))])
    result = service.bed_fit(path)
    assert result["overall_level"] == "risk"
    assert all(o["level"] == "ok" for o in result["objects_by_size"])           # each object is small enough
    assert "By placement" in texts(result) and "By size, object" not in " ".join(
        f["text"] for f in result["findings"] if f["level"] == "risk")


# --- multi-plate ------------------------------------------------------------------------------------------

def _two_plates(tmp_path, second_x=-130.0, second_size=20):
    settings = fx.model_settings_xml({"1": [("1", "normal_part")], "2": [("2", "normal_part")]},
                                     [(1, [("1", 0)]), (2, [("2", 0)])])
    # plate 2 sits 400 mm along the shared grid: its object's mesh is authored there
    return project(tmp_path,
                   [box_object("1", 20, 20, 20), box_object("2", second_size, 20, 20, origin=(400, 0, 0))],
                   [("1", fx.tf(50, 50, 0)), ("2", fx.tf(second_x, 50, 0))], settings=settings)


def test_a_multi_plate_project_has_no_combined_extent(tmp_path):
    path = _two_plates(tmp_path)
    placed = project_info(path)["placed"]
    assert placed["plate_count"] == 2 and placed["combined_extent_mm"] is None
    assert [(p["plate"], p["instances"]) for p in placed["plate_extents"]] == [(1, 1), (2, 1)]
    assert [i["plate"] for i in placed["instances"]] == [1, 2]


def test_multi_plate_extents_do_not_become_scale_or_split_advice(tmp_path):
    path = _two_plates(tmp_path)
    info = project_info(path)
    assert info["dimensions_mm"]["x"] > 400.0                                   # overall: 420 across both plates
    result = service.bed_fit(path)
    text = texts(result)
    assert result["overall_level"] == "ok", text
    assert "each of the 2 plates fits on its own" in text and "Positions across plates are not checked" in text
    assert "scale" not in text.lower() and result["fixes"] == []


def test_a_plate_whose_own_contents_do_not_fit_is_named(tmp_path):
    path = _two_plates(tmp_path, second_size=300)
    result = service.bed_fit(path)
    assert result["overall_level"] == "risk"
    assert any(f["text"].startswith("By placement, plate 2:") for f in result["findings"])
    assert any(f["text"].startswith("By size, object 2 is too big") for f in result["findings"])


def test_report_check_for_multi_plate_is_still_by_size_per_object(tmp_path):
    check = next(c for c in service.report(_two_plates(tmp_path))["checks"] if c["name"] == "Fits the print bed")
    assert check["status"] == "pass" and check["detail"].startswith("By size, object ")


# --- the legacy figure is still there for readers that only want a size ---------------------------------

def test_dimensions_mm_is_unchanged_for_a_single_object(tmp_path):
    path = project(tmp_path, [fx.cube_object("1", 30)], [("1", fx.tf(50, 60, 0))])
    assert project_info(path)["dimensions_mm"] == {"x": 30.0, "y": 30.0, "z": 30.0}


@pytest.mark.parametrize("dims", [None, {"x": None, "y": 1, "z": 1}])
def test_unmeasurable_size_stays_unavailable(dims):
    assert bed_fit.assess_objects([], fallback_dims=dims)["available"] is False
