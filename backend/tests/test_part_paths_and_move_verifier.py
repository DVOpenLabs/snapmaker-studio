"""Build items and components that name a part (p:path), plate records that cannot place an instance,
and the verifier that proves a moved copy changed only where things sit (issue 93 repair round)."""
from __future__ import annotations

import zipfile

from snapstudio_core import geometry, placement, plate_placement as pp
from tests import scene_fixtures as fx

SETTINGS = "Metadata/model_settings.config"
A, B = "3D/Objects/a.model", "3D/Objects/b.model"
MOVE = "every object moved by the same amount, in X and Y only"
KEPT = "every build item is still there, unchanged apart from where it sits"


def _rows(report):
    return {row["item_index"]: row for row in report["items"]}


def _two_parts(tmp_path, items, objects=(), settings=None, a_size=10, b_size=50, name="ext.3mf"):
    extra = {A: fx.sub_model_xml([fx.cube_object("1", a_size)]),
             B: fx.sub_model_xml([fx.cube_object("1", b_size)])}
    if settings:
        extra[SETTINGS] = settings
    return fx.three_mf(tmp_path / name, fx.model_xml(list(objects), items), extra)


# --- keyed by (part, object id) ------------------------------------------------------------------------

def test_object_one_in_two_parts_stays_two_objects(tmp_path):
    path = _two_parts(tmp_path, [("1", fx.tf(100, 100, 0), "/" + A), ("1", fx.tf(500, 100, 0), "/" + B)])
    report = pp.assess(str(path))
    rows = _rows(report)
    assert (rows[0]["bounds_mm"]["min"][0], rows[0]["bounds_mm"]["max"][0]) == (100.0, 110.0)
    assert (rows[1]["bounds_mm"]["min"][0], rows[1]["bounds_mm"]["max"][0]) == (500.0, 550.0)
    assert [row["item_index"] for row in report["off_plate"]] == [1]


def test_the_engine_reads_each_part_object_separately(tmp_path):
    settings = fx.model_settings_xml({"1": [("1", "normal_part")]}, [(1, [("1", 0), ("1", 1)])])
    path = _two_parts(tmp_path, [("1", fx.tf(100, 100, 0), "/" + A), ("1", fx.tf(500, 100, 0), "/" + B)],
                      settings=settings)
    objects = placement.read_objects(str(path))["objects"]
    assert [(o["part"], o["footprint"]["min_x"], o["footprint"]["max_x"]) for o in objects] == [
        (A, 100.0, 110.0), (B, 500.0, 550.0)]


def test_component_references_across_files_are_keyed_by_part(tmp_path):
    comp = fx.composite_object("5", [("1", "/" + A, None), ("1", "/" + B, fx.tf(100, 0, 0))])
    path = _two_parts(tmp_path, [("5", fx.tf(20, 20, 0))], objects=[comp], name="comp.3mf")
    [item] = pp.assess(str(path))["items"]
    # a.model's cube is 0..10; b.model's is 0..50 moved 100 by its component transform
    assert (item["bounds_mm"]["min"][0], item["bounds_mm"]["max"][0]) == (20.0, 170.0)
    [obj] = placement.read_objects(str(path))["objects"]
    assert (obj["footprint"]["min_x"], obj["footprint"]["max_x"]) == (20.0, 170.0)


def test_an_unresolvable_part_path_is_unresolved_not_the_root_object(tmp_path):
    # a decoy object 1 in the root model must NOT stand in for the missing part
    root = fx.model_xml([fx.cube_object("1", 10)],
                        [("1", fx.tf(100, 100, 0)), ("1", fx.tf(100, 100, 0), "/3D/Objects/missing.model")])
    report = pp.assess(str(fx.three_mf(tmp_path / "m.3mf", root)))
    assert [r["item_index"] for r in report["items"]] == [0]
    assert [u["item_index"] for u in report["unresolved_objects"]] == [1] and report["not_judged"] == 1
    assert "1 placed instance could not be judged" in report["summary"]
    assert report["summary"].startswith("Every placed instance Studio could measure") and report["fixable"] is False
    only = fx.three_mf(tmp_path / "o.3mf", fx.model_xml(
        [fx.cube_object("1", 10)], [("1", fx.tf(100, 100, 0), "/3D/Objects/missing.model")]))
    assert pp.assess(str(only))["available"] is False
    assert [u["item_index"] for u in geometry.measure_items(str(only))[1]] == [0]


