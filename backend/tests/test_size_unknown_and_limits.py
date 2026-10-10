"""Issue 91 repair round: an unknown size stays unknown, every object is checked, size wording claims no
position, and measuring a project once is enough."""
from __future__ import annotations

from snapstudio_api import service
from snapstudio_core import bed_fit, geometry, placement, plate_placement as pp
from snapstudio_core.intelligence import project_info
from tests import scene_fixtures as fx
from tests.test_size_vs_placed_bounds import box_object, project, texts

SETTINGS = "Metadata/model_settings.config"


def _renamed_root(tmp_path):
    """Two small meshes authored 500 mm apart, in a project whose root model is NOT 3D/3dmodel.model."""
    root = fx.model_xml([box_object("1", 20, 20, 20), box_object("2", 20, 20, 20, origin=(500, 0, 0))],
                        [("1", fx.tf(50, 50, 0)), ("2", fx.tf(-400, 50, 0))])
    entries = {"_rels/.rels": fx.rels_xml(target="/3D/main.model"), "3D/main.model": root}
    return str(fx.write_zip(tmp_path / "renamed.3mf", entries))


# --- unknown stays unknown ----------------------------------------------------------------------------

def test_unmeasured_objects_do_not_fall_back_to_the_combined_extents(tmp_path):
    path = _renamed_root(tmp_path)
    info = project_info(path, placement_aware=True)
    assert info["object_sizes_mm"] == []
    assert info["dimensions_mm"]["x"] == 520.0                       # the legacy figure still exists ...
    result = service.bed_fit(path)                                   # ... and is not used for fit
    assert result["available"] is False and result["reason"] == bed_fit.UNMEASURED_TEXT
    assert "scale" not in result["reason"].lower() and "too big" not in result["reason"].lower()
    check = next(c for c in service.report(path)["checks"] if c["name"] == "Fits the print bed")
    assert check["status"] == "warn" and check["detail"] == bed_fit.UNMEASURED_TEXT


def test_assess_objects_with_nothing_measured_is_unavailable_not_a_guess():
    out = bed_fit.assess_objects([])
    assert out["available"] is False and out["reason"] == bed_fit.UNMEASURED_TEXT
    assert bed_fit.assess_objects(None)["available"] is False


def test_some_objects_unmeasured_never_reads_as_everything_fits(tmp_path):
    root = fx.model_xml([fx.cube_object("1", 10)],
                        [("1", fx.tf(100, 100, 0)), ("1", fx.tf(100, 100, 0), "/3D/Objects/missing.model")])
    path = str(fx.three_mf(tmp_path / "u.3mf", root))
    info = project_info(path, placement_aware=True)
    assert info["objects_unmeasured"] == 1 and len(info["object_sizes_mm"]) == 1
    result = service.bed_fit(path)
    assert result["overall_level"] == "warn" and result["objects_unmeasured"] == 1
    assert "could not be measured" in result["overall_text"]
    check = next(c for c in service.report(path)["checks"] if c["name"] == "Fits the print bed")
    assert check["status"] == "warn" and "1 build item could not be measured" in check["detail"]


# --- every object is checked ----------------------------------------------------------------------------

