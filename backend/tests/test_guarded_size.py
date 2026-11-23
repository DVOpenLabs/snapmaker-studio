"""Issue 91: a guarded, exact size basis for rotated, scaled and non-millimetre projects.

Before: any rotation, scale, shear or declared unit other than millimetres made bed fit say "not checked".
Now bed fit builds its verdict on millimetres that were MEASURED: each part converted from its own 3MF
unit, every transform applied to the real vertices. Anything Studio cannot follow, or any unit outside the
six the format defines, stays "not checked". Every other size-dependent surface is unchanged.
"""
from __future__ import annotations

import pytest

from snapstudio_api import service
from snapstudio_core import geometry, geometry_basis
from snapstudio_core.intelligence import project_info
from tests import scene_fixtures as fx
from tests.test_geometry_verdict import (_IDENT, _ROT_X90, _ROT_Z90, _SCALE20, _mesh_xml, _model, _write, make)
from tests.test_size_vs_placed_bounds import project

_TF_Z90_AT_100 = "0 1 0 -1 0 0 0 0 1 100 100 0"      # 90 degrees about Z, then to (100, 100)


def _ids(result):
    return {f.get("id") for f in result["findings"]}


# --- units -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("unit,dims", [("inch", (254.0, 508.0, 762.0)), ("centimeter", (100.0, 200.0, 300.0)),
                                       ("micron", (0.01, 0.02, 0.03)), ("meter", (10000.0, 20000.0, 30000.0)),
                                       ("foot", (3048.0, 6096.0, 9144.0))])
def test_every_unit_the_format_defines_is_converted_to_millimetres(tmp_path, unit, dims):
    p = make(tmp_path, unit, unit=unit)
    assert geometry.object_sizes(p)[0]["dimensions"]["x"] == 10.0     # default: as written, for every other caller
    [size] = geometry.object_sizes(p, mm=True)
    assert (size["dimensions"]["x"], size["dimensions"]["y"], size["dimensions"]["z"]) == dims
    basis = geometry_basis.assess(p)
    assert basis["established"] is False and basis["extents"]["measurable"] is True
    assert basis["extents"]["converted_units"] == [unit]


def test_a_converted_project_gets_a_real_verdict_and_says_how_it_was_measured(tmp_path):
    fit = service.bed_fit(make(tmp_path, "inch", unit="inch"))      # 254 x 508 x 762 mm
    assert fit["available"] is True and fit["size_basis"] == "measured_mm" and fit["overall_level"] == "risk"
    assert fit["objects_by_size"][0]["dims_mm"] == {"x": 254.0, "y": 508.0, "z": 762.0}
    assert any("converted it to millimetres" in f["text"] for f in fit["findings"])
    tiny = service.bed_fit(make(tmp_path, "micron", unit="micron"))   # 0.01 mm: it fits
    assert tiny["available"] is True and tiny["objects_by_size"][0]["level"] == "ok"


def test_an_unrecognised_unit_is_never_guessed(tmp_path):
    p = make(tmp_path, "parsec", unit="parsec")
    basis = geometry_basis.assess(p)
    assert basis["extents"]["measurable"] is False and basis["extents"]["blocked_by"] == ["unit_unrecognized"]
    fit = service.bed_fit(p)
    assert fit["available"] is False and fit["status"] == "not_checked"


def test_each_part_uses_its_own_unit_and_a_translation_uses_the_unit_of_the_part_that_holds_it(tmp_path):
    """Root in millimetres, the object in a sub-part in centimetres: the vertices are 10 x 20 x 30 cm, the
    item's translation is in the ROOT's millimetres."""
    sub = {"3D/Objects/object_1.model": _model(_mesh_xml(1), "", "centimeter")}
    root = ('<object id="2" type="model"><components>'
            '<component p:path="/3D/Objects/object_1.model" objectid="1"/></components></object>')
    parts = {"3D/3dmodel.model": _model(root, '<item objectid="2" transform="1 0 0 0 1 0 0 0 1 100 50 0"/>',
                                        "millimeter")}
    parts.update(sub)
    p = _write(tmp_path / "mixed_units.3mf", parts)
    [item] = geometry.measure_items(p, mm=True)[0]
    assert item["bounds"]["min"] == (100.0, 50.0, 0.0) and item["bounds"]["max"] == (200.0, 250.0, 300.0)


