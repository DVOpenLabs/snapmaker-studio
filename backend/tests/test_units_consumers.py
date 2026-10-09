"""The 3MF `unit` header, applied once (snapstudio_core.units) and checked at every consumer.

Before this fix several readers ignored the header, so a 12 inch part was reported as 12 mm and bed-fit
statements were wrong for any non-millimetre project. A part that is 12 inches must read 304.8 mm
EVERYWHERE; millimetre projects must read exactly as they always did.
"""
import pytest

from snapstudio_core import units
from tests import scene_fixtures as fx

UNITS = sorted(units.MM_PER_UNIT.items())


def project(tmp_path, unit, size_mm=30.0, at_units=(0.0, 0.0, 0.0), name="u.3mf"):
    """A cube whose true edge is `size_mm`, written in `unit`, placed `at_units` (in that unit)."""
    f = units.MM_PER_UNIT[unit]
    return str(fx.three_mf(tmp_path / name, fx.model_xml([fx.cube_object("1", size_mm / f)], [("1", fx.tf(*at_units))], unit=unit)))


def composite(tmp_path, unit, size_units, at_units, name="c.3mf"):
    """The Bambu/Orca shape (one composite object over a mesh in 3D/Objects/): the only shape
    placement.read_objects reads."""
    return str(fx.bambu_project(tmp_path / name, parts=1, items=[("100", fx.tf(*at_units))], plates=[(1, [("100", 0)])],
                                unit=unit, sizes=[size_units], origins=[(0.0, 0.0, 0.0)]))


def twelve_inch(tmp_path, at=(0.0, 0.0, 0.0)):
    return str(fx.three_mf(tmp_path / "in.3mf", fx.model_xml([fx.cube_object("1", 12)], [("1", fx.tf(*at))], unit="inch")))


# ------------------------------------------------------------------ the shared table

def test_table_has_the_six_units_and_reads_the_header():
    assert units.MM_PER_UNIT == {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4,
                                 "foot": 304.8, "meter": 1000.0}
    assert units.unit_of(b'<?xml version="1.0"?><model unit="inch" xmlns="x">') == ("inch", 25.4)
    assert units.unit_of(b"<model xmlns='x' unit='foot'/>") == ("foot", 304.8)
    assert units.unit_of(b"<model xmlns='x'/>") == ("millimeter", 1.0)          # absent attribute = default
    assert units.unit_of(b'<model unit="yard">') == ("yard", None)               # unknown is surfaced, not guessed
    assert units.mm_per_unit(b'<model unit="yard">') == 1.0                      # legacy readers keep treating it as mm
    info = units.read_unit(b'<model_settings unit="inch">')                       # not a <model> element
    assert (info.recognized, info.declared, info.factor) == (False, False, 1.0)   # unreadable is not "absent"
    assert units.read_unit(b"this is not xml").recognized is False
    assert units.read_unit(b"").recognized is False and units.read_unit(b"<model/>").recognized is True
    assert units.scale_translation([1, 0, 0, 0, 1, 0, 0, 0, 1, 2, 3, 4], 25.4)[9:] == [2 * 25.4, 3 * 25.4, 4 * 25.4]
    same = [1, 0, 0, 0, 1, 0, 0, 0, 1, 2, 3, 4]
    assert units.scale_translation(same, 1.0) is same


# ------------------------------------------------------------------ every dimension source

@pytest.mark.parametrize("unit,factor", UNITS)
def test_project_info_and_its_service_wrappers(tmp_path, unit, factor):
    from snapstudio_api import service
    from snapstudio_core.intelligence import project_info
    path = project(tmp_path, unit)
    want = {"x": 30.0, "y": 30.0, "z": 30.0}
    assert project_info(path)["dimensions_mm"] == want
    assert service.insights(path)["dimensions_mm"] == want                       # DesignHealth data path
    assert service.strategy_recommend(path)["signals"]["dimensions_mm"] == want  # strategy signals (~490/522/541)


@pytest.mark.parametrize("unit,factor", UNITS)
def test_canonical_and_layout_and_validation_report(tmp_path, unit, factor):
    from snapstudio_api import service
    from snapstudio_core import layout
    path = project(tmp_path, unit)
    assert service.canonical(path)["dimensions_mm"] == {"x": 30.0, "y": 30.0, "z": 30.0}      # canonical.py:92
    rep = service.report(path)                                                                  # validation_report.py:35
    fits = next(c for c in rep["checks"] if c["name"] == "Fits the print bed")
    assert fits["status"] == "pass" and "30.0 × 30.0 × 30.0 mm" in fits["detail"]
    lay = layout.assess_layout(path)                                                            # layout.py:55
    assert lay["status"] == "pass", lay