def test_the_65th_object_is_checked_too(tmp_path):
    objects = [box_object(str(i), 10, 10, 10) for i in range(1, 65)] + [box_object("65", 10, 10, 300)]
    items = [(str(i), fx.tf(5 + (i % 20) * 12, 5 + (i // 20) * 12, 0)) for i in range(1, 66)]
    path = project(tmp_path, objects, items)
    result = service.bed_fit(path)
    assert result["objects_checked"] == 65 and result["overall_level"] == "risk"
    assert "By size, object 65 is taller than" in texts(result)
    check = next(c for c in service.report(path)["checks"] if c["name"] == "Fits the print bed")
    assert check["status"] == "warn" and "object 65 (10.0 × 10.0 × 300.0 mm)" in check["detail"]


# --- size statements claim no position -----------------------------------------------------------------------

def test_the_prime_tower_finding_is_about_size_not_placement():
    out = bed_fit.assess({"x": 250, "y": 250, "z": 40}, multi_material=True)
    tower = next(f for f in out["findings"] if "tower" in f["text"])
    assert tower["text"].startswith("By size,") and "Snapmaker Orca" in tower["text"]
    assert "off the bed" not in tower["text"] and "push" not in tower["text"]


def test_a_multi_plate_project_is_not_told_its_objects_share_one_plate(tmp_path):
    settings = fx.model_settings_xml({"1": [("1", "normal_part")], "2": [("2", "normal_part")]},
                                     [(1, [("1", 0)]), (2, [("2", 0)])])
    path = project(tmp_path, [fx.cube_object("1", 10), fx.cube_object("2", 10)],
                   [("1", fx.tf(50, 50, 0)), ("2", fx.tf(400, 50, 0))], settings=settings)
    text = texts(service.bed_fit(path))
    assert "share the plate" not in text and "whole arrangement must fit" not in text
    assert "Whatever sits on one plate must fit that plate" in text


def test_overall_wording_names_size_first():
    big = bed_fit.assess({"x": 320, "y": 100, "z": 50})
    assert big["overall_text"] == ("By size, this model won't fit as-is — this is the out-of-bounds error, "
                                   "with the fix below.")
    tight = bed_fit.assess({"x": 262, "y": 120, "z": 40})
    assert tight["overall_text"] == "By size, it fits, but the edges are tight — see below before slicing."


# --- a size is as modelled; a scaled item shows up as a placed bound ------------------------------------------

def test_object_size_ignores_scale_and_turn_on_the_first_item(tmp_path):
    path = project(tmp_path, [box_object("1", 10, 10, 10)],
                   [("1", "2 0 0 0 2 0 0 0 2 10 10 0"), ("1", "0 1 0 -1 0 0 0 0 1 50 50 0")])
    [size] = geometry.object_sizes(path)
    assert size["dimensions"] == {"x": 10.0, "y": 10.0, "z": 10.0} and size["instance_count"] == 2
    placed = geometry.build_item_dims(path)
    assert placed[0]["dimensions"] == {"x": 20.0, "y": 20.0, "z": 20.0}


def test_a_scaled_instance_beyond_the_bed_is_caught_by_placement_not_size(tmp_path):
    path = project(tmp_path, [box_object("1", 100, 100, 10)], [("1", "3 0 0 0 3 0 0 0 1 10 10 0")])
    result = service.bed_fit(path)
    assert result["overall_level"] == "risk"
    assert result["overall_text"].startswith("By size, this model is small enough")
    assert any(f["text"].startswith("By placement") for f in result["findings"] if f["level"] == "risk")


# --- measure once -------------------------------------------------------------------------------------------

def test_a_project_is_measured_once_across_the_consumers(tmp_path, monkeypatch):
    path = project(tmp_path, [fx.cube_object("1", 10)], [("1", fx.tf(100, 100, 0))], name="once.3mf")
    calls = {"measure": 0, "read": 0}
    real_measure, real_read = geometry._measure_uncached, placement._read_objects

    def counting_measure(p):
        calls["measure"] += 1
        return real_measure(p)

    def counting_read(p):
        calls["read"] += 1
        return real_read(p)

    monkeypatch.setattr(geometry, "_measure_uncached", counting_measure)
    monkeypatch.setattr(placement, "_read_objects", counting_read)
    project_info(path, placement_aware=True)
    service.bed_fit(path)
    service.report(path)
    assert calls == {"measure": 1, "read": 1}


def test_the_measurement_cache_follows_the_file(tmp_path):
    path = project(tmp_path, [fx.cube_object("1", 10)], [("1", fx.tf(100, 100, 0))], name="chg.3mf")
    assert geometry.object_sizes(path)[0]["dimensions"]["x"] == 10.0
    project(tmp_path, [fx.cube_object("1", 30)], [("1", fx.tf(100, 100, 0))], name="chg.3mf")
    assert geometry.object_sizes(path)[0]["dimensions"]["x"] == 30.0


def test_measuring_sizes_and_items_does_not_halve_the_vertex_limit(tmp_path, monkeypatch):
    path = project(tmp_path, [fx.cube_object("1", 10), fx.cube_object("2", 10)],
                   [("1", fx.tf(10, 10, 0)), ("2", fx.tf(60, 10, 0))], name="lim.3mf")
    monkeypatch.setattr(geometry, "_MAX_VERTS", 16)           # exactly the 16 vertices the file holds
    items, unresolved, sizes = geometry.measure(path)
    assert len(items) == 2 and len(sizes) == 2 and unresolved == []


def test_two_parts_with_the_same_object_id_have_two_sizes(tmp_path):
    a, b = "3D/Objects/a.model", "3D/Objects/b.model"
    extra = {a: fx.sub_model_xml([fx.cube_object("1", 10)]), b: fx.sub_model_xml([fx.cube_object("1", 50)])}
    path = str(fx.three_mf(tmp_path / "two.3mf", fx.model_xml(
        [], [("1", fx.tf(10, 10, 0), "/" + a), ("1", fx.tf(100, 10, 0), "/" + b)]), extra))
    sizes = {s["part"]: s["dimensions"]["x"] for s in geometry.object_sizes(path)}
    assert sizes == {a: 10.0, b: 50.0}
    assert pp.assess(path)["available"]


def test_project_info_keeps_its_old_cost_unless_asked_for_placement_data(tmp_path, monkeypatch):
    path = project(tmp_path, [fx.cube_object("1", 10)], [("1", fx.tf(100, 100, 0))], name="plain.3mf")
    monkeypatch.setattr(geometry, "_measure_uncached", lambda p: (_ for _ in ()).throw(AssertionError("read")))
    info = project_info(path)
    assert info["object_sizes_mm"] is None and info["placed"] is None and info["objects_unmeasured"] is None
    assert info["dimensions_mm"] == {"x": 10.0, "y": 10.0, "z": 10.0}