def test_a_root_in_centimetres_reads_its_own_translation_as_centimetres(tmp_path):
    p = make(tmp_path, "cm", unit="centimeter", items=(("1", "1 0 0 0 1 0 0 0 1 10 5 0"),))
    [item] = geometry.measure_items(p, mm=True)[0]
    assert item["bounds"]["min"] == (100.0, 50.0, 0.0) and item["bounds"]["max"] == (200.0, 250.0, 300.0)


def test_millimetre_projects_are_measured_exactly_as_before(tmp_path):
    p = make(tmp_path, "mm", items=(("1", "1 0 0 0 1 0 0 0 1 100 50 0"),))
    [item] = geometry.measure_items(p)[0]
    assert item["bounds"]["min"] == (100.0, 50.0, 0.0) and item["bounds"]["max"] == (110.0, 70.0, 30.0)
    assert geometry_basis.assess(p)["established"] is True


# --- rotation, scale, shear ---------------------------------------------------------------------------------

def test_a_rotated_item_is_judged_by_its_extents_after_the_rotation(tmp_path):
    p = make(tmp_path, "rot", items=(("1", _TF_Z90_AT_100),))
    [inst] = project_info(p, placement_aware=True, convert_units=True)["placed"]["instances"]
    assert inst["dimensions_mm"] == {"x": 20.0, "y": 10.0, "z": 30.0}      # x and y swapped, not 10 x 20
    ext = geometry_basis.assess(p)["extents"]
    assert ext["measurable"] is True and ext["size_exact"] is False and ext["items_rotated"] and not ext["items_scaled"]
    fit = service.bed_fit(p)
    assert fit["available"] is True and fit["size_basis"] == "as_placed"      # a rotated item is sized as placed too
    assert fit["objects_by_size"][0]["dims_mm"] == {"x": 20.0, "y": 10.0, "z": 30.0}
    assert any("rotated" in f["text"] for f in fit["findings"])


def test_a_rotated_item_that_leaves_the_plate_is_reported_by_placement_and_no_fix_is_promised(tmp_path):
    # 90 degrees about X puts the box at y = 10 - z: it reaches 20 mm in front of the plate
    p = make(tmp_path, "rot_off", items=(("1", "1 0 0 0 0 1 0 -1 0 100 10 0"),))
    fit = service.bed_fit(p)
    assert "placement-off-plate" in _ids(fit)
    off = next(f for f in fit["findings"] if f.get("id") == "placement-off-plate")
    assert "does not save a corrected copy" in off["action"]            # the writer only handles established projects
    assert "Studio can save a corrected copy" not in off["action"]


def test_an_established_project_keeps_its_fix_wording(tmp_path):
    p = project(tmp_path, [fx.cube_object("1", 10)], [("1", fx.tf(400, 50, 0))], name="est.3mf")
    fit = service.bed_fit(p)
    off = next(f for f in fit["findings"] if f.get("id") == "placement-off-plate")
    assert "Studio can save a corrected copy" in off["action"]
    assert "size_basis" not in fit                                      # not a guarded verdict


def test_a_scaled_item_is_sized_as_placed_not_as_modelled(tmp_path):
    p = make(tmp_path, "scaled", items=(("1", _SCALE20),))
    ext = geometry_basis.assess(p)["extents"]
    assert ext["measurable"] is True and ext["size_exact"] is False and ext["items_scaled"]
    fit = service.bed_fit(p)
    assert fit["size_basis"] == "as_placed"
    assert fit["objects_by_size"][0]["dims_mm"] == {"x": 200.0, "y": 400.0, "z": 600.0}


def test_a_shear_too_small_to_see_is_still_not_a_rotation(tmp_path):
    p = make(tmp_path, "shear", items=(("1", "1 0.0005 0 0 1 0 0 0 1 0 0 0"),))
    ext = geometry_basis.assess(p)["extents"]
    assert ext["items_scaled"] and not ext["items_rotated"]
    assert service.bed_fit(p)["size_basis"] == "as_placed"