def test_twelve_inch_part_reads_304_8_mm_everywhere(tmp_path):
    from snapstudio_api import service
    from snapstudio_core import geometry, layout, plate_placement, placement, scale_doctor
    from snapstudio_core.intelligence import project_info
    path = twelve_inch(tmp_path)
    full = {"x": 304.8, "y": 304.8, "z": 304.8}
    assert project_info(path)["dimensions_mm"] == full
    assert service.insights(path)["dimensions_mm"] == full
    assert service.canonical(path)["dimensions_mm"] == full
    assert service.strategy_recommend(path)["signals"]["dimensions_mm"] == full
    # bed_fit (via its service caller): the model does NOT fit a 270 mm plate
    bf = service.bed_fit(path)
    assert bf["dims_mm"] == full and bf["overall_level"] == "risk"
    assert any("305" in f["text"] for f in bf["findings"])
    # validation report
    fits = next(c for c in service.report(path)["checks"] if c["name"] == "Fits the print bed")
    assert fits["status"] == "warn" and "304.8" in fits["detail"]
    # layout
    assert layout.assess_layout(path)["status"] == "fail"
    # geometry
    item = geometry.build_item_dims(path)[0]
    assert item["dimensions"] == {"x": 304.8, "y": 304.8, "z": 304.8}
    mesh = geometry.load_mesh(path)
    assert max(v[0] for v in mesh.verts) == pytest.approx(304.8)
    # placement
    obj = placement.read_objects(composite(tmp_path, "inch", 12, (0, 0, 0)))["objects"][0]
    assert obj["footprint"]["width"] == pytest.approx(304.8)
    assessed = plate_placement.assess(path)
    assert assessed["items"][0]["dimensions"] == full and assessed["off_plate"]
    # scale doctor
    opts = scale_doctor.scale_options(path)
    assert opts["current_parts"][0]["dimensions"] == full
    prev = scale_doctor.preview(path, 100)
    assert prev["original_dimensions"] == full and prev["fits_build_volume"] is False


@pytest.mark.parametrize("unit,factor", UNITS)
def test_build_item_translation_is_in_the_models_unit(tmp_path, unit, factor):
    """A transform's translation is a length in the model's unit too (an inch offset is not 1 mm)."""
    from snapstudio_core import geometry, placement
    path = project(tmp_path, unit, size_mm=20.0, at_units=(10.0 / factor, 20.0 / factor, 0.0))
    item = geometry.build_item_dims(path)[0]
    assert item["bounds"]["min"][0] == pytest.approx(10.0, abs=1e-6)
    assert item["bounds"]["max"][1] == pytest.approx(40.0, abs=1e-6)
    comp = composite(tmp_path, unit, 20.0 / factor, (10.0 / factor, 20.0 / factor, 0.0), name="comp.3mf")
    fp = placement.read_objects(comp)["objects"][0]["footprint"]
    assert (fp["min_x"], fp["max_y"]) == (pytest.approx(10.0, abs=1e-6), pytest.approx(40.0, abs=1e-6))


def test_plate_placement_judges_an_inch_project_in_millimetres(tmp_path):
    """3 inches in is 76.2 mm in: on the plate. 12 inches in is 304.8 mm in: off it."""
    from snapstudio_core import plate_placement
    inside = project(tmp_path, "inch", size_mm=25.4, at_units=(3.0, 3.0, 0.0), name="a.3mf")
    r = plate_placement.assess(inside)
    assert not r["off_plate"] and r["items"][0]["position"] == {"x": 88.9, "y": 88.9}
    outside = project(tmp_path, "inch", size_mm=25.4, at_units=(12.0, 3.0, 0.0), name="b.3mf")
    assert plate_placement.assess(outside)["off_plate"]


def test_sub_model_units_are_per_part(tmp_path):
    from snapstudio_core import geometry, placement
    from snapstudio_core.intelligence import project_info
    sub = fx.sub_model_xml([fx.cube_object("1", 2)], unit="centimeter")        # a 20 mm cube
    root = fx.model_xml([fx.composite_object("10", [("1", "/3D/Objects/a.model", None)])], [("10", fx.tf(5, 0, 0))])
    path = str(fx.three_mf(tmp_path / "m.3mf", root, {"3D/Objects/a.model": sub}))
    assert project_info(path)["dimensions_mm"] == {"x": 20.0, "y": 20.0, "z": 20.0}
    item = geometry.build_item_dims(path)[0]
    assert item["bounds"]["min"][0] == pytest.approx(5.0) and item["bounds"]["max"][0] == pytest.approx(25.0)
    assert placement.read_objects(path)["objects"][0]["footprint"]["width"] == pytest.approx(20.0)


