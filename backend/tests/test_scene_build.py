"""scene/1 builder: units, ids, instances, transforms, volumes, plates, STL, bed, comparisons.

Every scene a test builds is also validated against the committed JSON Schema (real validator) and
the invariants JSON Schema cannot express.
"""
import json
import math
import os
from pathlib import Path

import pytest

from snapstudio_core import plate_placement, scene, units
from tests import scene_fixtures as fx
from tests.test_scene_contract import assert_valid

REV = "ab" * 32
EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def build(path) -> dict:
    sc = scene.build_scene_dict(str(path), REV)
    assert_valid(sc)
    return sc


def node(sc, nid):
    return next(n for n in sc["nodes"] if n["id"] == nid)


def codes(sc):
    return [l["code"] for l in sc["limitations"]]


# ------------------------------------------------------------------------------ units

@pytest.mark.parametrize("unit,factor", sorted(units.MM_PER_UNIT.items()))
def test_all_six_units_convert_to_millimetres(tmp_path, unit, factor):
    # a 12-unit cube, built 2 units along x. Both the vertex coordinates and the transform's
    # translation are in the model's unit.
    path = fx.three_mf(tmp_path / "u.3mf", fx.model_xml([fx.cube_object("1", 12)], [("1", fx.tf(2, 0, 0))], unit=unit))
    sc = build(path)
    assert sc["sources"] == [{"part": "3D/3dmodel.model", "unit": unit, "mm_per_unit": factor}]
    b = node(sc, "b0")["bounds_mm"]
    assert b["min"][0] == pytest.approx(2 * factor, abs=1e-5)
    assert b["max"][0] == pytest.approx(14 * factor, abs=1e-5)
    assert b["max"][2] == pytest.approx(12 * factor, abs=1e-5)
    assert node(sc, "b0")["world_mm"][12] == pytest.approx(2 * factor, rel=1e-8)
    if unit != "millimeter":
        assert "NON_MM_SOURCE_UNIT" in codes(sc) and sc["status"] == "partial"
        assert not [f for f in sc["findings"] if f["kind"] == "placement"]


def test_twelve_inch_part_is_304_8_mm(tmp_path):
    sc = build(fx.three_mf(tmp_path / "i.3mf", fx.model_xml([fx.cube_object("1", 12)], [("1", None)], unit="inch")))
    b = node(sc, "b0")["bounds_mm"]
    assert b["max"][0] - b["min"][0] == pytest.approx(304.8, abs=1e-4)
    assert any(f["kind"] == "size" for f in sc["findings"])          # larger than the 270 mm plate


def test_unrecognised_unit_is_a_limitation_not_a_silent_millimetre(tmp_path):
    # far off the plate: with an unknown unit no fit statement of any kind may be made
    path = fx.three_mf(tmp_path / "x.3mf", fx.model_xml([fx.cube_object("1", 400)], [("1", fx.tf(900, 900, 0))], unit="yard"))
    sc = build(path)
    assert "UNSUPPORTED_UNIT" in codes(sc) and sc["status"] == "partial"
    assert sc["findings"] == []
    assert sc["sources"] == [{"part": "3D/3dmodel.model", "unit": "millimeter", "mm_per_unit": 1.0}]   # the documented fallback
    absent = build(fx.three_mf(tmp_path / "y.3mf", fx.model_xml([fx.cube_object("1", 400)], [("1", fx.tf(900, 900, 0))]).replace(' unit="millimeter"', "")))
    assert "UNSUPPORTED_UNIT" not in codes(absent) and absent["findings"]     # absent = millimetre, judged normally


def test_sub_model_in_a_different_unit_uses_its_own_unit(tmp_path):
    sub = fx.sub_model_xml([fx.cube_object("1", 1)], unit="centimeter")
    root = fx.model_xml([fx.composite_object("10", [("1", "/3D/Objects/a.model", None)])], [("10", fx.tf(5, 0, 0))])
    sc = build(fx.three_mf(tmp_path / "m.3mf", root, {"3D/Objects/a.model": sub}))
    b = node(sc, "b0")["bounds_mm"]
    assert b["min"][0] == pytest.approx(5.0)            # root (mm) translation
    assert b["max"][0] == pytest.approx(15.0)           # 1 cm cube
    assert {s["unit"] for s in sc["sources"]} == {"millimeter", "centimeter"}