def test_repeated_instances_of_a_scaled_object_are_each_sized(tmp_path):
    p = make(tmp_path, "twice", items=(("1", _IDENT), ("1", "2 0 0 0 2 0 0 0 2 100 0 0")))
    fit = service.bed_fit(p)
    assert fit["size_basis"] == "as_placed" and fit["objects_checked"] == 2
    assert sorted(o["dims_mm"]["x"] for o in fit["objects_by_size"]) == [10.0, 20.0]


# --- unknown stays unknown ------------------------------------------------------------------------------------

def test_what_studio_cannot_follow_stays_not_checked(tmp_path):
    loop = ('<object id="5" type="model"><components><component objectid="6"/></components></object>'
            '<object id="6" type="model"><components><component objectid="5"/></components></object>')
    cases = {
        "cycle": make(tmp_path, "cycle", items=(("5", _IDENT),), extra_objects=loop),
        "missing": make(tmp_path, "missing", items=(("99", _IDENT),)),
        "unreadable_tf": make(tmp_path, "badtf", items=(("1", "not numbers"),)),
    }
    for label, p in cases.items():
        assert geometry_basis.assess(p)["extents"]["measurable"] is False, label
        fit = service.bed_fit(p)
        assert fit["available"] is False and fit["status"] == "not_checked", label


def test_a_rotated_project_in_an_unknown_unit_is_not_measured(tmp_path):
    p = make(tmp_path, "both", unit="parsec", items=(("1", _ROT_Z90),))
    assert service.bed_fit(p)["status"] == "not_checked"


def test_only_bed_fit_opts_in_to_the_guarded_placement(tmp_path):
    """Preflight, the move writer and every other caller of plate_placement.assess keep 'not checked'."""
    from snapstudio_core import plate_placement as pp
    p = make(tmp_path, "optin", items=(("1", _ROT_Z90),))
    assert pp.assess(p)["status"] == "not_checked"
    assert pp.prepare_placed_copy(p, out_dir=str(tmp_path / "out"))["ok"] is False
    assert not (tmp_path / "out").exists()
    guarded = pp.assess(p, guarded=True)
    assert guarded["available"] is True and guarded["fix_withheld"] is True and guarded["fixable"] is False
    est = project(tmp_path, [fx.cube_object("1", 10)], [("1", fx.tf(100, 100, 0))], name="est2.3mf")
    assert pp.assess(est, guarded=True)["fix_withheld"] is False       # established projects are unaffected


def test_the_other_size_surfaces_still_withhold_for_a_guarded_project(tmp_path):
    """Only bed fit moved to the guarded basis; the rest measure the mesh BEFORE the transform."""
    p = make(tmp_path, "rest", unit="inch")
    assert service.predict_success(p)["status"] == "not_checked"
    assert service.first_layer(p)["status"] == "not_checked"
    assert service.scale_options(p)["status"] == "not_checked"
    assert service.scale_preview(p, 150)["fits_build_volume"] is None


def test_established_and_stl_files_carry_full_extents_and_no_guarded_label(tmp_path):
    p = make(tmp_path, "plain")
    ext = geometry_basis.assess(p)["extents"]
    assert ext["measurable"] and ext["size_exact"] and not ext["blocked_by"]
    assert geometry_basis.extents_measurable(geometry_basis.assess(p)) is False   # guarded path is only for the rest
    assert geometry_basis.extents_measurable(None) is False and geometry_basis.size_exact({}) is False
    assert geometry_basis.extents_measurable({"established": False, "extents": {"measurable": "yes"}}) is False


# --- the "N build items could not be measured" finding has a condition id and a step ----------------------------

def test_unmeasured_items_finding_has_an_id_and_an_action(tmp_path):
    root = fx.model_xml([fx.cube_object("1", 10)],
                        [("1", fx.tf(100, 100, 0)), ("1", fx.tf(100, 100, 0), "/3D/Objects/missing.model")])
    p = str(fx.three_mf(tmp_path / "u.3mf", root))
    fit = service.bed_fit(p)
    row = next(f for f in fit["findings"] if "could not be measured" in f["text"])
    assert row["id"] == "placement-not-judged" and "Snapmaker Orca" in row["action"]