def test_item_numbering_ignores_commented_out_items(tmp_path):
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(500, 100, 0)), ("1", fx.tf(100, 100, 0))])
    root = root.replace("<build>", '<build><!-- <item objectid="1" transform="1 0 0 0 1 0 0 0 1 9 9 0"/> -->')
    path = fx.three_mf(tmp_path / "c.3mf", root)
    assert [i["item_index"] for i in geometry.build_item_dims(str(path))] == [0, 1]
    assert [o["item_index"] for o in placement.read_objects(str(path))["objects"]] == [0, 1]


# --- instances Studio cannot place on a plate are never harmless ------------------------------------------

def _plated(tmp_path, items, plates, objects=None, name="pl.3mf"):
    objects = objects or {"1": [("1", "normal_part")]}
    settings = fx.model_settings_xml(objects, plates)
    return fx.three_mf(tmp_path / name, fx.model_xml([fx.cube_object(o, 10) for o in objects], items),
                       {SETTINGS: settings})


def test_instances_with_no_instance_id_are_not_judged_and_never_reported_as_fitting(tmp_path):
    path = _plated(tmp_path, [("1", fx.tf(50, 50, 0)), ("1", fx.tf(400, 50, 0))],
                   [(1, [("1", None)]), (2, [("1", None)])])
    report = pp.assess(str(path))
    assert report["not_judged"] == 2 and len(report["unresolved_objects"]) == 2
    assert "2 placed instances could not be judged" in report["summary"]
    assert "All" not in report["summary"] and "fit" not in report["summary"].lower().replace("fits", "")
    assert report["plate_fit"] == [] and report["fixable"] is False


def test_some_instances_judged_and_some_not_is_said_plainly(tmp_path):
    objects = {"1": [("1", "normal_part")], "2": [("2", "normal_part")]}
    path = _plated(tmp_path, [("1", fx.tf(50, 50, 0)), ("1", fx.tf(60, 50, 0)), ("2", fx.tf(400, 50, 0))],
                   [(1, [("1", None)]), (2, [("2", 0)])], objects=objects)
    report = pp.assess(str(path))
    assert report["not_judged"] == 2 and "All" not in report["summary"]
    assert report["summary"].startswith("None of the plates Studio could assign is too big")
    assert "2 placed instances could not be judged" in report["summary"]


# --- the verifier: negative tests --------------------------------------------------------------------------

def _mutate(src, dest, edit):
    with zipfile.ZipFile(src) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries["3D/3dmodel.model"] = edit(entries["3D/3dmodel.model"].decode("utf-8")).encode("utf-8")
    return str(fx.write_zip(dest, entries))


def _source(tmp_path):
    return str(_two_parts(tmp_path, [("1", fx.tf(-5, 100, 0), "/" + A), ("1", fx.tf(100, 100, 0), "/" + B)],
                          name="v.3mf"))


def _moved(text):
    return text.replace("1 -5 100 0", "1 1 100 0").replace("1 100 100 0", "1 106 100 0")


def _checks(result):
    return {c["check"]: c["pass"] for c in result["checks"]}


def test_a_faithful_uniform_move_passes_the_verifier(tmp_path):
    src = _source(tmp_path)
    result = pp.verify_only_placement_moved(src, _mutate(src, tmp_path / "ok.3mf", _moved))
    assert result["passed"] is True and result["delta_mm"] == {"x": 6.0, "y": 0.0}


def test_switching_an_items_part_path_fails_the_verifier(tmp_path):
    src = _source(tmp_path)

    def swap(text):
        return _moved(text).replace("/" + A, "/@").replace("/" + B, "/" + A).replace("/@", "/" + B)

    result = pp.verify_only_placement_moved(src, _mutate(src, tmp_path / "swap.3mf", swap))
    assert result["passed"] is False and _checks(result)[KEPT] is False