# ------------------------------------------------------------------------------ ids and instances

def test_cross_file_duplicate_object_ids_stay_distinct(tmp_path):
    a = fx.sub_model_xml([fx.cube_object("1", 10)])
    b = fx.sub_model_xml([fx.cube_object("1", 30)])
    root = fx.model_xml([fx.composite_object("9", [("1", "/3D/Objects/a.model", None),
                                                 ("1", "/3D/Objects/b.model", fx.tf(100, 0, 0))])], [("9", None)])
    sc = build(fx.three_mf(tmp_path / "d.3mf", root, {"3D/Objects/a.model": a, "3D/Objects/b.model": b}))
    keys = {(m["key"]["part"], m["key"]["object_id"]): m for m in sc["meshes"]}
    assert set(keys) == {("3D/Objects/a.model", "1"), ("3D/Objects/b.model", "1")}
    assert [n["id"] for n in sc["nodes"]] == ["b0", "b0.c0", "b0.c1"]
    assert node(sc, "b0.c0")["bounds_mm"]["max"][0] == 10.0
    assert node(sc, "b0.c1")["bounds_mm"]["min"][0] == 100.0 and node(sc, "b0.c1")["bounds_mm"]["max"][0] == 130.0
    assert node(sc, "b0")["bounds_mm"] == {"min": [0.0, 0.0, 0.0], "max": [130.0, 30.0, 30.0]}


def test_repeated_instances_share_a_mesh_and_disable_engine_findings(tmp_path):
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(100, 100, 0)), ("1", fx.tf(500, 100, 0))])
    sc = build(fx.three_mf(tmp_path / "r.3mf", root))
    assert len(sc["meshes"]) == 1 and [n["id"] for n in sc["nodes"]] == ["b0", "b1"]
    assert sc["counts"]["rendered_triangles"] == 24 and sc["counts"]["triangles"] == 12
    assert node(sc, "b0")["bounds_mm"]["min"][0] == 100.0
    assert node(sc, "b1")["bounds_mm"]["min"][0] == 500.0            # geometry stays available
    lim = next(l for l in sc["limitations"] if l["code"] == "REPEATED_INSTANCE_PLACEMENT_UNVERIFIED")
    assert lim["target_ids"] == ["b0", "b1"] and sc["status"] == "partial"
    assert sc["findings"] == [] and all(n["finding_ids"] == [] for n in sc["nodes"])
    # the same cube on its own IS judged: the second instance really is off the plate
    single = build(fx.three_mf(tmp_path / "s.3mf", fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(500, 100, 0))])))
    assert [f["kind"] for f in single["findings"]] == ["placement"]


def test_nested_and_mirrored_transforms_compose(tmp_path):
    inner = fx.composite_object("5", [("1", None, "-1 0 0 0 1 0 0 0 1 0 0 0")])        # mirror x
    mesh = fx.cube_object("1", 10)
    outer = fx.composite_object("6", [("5", None, fx.tf(30, 0, 0))])
    root = fx.model_xml([mesh, inner, outer], [("6", fx.tf(0, 50, 0))])
    sc = build(fx.three_mf(tmp_path / "n.3mf", root))
    assert [n["id"] for n in sc["nodes"]] == ["b0", "b0.c0", "b0.c0.c0"]
    leaf = node(sc, "b0.c0.c0")
    assert leaf["instance_ref"] == {"build_index": 0, "component_path": [0, 0]}
    assert leaf["mirrored"] is True and node(sc, "b0")["mirrored"] is False
    assert leaf["parent_id"] == "b0.c0"
    # mirror -> x in [-10, 0]; +30 -> [20, 30]; y +50
    assert leaf["bounds_mm"] == {"min": [20.0, 50.0, 0.0], "max": [30.0, 60.0, 10.0]}
    expected = scene.mat_mul(scene.mat_mul(scene.parse_transform(fx.tf(0, 50, 0), 1.0),
                                           scene.parse_transform(fx.tf(30, 0, 0), 1.0)),
                             scene.parse_transform("-1 0 0 0 1 0 0 0 1 0 0 0", 1.0))
    assert leaf["world_mm"] == pytest.approx(expected)