# --- independent review of PR 153 (Opus): one unit rule, rotated size, item part, scope ---------------------------

@pytest.mark.parametrize("unit", [" inch ", "inch ", "Inch", "INCH", "inches"])
def test_a_unit_the_converter_would_not_recognise_is_never_called_converted(tmp_path, unit):
    """geometry.measure and geometry_basis must agree: an unrecognised value is left as written, so the
    basis may not claim it was converted (it would report a 10 mm cube as 'fits' and say it was converted)."""
    p = make(tmp_path, "pad", unit=unit)
    ext = geometry_basis.assess(p)["extents"]
    assert ext["measurable"] is False and ext["blocked_by"] == ["unit_unrecognized"] and not ext["converted_units"]
    fit = service.bed_fit(p)
    assert fit["available"] is False and fit["status"] == "not_checked"


def test_a_rotation_that_is_not_a_quarter_turn_is_sized_as_placed(tmp_path):
    # 45 degrees about Z: a 10 x 20 box is about 21.2 x 21.2 placed, not 10 x 20
    c = 0.7071067811865476
    p = make(tmp_path, "r45", items=(("1", f"{c} {c} 0 {-c} {c} 0 0 0 1 100 100 0"),))
    fit = service.bed_fit(p)
    assert fit["size_basis"] == "as_placed"
    dims = fit["objects_by_size"][0]["dims_mm"]
    assert abs(dims["x"] - 21.21) < 0.02 and abs(dims["y"] - 21.21) < 0.02 and dims["z"] == 30.0


def test_the_other_callers_still_read_the_numbers_as_written(tmp_path):
    """Unit conversion is opt-in (mm=True / convert_units=True); regrid, selfcheck and every other caller
    of geometry.* and project_info are unchanged."""
    p = make(tmp_path, "optin_units", unit="inch")
    [item] = geometry.measure_items(p)[0]
    assert item["dimensions"] == {"x": 10.0, "y": 20.0, "z": 30.0}
    assert project_info(p, placement_aware=True)["object_sizes_mm"][0]["dimensions_mm"]["x"] == 10.0
    assert project_info(p, placement_aware=True, convert_units=True)["object_sizes_mm"][0]["dimensions_mm"]["x"] == 254.0


# --- independent review of PR 153 head 8510301 (Sol): the part an item names, and one exact unit rule ------------

def test_an_unreadable_transform_in_the_part_a_build_item_names_is_never_measured_as_identity(tmp_path):
    """Root object 1 is a clean mesh, but the item names object 1 in a SUB part whose component transform is
    unreadable. geometry.measure follows the named part, so the basis must validate that same part."""
    sub = ('<object id="2" type="model">' + _mesh_xml(2) + '</object>'
           '<object id="1" type="model"><components><component objectid="2" transform="not numbers"/>'
           '</components></object>')
    root = '<object id="1" type="model">' + _mesh_xml(1) + '</object>'
    item = f'<item objectid="1" p:path="/3D/Objects/sub.model" transform="{_TF_Z90_AT_100}"/>'
    p = _write(tmp_path / "named_part.3mf", {"3D/3dmodel.model": _model(root, item, "millimeter"),
                                              "3D/Objects/sub.model": _model(sub, "", "millimeter")})
    ext = geometry_basis.assess(p)["extents"]
    assert ext["measurable"] is False and "transform_unreadable" in ext["blocked_by"]
    fit = service.bed_fit(p)
    assert fit["available"] is False and fit["status"] == "not_checked"


@pytest.mark.parametrize("unit", [" millimeter ", "Millimeter", "MILLIMETER"])
def test_a_millimetre_spelling_the_converter_would_not_recognise_does_not_authorise_a_rotated_verdict(tmp_path, unit):
    p = make(tmp_path, "mmvar", unit=unit, items=(("1", _ROT_Z90),))
    ext = geometry_basis.assess(p)["extents"]
    assert ext["measurable"] is False and ext["blocked_by"] == ["unit_unrecognized"]
    assert service.bed_fit(p)["status"] == "not_checked"


# --- independent review of PR 153 head 8510301 (Opus): footprints must not overwrite converted bounds ----------