def test_changing_another_item_attribute_fails_the_verifier(tmp_path):
    src = _source(tmp_path)
    result = pp.verify_only_placement_moved(
        src, _mutate(src, tmp_path / "attr.3mf", lambda t: _moved(t).replace("<item ", '<item printable="0" ', 1)))
    assert result["passed"] is False and _checks(result)[KEPT] is False


def test_a_copy_that_moved_only_one_instance_fails_the_verifier(tmp_path):
    src = _source(tmp_path)
    result = pp.verify_only_placement_moved(
        src, _mutate(src, tmp_path / "one.3mf", lambda t: t.replace("1 -5 100 0", "1 1 100 0")))
    assert result["passed"] is False and result["delta_mm"] is None and _checks(result)[MOVE] is False


def test_a_copy_that_did_not_move_at_all_is_not_a_moved_copy(tmp_path):
    src = _source(tmp_path)
    result = pp.verify_only_placement_moved(src, _mutate(src, tmp_path / "same.3mf", lambda t: t))
    assert _checks(result)[MOVE] is False and result["passed"] is False


def test_a_move_other_than_the_one_asked_for_is_refused(tmp_path, monkeypatch):
    src = fx.three_mf(tmp_path / "s.3mf", fx.model_xml(
        [fx.cube_object("1", 10)], [("1", fx.tf(-5, 100, 0)), ("1", fx.tf(100, 100, 0))]))
    real = pp.verify_only_placement_moved

    def lying(a, b):
        out = real(a, b)
        out["delta_mm"] = {"x": 1.0, "y": 0.0}
        return out

    monkeypatch.setattr(pp, "verify_only_placement_moved", lying)
    result = pp.prepare_placed_copy(str(src), out_dir=str(tmp_path / "out"))
    assert result["ok"] is False and "was not kept" in result["reason"]


# --- bounded reading, and instance numbers that mean the same object -------------------------------------

def test_two_parts_sharing_an_object_id_are_not_instances_of_each_other(tmp_path):
    path = _two_parts(tmp_path, [("1", fx.tf(100, 100, 0), "/" + A), ("1", fx.tf(500, 100, 0), "/" + B)], name="lbl.3mf")
    report = pp.assess(str(path))
    assert [(r["instance_index"], r["instance_count"]) for r in report["items"]] == [(0, 1), (0, 1)]
    assert "instance" not in report["summary"]
    assert [(o["instance_index"], o["instance_count"]) for o in placement.read_objects(str(path))["objects"]] == [(0, 1), (0, 1)]


def test_too_many_vertices_is_refused_while_collecting_never_reported_fine(tmp_path, monkeypatch):
    settings = fx.model_settings_xml({"1": [("1", "normal_part")]}, [(1, [("1", 0), ("1", 1)])])
    path = str(fx.three_mf(tmp_path / "v.3mf", fx.model_xml(
        [fx.cube_object("1", 10)], [("1", fx.tf(100, 100, 0)), ("1", fx.tf(500, 100, 0))]), {SETTINGS: settings}))
    monkeypatch.setattr(geometry, "_MAX_VERTS", 10)          # the file holds 8 vertices, 16 once placed twice
    import pytest
    with pytest.raises(placement.TooLargeToMeasure):
        placement.read_objects(path)
    report = pp.assess(path)
    assert report["available"] is False                       # a clear "could not measure", not an OK


def test_a_highly_compressed_archive_is_refused_not_expanded(tmp_path):
    import time
    big = fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(100, 100, 0))])
    padded = big.replace("<resources>", "<resources>" + "<!--" + " " * (90 * 1024 * 1024) + "-->")
    path = tmp_path / "bomb.3mf"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("_rels/.rels", fx.rels_xml())
        z.writestr("3D/3dmodel.model", padded)
    assert path.stat().st_size < 1_000_000
    started = time.perf_counter()
    report = pp.assess(str(path))
    assert report["available"] is False
    assert time.perf_counter() - started < 20
    try:
        placement.read_objects(str(path))
        raise AssertionError("expected a refusal")
    except placement.TooLargeToMeasure:
        pass