# ------------------------------------------------------------------ millimetre behaviour is unchanged

def test_millimetre_projects_read_exactly_as_before(tmp_path):
    from snapstudio_core import geometry, placement
    from snapstudio_core.intelligence import project_info
    path = str(fx.three_mf(tmp_path / "mm.3mf", fx.model_xml([fx.cube_object("1", 12.3456)], [("1", fx.tf(1.25, 2.5, 0))])))
    assert project_info(path)["dimensions_mm"] == {"x": 12.3, "y": 12.3, "z": 12.3}
    item = geometry.build_item_dims(path)[0]
    assert item["bounds"] == {"min": (1.25, 2.5, 0.0), "max": (1.25 + 12.3456, 2.5 + 12.3456, 12.3456)}
    fp = placement.read_objects(composite(tmp_path, "millimeter", 12.3456, (1.25, 2.5, 0)))["objects"][0]["footprint"]
    assert (fp["min_x"], fp["min_y"]) == (1.25, 2.5)
    # no unit attribute at all is millimetre
    bare = fx.model_xml([fx.cube_object("1", 7)], [("1", None)]).replace(' unit="millimeter"', "")
    assert project_info(str(fx.three_mf(tmp_path / "bare.3mf", bare)))["dimensions_mm"] == {"x": 7.0, "y": 7.0, "z": 7.0}


# ------------------------------------------------------------------ repair round 1: A3 / D1 / A15

def _root_translation(copy_path):
    import re
    import zipfile
    with zipfile.ZipFile(copy_path) as z:
        text = z.read("3D/3dmodel.model").decode()
    return [float(x) for x in re.search(r"<item[^>]*transform=\"([^\"]*)\"", text).group(1).split()]


def test_d1_the_placement_fix_moves_an_inch_model_by_the_right_amount(tmp_path):
    from snapstudio_core import plate_placement
    path = project(tmp_path, "inch", size_mm=25.4, at_units=(11.0, 3.0, 0.0))
    assert plate_placement.assess(path)["off_plate"]                      # 11 in + 1 in = 304.8 mm: off the 270 mm plate
    res = plate_placement.prepare_placed_copy(path, out_dir=str(tmp_path / "out"))
    assert res["ok"] is True, res.get("reason")
    tx, ty, tz = _root_translation(res["output_path"])[9:12]
    dx, dy = res["offset_mm"]["x"], res["offset_mm"]["y"]
    assert tx == pytest.approx(11 + dx / 25.4, abs=1e-3) and ty == pytest.approx(3 + dy / 25.4, abs=1e-3) and tz == 0
    assert res["after"]["available"] and not res["after"]["off_plate"]    # and it really lands on the plate
    assert plate_placement.assess(res["output_path"])["off_plate"] == []


def test_d1_a_move_that_did_not_work_leaves_no_copy_on_disk(tmp_path, monkeypatch):
    from snapstudio_core import plate_placement
    path = project(tmp_path, "inch", size_mm=25.4, at_units=(11.0, 3.0, 0.0))
    monkeypatch.setattr(plate_placement, "_rewrite_items", lambda raw, offset_for: (raw, 1))   # a move that moves nothing
    monkeypatch.setattr(plate_placement, "verify_only_placement_moved", lambda a, b: {"passed": True, "checks": []})
    out = tmp_path / "out"
    res = plate_placement.prepare_placed_copy(path, out_dir=str(out))
    assert res["ok"] is False and "output_path" not in res
    assert not list(out.glob("*.3mf"))


def test_d1_millimetre_models_get_exactly_the_offset_they_always_got(tmp_path):
    from snapstudio_core import plate_placement
    path = str(fx.three_mf(tmp_path / "mm.3mf", fx.model_xml([fx.cube_object("1", 25.4)], [("1", fx.tf(290.0, 3.0, 0.0))])))
    res = plate_placement.prepare_placed_copy(path, out_dir=str(tmp_path / "out"))
    assert res["ok"] is True
    tx, ty, _ = _root_translation(res["output_path"])[9:12]
    assert tx == pytest.approx(290.0 + res["offset_mm"]["x"], abs=1e-4)


def test_a15_placement_uses_the_shared_translation_scaler():
    from snapstudio_core import placement
    assert not hasattr(placement, "_scale_translation")
    rows = ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1.0, 2.0, 3.0))
    assert units.scale_translation(rows, 25.4)[3] == pytest.approx((25.4, 50.8, 76.2))
    assert units.scale_translation(rows, 1.0) is rows
    assert units.scale_translation(None, 25.4) is None