def test_a_component_built_inch_project_is_not_sized_from_unconverted_footprints(tmp_path):
    """Object 2 is built from object 1 by <components> (the normal Orca shape), so placement.read_objects has a
    footprint for it, in file units. Rotated, so the size comes from the placed numbers: they must be the
    converted ones (254 x 508 mm before the turn), never the inch numbers."""
    root = ('<object id="1" type="model">' + _mesh_xml(1) + '</object>'
            '<object id="2" type="model"><components><component objectid="1"/></components></object>')
    p = _write(tmp_path / "comp_inch.3mf", {"3D/3dmodel.model": _model(root, f'<item objectid="2" transform="{_TF_Z90_AT_100}"/>', "inch")})
    fit = service.bed_fit(p)
    assert fit["available"] is True
    dims = fit["objects_by_size"][0]["dims_mm"]
    assert max(dims["x"], dims["y"]) >= 500.0 and fit["overall_level"] != "ok"


def test_a_centimetre_sub_part_placed_off_the_plate_is_reported_off_the_plate(tmp_path):
    sub = {"3D/Objects/o.model": _model('<object id="1" type="model">' + _mesh_xml(1) + '</object>', "", "centimeter")}
    root = ('<object id="2" type="model"><components>'
            '<component p:path="/3D/Objects/o.model" objectid="1"/></components></object>')
    parts = {"3D/3dmodel.model": _model(root, '<item objectid="2" transform="1 0 0 0 1 0 0 0 1 200 100 0"/>',
                                        "millimeter")}
    parts.update(sub)
    p = _write(tmp_path / "cm_off.3mf", parts)
    [item] = geometry.measure_items(p, mm=True)[0]
    assert item["bounds"]["max"][0] == 300.0                      # 200 mm + 10 cm
    from snapstudio_core import plate_placement as pp
    placed = pp.assess(p, guarded=True)
    assert [o["bounds_mm"]["max"][0] for o in placed["off_plate"]] == [300.0]     # the converted bound, not 215


# --- independent review of PR 153 head d6f35c9 (Sol): extents-only blockers must survive; no footprint overwrite ---

def test_an_unreadable_transform_in_the_named_part_is_not_established_even_without_a_rotation(tmp_path):
    sub = ('<object id="2" type="model">' + _mesh_xml(2) + '</object>'
           '<object id="1" type="model"><components><component objectid="2" transform="not numbers"/>'
           '</components></object>')
    root = '<object id="1" type="model">' + _mesh_xml(1) + '</object>'
    item = '<item objectid="1" p:path="/3D/Objects/sub.model" transform="1 0 0 0 1 0 0 0 1 100 100 0"/>'
    p = _write(tmp_path / "named_part_plain.3mf", {"3D/3dmodel.model": _model(root, item, "millimeter"),
                                                    "3D/Objects/sub.model": _model(sub, "", "millimeter")})
    basis = geometry_basis.assess(p)
    assert basis["established"] is False and "transform_unreadable" in basis["reasons"]
    fit = service.bed_fit(p)
    assert fit["available"] is False and fit["status"] == "not_checked"


def test_a_dotted_named_part_path_is_validated_in_the_part_geometry_reads(tmp_path):
    """Sol R1 (82285df): p:path '/3D/Objects/./sub.model' is the part geometry.normalize_part resolves; the basis
    must walk that same part, and a blocker found only there must keep the legacy gate not established."""
    sub = ('<object id="2" type="model">' + _mesh_xml(2) + '</object>'
           '<object id="1" type="model"><components><component objectid="2" transform="not numbers"/>'
           '</components></object>')
    root = '<object id="1" type="model">' + _mesh_xml(1) + '</object>'
    item = '<item objectid="1" p:path="/3D/Objects/./sub.model" transform="1 0 0 0 1 0 0 0 1 100 100 0"/>'
    p = _write(tmp_path / "dotted.3mf", {"3D/3dmodel.model": _model(root, item, "millimeter"),
                                          "3D/Objects/sub.model": _model(sub, "", "millimeter")})
    basis = geometry_basis.assess(p)
    assert basis["established"] is False and "transform_unreadable" in basis["reasons"]
    fit = service.bed_fit(p)
    assert fit["available"] is False and fit["status"] == "not_checked"