def test_rotated_instance_bounds_are_tight_not_box_corners(tmp_path):
    verts = [(0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 10)]
    tris = [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)]
    c = math.cos(math.pi / 4)
    lin = f"{c} {c} 0 {-c} {c} 0 0 0 1"                      # 45 degrees about z
    obj = f'<object id="1" type="model">{fx.mesh_xml(verts, tris)}</object>'
    sc = build(fx.three_mf(tmp_path / "rot.3mf", fx.model_xml([obj], [("1", fx.tf(0, 0, 0, lin))])))
    b = node(sc, "b0")["bounds_mm"]
    assert b["max"][1] == pytest.approx(10 * c, abs=1e-4)    # a box-corner estimate would give 14.14
    assert b["min"][0] == pytest.approx(-10 * c, abs=1e-4) and b["max"][0] == pytest.approx(10 * c, abs=1e-4)


# ------------------------------------------------------------------------------ roles and volumes

def test_bambu_roles_and_non_part_volumes_do_not_count_for_bounds(tmp_path):
    path = fx.bambu_project(tmp_path / "b.3mf", parts=3, items=[("100", fx.tf(10, 10, 0))], plates=[(1, [("100", 0)])],
                            roles=["normal_part", "modifier_part", "negative_part"],
                            origins=[(0, 0, 0), (500, 0, 0), (900, 0, 0)])
    sc = build(path)
    roles = {n["resource"]["object_id"]: n["role_context"] for n in sc["nodes"] if n["mesh_key"]}
    assert roles == {"1": "part", "2": "modifier", "3": "negative"}     # roles follow the USE (node), not the mesh
    assert node(sc, "b0.c0")["printable"] is True
    top = node(sc, "b0")
    assert top["has_non_part_volumes"] is True and top["printable"] is True
    assert top["bounds_mm"] == {"min": [10.0, 10.0, 0.0], "max": [20.0, 20.0, 10.0]}       # the modifier at x=500 is ignored
    assert node(sc, "b0.c1")["printable"] is False and node(sc, "b0.c1")["bounds_mm"] is None
    assert sc["findings"] == []                                                        # fits: modifiers are excluded from fit


def test_prusa_ranges_partition_all_triangles(tmp_path):
    path = fx.prusa_project(tmp_path / "p.3mf", volumes=[(0, 11, "ModelPart"), (12, 23, "ParameterModifier")])
    sc = build(path)
    vols = sc["meshes"][0]["volumes"]
    assert [(v["triangle_start"], v["triangle_count"], v["role"], v["source"]) for v in vols] == [
        (0, 12, "part", "prusa_range"), (12, 12, "modifier", "prusa_range")]
    assert node(sc, "b0")["has_non_part_volumes"] is True
    assert node(sc, "b0")["bounds_mm"]["max"][0] == pytest.approx(100 + 10)        # only the first cube counts


def test_prusa_gap_and_overlap_never_guess(tmp_path):
    gap = build(fx.prusa_project(tmp_path / "g.3mf", volumes=[(0, 5, "ModelPart"), (12, 23, "ModelPart")]))
    assert [v["role"] for v in gap["meshes"][0]["volumes"]] == ["part", "unknown", "part"]
    assert "UNKNOWN_VOLUME_ROLE" in codes(gap) and gap["status"] == "partial"
    overlap = build(fx.prusa_project(tmp_path / "o.3mf", volumes=[(0, 12, "ModelPart"), (10, 23, "ModelPart")]))
    assert [v["role"] for v in overlap["meshes"][0]["volumes"]] == ["unknown"]
    assert node(overlap, "b0")["printable"] is None and overlap["findings"] == []


def test_unrecognised_bambu_subtype_is_unknown_not_a_part(tmp_path):
    sc = build(fx.bambu_project(tmp_path / "u.3mf", parts=1, items=[("100", fx.tf(10, 10, 0))], plates=[(1, [("100", 0)])],
                                roles=["totally_new_part"]))
    assert node(sc, "b0.c0")["role_context"] == "unknown"
    lim = next(l for l in sc["limitations"] if l["code"] == "UNKNOWN_VOLUME_ROLE")
    assert lim["target_ids"] == ["b0.c0"] and node(sc, "b0")["printable"] is None


