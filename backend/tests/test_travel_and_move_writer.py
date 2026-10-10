"""Review round 3: travel extents are not a printable area; malformed p:path fails closed; the move writer
leaves every token but the X/Y translation alone."""
from __future__ import annotations

import zipfile

from snapstudio_api import service
from snapstudio_core import geometry, placement, plate_placement as pp
from tests import scene_fixtures as fx

A = "3D/Objects/a.model"


def _facts(identity):
    return lambda host=None, port=7125: {
        "reachable": True, "host": "h", "port": 7125, "toolhead_count": 4, "klipper_objects": [],
        "bed_mm": {"x": 271, "y": 335, "z": 275}, "print_state": "standby", "identity": identity}


def _y300(tmp_path):
    return str(fx.three_mf(tmp_path / "y.3mf", fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(100, 300, 0))])))


def test_a_u1_is_judged_against_its_printable_area_not_its_travel(tmp_path, monkeypatch):
    seen = {}
    real = pp.assess

    def spy(path, bed=None, bed_name=None, height_mm=None):
        seen["bed"] = bed
        return real(path, bed=bed, bed_name=bed_name, height_mm=height_mm)

    monkeypatch.setattr(pp, "assess", spy)
    monkeypatch.setattr(service, "printer_facts", _facts({"printer_id": "snapmaker_u1"}))
    out = service.preflight(_y300(tmp_path), "h")
    assert seen["bed"] is None                                      # the profile polygon, not 271 x 335
    check = next(c for c in out["checks"] if c["id"] == "bed.fit")
    assert check["result"] == "attention" and "335" not in check["evidence"]


def test_a_printer_that_cannot_be_identified_has_an_unknown_printable_area(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "printer_facts", _facts({"printer_id": None}))
    out = service.preflight(_y300(tmp_path), "h")
    check = next(c for c in out["checks"] if c["id"] == "bed.fit")
    assert check["result"] == "unknown" and check["confidence"] != "confirmed"
    assert "printable area" in check["evidence"]


def test_a_malformed_part_path_is_unresolved_never_the_root_object(tmp_path):
    for bad in ("", "3D/Objects/a.model", "/../x.model", "http://x/a.model"):
        root = fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(100, 100, 0)), ("1", fx.tf(100, 100, 0), bad)])
        path = str(fx.three_mf(tmp_path / "bad.3mf", root))
        items, unresolved = geometry.measure_items(path)
        assert [i["item_index"] for i in items] == [0], bad
        assert [u["item_index"] for u in unresolved] == [1], bad


def test_a_malformed_component_path_is_unresolved(tmp_path):
    for bad in ("", "3D/Objects/a.model"):
        comp = fx.composite_object("5", [("1", bad, None)])
        extra = {A: fx.sub_model_xml([fx.cube_object("1", 10)])}
        path = str(fx.three_mf(tmp_path / "c.3mf", fx.model_xml([fx.cube_object("1", 10), comp], [("5", fx.tf(10, 10, 0))]), extra))
        assert [u["item_index"] for u in geometry.measure_items(path)[1]] == [0], bad
        assert placement.read_objects(path)["objects"][0]["resolved"] is False, bad


def test_the_move_writer_keeps_every_other_token_verbatim():
    out = pp._shift_transform("0.7071067812 0.7071067812 0 -0.7071067812 0.7071067812 0 0 0 1 100.123456789 200 5", 6, 0)
    tokens = out.split()
    assert tokens[:9] == ["0.7071067812", "0.7071067812", "0", "-0.7071067812", "0.7071067812", "0", "0", "0", "1"]
    assert tokens[9] == "106.123457" and tokens[10] == "200" and tokens[11] == "5"


def test_a_rotated_project_is_moved_and_verified(tmp_path):
    rot = "0.7071067812 0.7071067812 0 -0.7071067812 0.7071067812 0 0 0 1"
    src = fx.three_mf(tmp_path / "rot.3mf", fx.model_xml(
        [fx.cube_object("1", 10)], [("1", f"{rot} -5 100 0"), ("1", f"{rot} 100 100 0")]))
    result = pp.prepare_placed_copy(str(src), out_dir=str(tmp_path / "out"))
    assert result["ok"] is True, result.get("reason")
    assert result["verification"]["passed"] is True
    with zipfile.ZipFile(result["output_path"]) as z:
        assert z.read("3D/3dmodel.model").decode().count(rot) == 2


def test_a_tall_object_is_not_confirmed_by_preflight_even_when_it_is_on_the_plate(tmp_path, monkeypatch):
    path = str(fx.three_mf(tmp_path / "tall.3mf", fx.model_xml(
        [fx.cube_object("1", 10).replace('z="10.0"', 'z="300.0"')], [("1", fx.tf(100, 100, 0))])))
    monkeypatch.setattr(service, "printer_facts", _facts({"printer_id": "snapmaker_u1"}))
    check = next(c for c in service.preflight(path, "h")["checks"] if c["id"] == "bed.fit")
    assert check["result"] == "attention" and "height limit" in check["evidence"]
    assert check["confidence"] == "confirmed" and "300" in check["evidence"]