def test_a_backslash_path_and_nan_transform_in_the_named_part_are_not_established(tmp_path):
    for n, (path, tf) in enumerate([(r"\3D\Objects\sub.model", "not numbers"),
                                    ("/3D/Objects/sub.model", "nan 0 0 0 1 0 0 0 1 0 0 0")]):
        sub = ('<object id="2" type="model">' + _mesh_xml(2) + '</object>'
               f'<object id="1" type="model"><components><component objectid="2" transform="{tf}"/>'
               '</components></object>')
        root = '<object id="1" type="model">' + _mesh_xml(1) + '</object>'
        item = f'<item objectid="1" p:path="{path}" transform="1 0 0 0 1 0 0 0 1 100 100 0"/>'
        p = _write(tmp_path / f"bs{n}.3mf", {"3D/3dmodel.model": _model(root, item, "millimeter"),
                                              "3D/Objects/sub.model": _model(sub, "", "millimeter")})
        assert geometry_basis.assess(p)["established"] is False
        assert service.bed_fit(p)["status"] == "not_checked"


def test_a_component_resolved_only_by_fallback_into_another_part_is_not_established(tmp_path):
    a = '<object id="1" type="model"><components><component objectid="7"/></components></object>'
    c = ('<object id="8" type="model">' + _mesh_xml(8) + '</object>'
         '<object id="7" type="model"><components><component objectid="8" transform="not numbers"/>'
         '</components></object>')
    root = '<object id="1" type="model">' + _mesh_xml(1) + '</object>'
    item = '<item objectid="1" p:path="/3D/Objects/a.model" transform="1 0 0 0 1 0 0 0 1 100 100 0"/>'
    p = _write(tmp_path / "fallback.3mf", {"3D/3dmodel.model": _model(root, item, "millimeter"),
                                            "3D/Objects/a.model": _model(a, "", "millimeter"),
                                            "3D/Objects/c.model": _model(c, "", "millimeter")})
    assert geometry_basis.assess(p)["established"] is False
    assert service.bed_fit(p)["status"] == "not_checked"


def test_footprints_never_overwrite_the_exact_bounds_of_a_guarded_project(tmp_path):
    """Sol F2: placement.read_objects recognises only vertices written x,y,z; a mixed-order mesh gives it a
    partial footprint. With every unit factor 1 it used to replace the exact transformed bounds."""
    from snapstudio_core import plate_placement as pp
    from tests.test_geometry_verdict import _V, _F
    vs = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' if i < 2 else f'<vertex y="{y}" x="{x}" z="{z}"/>'
                 for i, (x, y, z) in enumerate(_V))
    ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in _F)
    mesh = f'<object id="1" type="model"><mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>'
    root = mesh + '<object id="2" type="model"><components><component objectid="1"/></components></object>'
    item = '<item objectid="2" transform="0 20 0 -20 0 0 0 0 20 210 10 0"/>'
    p = _write(tmp_path / "mixed_order.3mf", {"3D/3dmodel.model": _model(root, item, "millimeter")})
    [exact] = geometry.measure_items(p, mm=True)[0]
    placed = pp.placed_instances(p, measured=geometry.measure_items(p, mm=True), converted=True)
    [inst] = placed["instances"]
    assert inst["bounds_mm"]["min"] == [round(v, 3) for v in exact["bounds"]["min"]]
    assert inst["bounds_mm"]["max"] == [round(v, 3) for v in exact["bounds"]["max"]]


def test_a_non_model_root_element_is_never_called_converted(tmp_path):
    """Opus N-4: the converter reads no unit from a root that is not <model>, so the basis may not either."""
    from tests.test_geometry_verdict import _CORE, _PROD
    xml = _model('<object id="1" type="model">' + _mesh_xml(1) + '</object>',
                 '<item objectid="1" transform="1 0 0 0 1 0 0 0 1 100 100 0"/>', "inch").replace("<model", "<Model").replace("</model>", "</Model>")
    p = _write(tmp_path / "rootcase.3mf", {"3D/3dmodel.model": xml})
    ext = geometry_basis.assess(p)["extents"]
    assert not ext["converted_units"]