def test_plain_mesh_gets_one_synthetic_part_volume(tmp_path):
    sc = build(fx.plain_cube_3mf(tmp_path / "c.3mf"))
    assert sc["meshes"][0]["volumes"] == [
        {"id": "v0", "triangle_start": 0, "triangle_count": 12, "role": "part", "source": "object"}]


# ------------------------------------------------------------------------------ plates

def test_two_instances_of_one_resource_on_different_plates(tmp_path):
    path = fx.bambu_project(tmp_path / "pl.3mf", parts=1, items=[("100", fx.tf(10, 10, 0)), ("100", fx.tf(20, 10, 0))],
                            plates=[(1, [("100", 0)]), (2, [("100", 1)])])
    sc = build(path)
    assert node(sc, "b0")["plate"] == {"state": "known", "plate_id": "p1", "source": "plate_config"}
    assert node(sc, "b1")["plate"] == {"state": "known", "plate_id": "p2", "source": "plate_config"}
    assert [p["id"] for p in sc["plates"]] == ["p1", "p2"] and all(p["origin_mm"] is None for p in sc["plates"])
    assert "MULTI_PLATE_PLACEMENT_UNCHECKED" in codes(sc)
    assert sc["findings"] == []


def test_membership_ambiguity_is_reported_not_guessed(tmp_path):
    both = build(fx.bambu_project(tmp_path / "a.3mf", parts=1, items=[("100", fx.tf(10, 10, 0))],
                                  plates=[(1, [("100", 0)]), (2, [("100", 0)])]))
    assert node(both, "b0")["plate"]["state"] == "ambiguous" and node(both, "b0")["plate"]["plate_id"] is None
    assert "PLATE_MEMBERSHIP_AMBIGUOUS" in codes(both)
    unspecific = build(fx.bambu_project(tmp_path / "b.3mf", parts=1, items=[("100", fx.tf(10, 10, 0)), ("100", fx.tf(40, 10, 0))],
                                        plates=[(1, [("100", None)])]))
    assert [node(unspecific, i)["plate"]["state"] for i in ("b0", "b1")] == ["ambiguous", "ambiguous"]
    absent = build(fx.bambu_project(tmp_path / "c.3mf", parts=1, items=[("100", fx.tf(10, 10, 0))], plates=[(1, [])]))
    assert node(absent, "b0")["plate"]["state"] == "unknown"


# ------------------------------------------------------------------------------ STL and no placement

def test_stl_placement_is_unknown_and_never_judged(tmp_path):
    path = fx.binary_stl(tmp_path / "huge.stl", size=900.0)
    sc = build(path)
    n = node(sc, "b0")
    assert n["placement_state"] == "unknown" and n["plate"]["state"] == "unknown" and n["build_index"] is None
    assert n["world_mm"] == scene.IDENTITY16                  # an identity is a rendering default only
    assert sc["findings"] == [] and "UNKNOWN_PLACEMENT" in codes(sc) and sc["status"] == "partial"
    assert sc["sources"] == [{"part": "model.stl", "unit": "millimeter", "mm_per_unit": 1.0}]
    assert sc["meshes"][0]["volumes"][0]["role"] == "part"


def test_model_without_build_items_has_unknown_placement(tmp_path):
    root = fx.model_xml([fx.cube_object("1", 10)], [])
    sc = build(fx.three_mf(tmp_path / "nb.3mf", root))
    assert node(sc, "b0")["placement_state"] == "unknown" and node(sc, "b0")["build_index"] is None
    assert {"NO_BUILD_ITEMS", "UNKNOWN_PLACEMENT"} <= set(codes(sc)) and sc["findings"] == []


# ------------------------------------------------------------------------------ bed

@pytest.mark.parametrize("breaker", ["empty", "raises"])
def test_bed_template_problem_is_surfaced_and_suppresses_fit_findings(tmp_path, monkeypatch, breaker):
    def broken():
        if breaker == "raises":
            raise FileNotFoundError("template")
        return []
    monkeypatch.setattr(plate_placement, "_u1_printable_area", broken)
    sc = build(fx.three_mf(tmp_path / "f.3mf", fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(900, 900, 0))])))
    assert sc["bed"]["policy"] == "fallback" and "BED_TEMPLATE_UNAVAILABLE" in codes(sc)
    assert sc["findings"] == [] and sc["status"] == "partial"


def test_bed_matches_the_engines_u1_rectangle():
    lims = scene._Limitations()
    bed, rect = scene._bed([])
    assert bed["policy"] == "u1_template" and rect == plate_placement.u1_bed_rect()
    assert bed["polygon_mm"] == [[0.5, 1.0], [270.5, 1.0], [270.5, 271.0], [0.5, 271.0]]
    assert bed["edge_margin_mm"] == plate_placement.EDGE_MARGIN_MM


# ------------------------------------------------------------------------------ scene vs the engine

def _single_plate_cases(tmp_path):
    cases = {}
    for name, at in {"inside": (50, 60, 0), "past_right": (300, 60, 0), "edge_margin": (270.2, 60, 0),
                     "past_front": (50, -5, 0)}.items():
        cases[name] = fx.bambu_project(tmp_path / f"{name}.3mf", parts=1, items=[("100", fx.tf(*at))], plates=[(1, [("100", 0)])])
    cases["example_offplate"] = EXAMPLES / "demo_offplate_foreign.3mf"
    cases["example_cube"] = EXAMPLES / "sample_cube_SnapmakerU1.3mf"
    return cases


def test_scene_world_bounds_and_findings_agree_with_plate_placement_assess(tmp_path):
    from snapstudio_core import geometry
    for name, path in _single_plate_cases(tmp_path).items():
        sc = build(path)
        assessed = plate_placement.assess(str(path))
        assert assessed["available"], name
        dims = geometry.build_item_dims(str(path))
        assert len(dims) == 1
        top = node(sc, "b0")
        assert top["bounds_mm"]["min"] == pytest.approx(list(dims[0]["bounds"]["min"]), abs=1e-4), name
        assert top["bounds_mm"]["max"] == pytest.approx(list(dims[0]["bounds"]["max"]), abs=1e-4), name
        scene_off = any(f["kind"] == "placement" for f in sc["findings"])
        assert scene_off == bool(assessed["off_plate"]), name
        if scene_off:
            f = next(f for f in sc["findings"] if f["kind"] == "placement")
            assert f["value"]["overhang_mm"] == assessed["items"][0]["overhang_mm"], name


def test_repeated_instance_fixture_documents_why_no_finding_is_attached(tmp_path):
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(500, 100, 0)), ("1", fx.tf(100, 100, 0))])
    path = fx.three_mf(tmp_path / "rep.3mf", root)
    sc = build(path)
    assert "REPEATED_INSTANCE_PLACEMENT_UNVERIFIED" in codes(sc)
    assert sc["findings"] == [] and not any(n["finding_ids"] for n in sc["nodes"])


# ------------------------------------------------------------------------------ originals are never touched

@pytest.mark.parametrize("make", ["3mf", "stl", "example"])
def test_original_file_is_not_modified(tmp_path, make):
    path = {"3mf": lambda: fx.bambu_project(tmp_path / "o.3mf", parts=2, items=[("100", fx.tf(10, 10, 0))], plates=[(1, [("100", 0)])]),
            "stl": lambda: fx.binary_stl(tmp_path / "o.stl"),
            "example": lambda: tmp_path.joinpath("e.3mf").write_bytes((EXAMPLES / "demo_offplate_foreign.3mf").read_bytes()) and tmp_path / "e.3mf"}[make]()
    before = (Path(path).read_bytes(), os.stat(path).st_mtime_ns)
    os.utime(path, ns=(before[1] - 10**9, before[1] - 10**9))        # make a rewrite visible even on coarse clocks
    before = (Path(path).read_bytes(), os.stat(path).st_mtime_ns)
    scene.build_scene(str(path))
    assert (Path(path).read_bytes(), os.stat(path).st_mtime_ns) == before
