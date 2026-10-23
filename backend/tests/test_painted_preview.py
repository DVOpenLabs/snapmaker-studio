"""The painted preview: what is drawn, where each colour comes from, and every case it declines.

The preview is the one place Studio shows a person which filament prints where, so most of what is
tested here is the edge of that claim: the file that is not in millimetres, the facet whose paint
cannot be decoded, the project that says nothing about its unpainted parts, and a result that would
have to be cut down to fit. Colours are carried per slot, so the tests that matter most compare the
*prepared copy Studio actually wrote* with the original: an unselected slot must come out unchanged,
and a chosen replacement must change only the slot that was chosen.
"""
from __future__ import annotations

import base64
import json
import os
import struct
import sys
import zipfile
from array import array
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from painted_fixtures import TRIANGLE_AREA, bambu_project, paint, prusa_project  # noqa: E402
from scene_fixtures import (CORE, PROD, cube_object, model_xml, plain_cube_3mf, three_mf, tf)  # noqa: E402

from snapstudio_core import convert, painted_color, painted_preview as pp  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "painted"
BAMBU = FIXTURES / "bambustudio-2.08.02.61-authored.3mf"
ORCA_CUBE = FIXTURES / "orcaslicer-2.4.2-painted-cube.3mf"
PRUSA_CUBE = FIXTURES / "prusaslicer-2.9.6-painted-cube.3mf"
SLAB = FIXTURES / "snapmaker-orca-2.3.5-authored.3mf"


def slot(result, number):
    for row in result["slots"]:
        if row["slot"] == number:
            return row
    raise AssertionError(f"slot {number} not in {[r['slot'] for r in result['slots']]}")


def triangles(result, mesh_key=None):
    """Drawn triangles per slot, counted from the float arrays a viewer would receive."""
    out: dict = {}
    for mesh in result["meshes"]:
        if mesh_key is not None and mesh["key"] != mesh_key:
            continue
        for part in mesh["parts"]:
            floats = array("f")
            floats.frombytes(base64.b64decode(part["positions_f32le_base64"]))
            assert len(floats) == part["triangles"] * 9
            out[part["slot"]] = out.get(part["slot"], 0) + part["triangles"]
    return out


# --- the four real-slicer fixtures -------------------------------------------------------------

def test_a_painted_project_is_split_by_slot_and_agrees_with_the_painting_reader():
    got = pp.build(str(ORCA_CUBE))
    assert (got["state"], got["kind"]) == ("ok", "painted")
    read = painted_color.read(str(ORCA_CUBE))
    assert read["slots_referenced"] == [s["slot"] for s in got["slots"] if s["from_painting"]]
    for entry in got["slots"]:
        if not entry["from_painting"]:
            continue
        painted_area = sum(a["area_mm2"] for o in read["objects"] for a in o["assignments"]
                           if a["painted"] and a["slot"] == entry["slot"])
        assert entry["painted_area_mm2"] == pytest.approx(painted_area, rel=1e-3), entry["slot"]
    assert got["counts"]["painted_triangles"] == read["painted_triangle_count"]
    assert got["counts"]["leaves"] == sum(o["leaf_count"] for o in read["objects"])
    # What is drawn is what was counted: every triangle in the output belongs to some slot.
    assert sum(triangles(got).values()) == got["counts"]["triangles_out"]


def test_slots_beyond_the_four_toolheads_are_all_listed_with_their_own_colour():
    got = pp.build(str(SLAB))
    assert got["state"] == "ok"
    assert [s["slot"] for s in got["slots"]] == [1, 2, 3, 4, 5]
    assert slot(got, 5)["colour"] == "#DE4343"          # the fifth colour is not folded into another
    assert slot(got, 4)["colour"] == "#61C680"
    # Dense authored paint: thousands of exact patches, none sampled, and the body stays within the budget.
    assert got["counts"]["leaves"] > 60_000
    assert got["counts"]["triangles_out"] <= pp.MAX_TRIANGLES_OUT
    assert len(json.dumps(got)) < 8 * 1024 * 1024


def test_a_project_that_states_no_colours_leaves_them_unknown_rather_than_inventing_them():
    got = pp.build(str(PRUSA_CUBE))
    assert (got["state"], got["kind"]) == ("ok", "painted")
    assert all(s["colour"] is None for s in got["slots"])
    assert any("does not list filament colours" in n for n in got["notes"])


def test_every_instance_carries_a_full_placement():
    for fixture in (BAMBU, ORCA_CUBE, PRUSA_CUBE, SLAB):
        got = pp.build(str(fixture))
        assert got["instances"], fixture.name
        for inst in got["instances"]:
            assert len(inst["world_mm"]) == 16
            assert inst["mesh"] in {m["key"] for m in got["meshes"]}
        assert got["bed"]["polygon_mm"], fixture.name


# --- what it does with a project that does not say ---------------------------------------------

def test_an_unpainted_part_with_no_stated_filament_is_neutral_not_slot_one(tmp_path):
    # Two facets, one painted slot 2, the other left alone, and no filament assigned to the part.
    path = bambu_project(tmp_path, meshes=[{"painted": {0: paint(2)}, "extruder": None}])
    got = pp.build(path)
    assert got["state"] == "ok"
    by_slot = triangles(got)
    assert by_slot.get(2) == 1                       # the painted facet
    assert by_slot.get(None) == 1                    # the unpainted facet: no stated slot, drawn neutral
    assert got["unknown_default"] is True
    assert slot(got, 1)["area_mm2"] == 0.0           # slot 1 was not credited with it
    assert any("no filament" in n.lower() or "does not record a slot" in n.lower() for n in got["notes"])


def test_an_unpainted_project_is_drawn_in_the_slots_it_assigns(tmp_path):
    path = bambu_project(tmp_path, meshes=[{"painted": {}, "extruder": 3}])
    got = pp.build(path)
    assert (got["state"], got["kind"]) == ("ok", "assigned")
    assert triangles(got) == {3: 2}
    assert slot(got, 3)["from_assignment"] is True and slot(got, 3)["from_painting"] is False
    assert got["unknown_default"] is False


def test_a_mixed_facet_is_split_exactly_into_its_slots(tmp_path):
    tree = (0, [1, 3, 4])                           # a quarter, a quarter and a half, as the format fixes them
    got = pp.build(bambu_project(tmp_path, meshes=[{"painted": {0: paint(tree)}, "extruder": 2}]))
    assert slot(got, 1)["painted_area_mm2"] == pytest.approx(TRIANGLE_AREA * 0.25)
    assert slot(got, 3)["painted_area_mm2"] == pytest.approx(TRIANGLE_AREA * 0.25)
    assert slot(got, 4)["painted_area_mm2"] == pytest.approx(TRIANGLE_AREA * 0.5)
    # Each share is drawn as its own exact patch (the fourth is the mesh's other, unpainted facet in slot 2).
    assert triangles(got) == {1: 1, 2: 1, 3: 1, 4: 1}
    assert got["counts"]["leaves"] == 3
    assert sum(r["painted_area_mm2"] for r in got["slots"]) == pytest.approx(TRIANGLE_AREA)


def test_one_undecodable_facet_is_counted_and_drawn_neutral_while_the_rest_is_drawn(tmp_path):
    path = bambu_project(tmp_path, meshes=[{"painted": {0: "not-hex!", 1: paint(2)}, "extruder": 1}])
    got = pp.build(path)
    assert got["state"] == "ok"
    assert got["counts"]["malformed"] == 1
    assert triangles(got) == {None: 1, 2: 1}         # not drawn as painted, not dropped
    assert any("could not be decoded" in n for n in got["notes"])


# --- what it declines, and says why ------------------------------------------------------------

def test_a_project_not_in_millimetres_is_declined_not_converted(tmp_path):
    path = three_mf(tmp_path / "inch.3mf", model_xml([cube_object("1")], [("1", tf(0, 0, 0))], unit="inch"))
    got = pp.build(str(path))
    assert (got["available"], got["state"]) == (False, "unsupported")
    assert "millimetre" in got["reason"]
    assert got["meshes"] == []


def test_a_file_that_is_not_an_archive_is_unreadable_with_a_plain_reason(tmp_path):
    path = tmp_path / "broken.3mf"
    path.write_text("not a zip")
    got = pp.build(str(path))
    assert (got["available"], got["state"]) == (False, "unreadable")
    assert got["reason"] and "Traceback" not in got["reason"]


def test_an_archive_without_a_root_model_is_unreadable(tmp_path):
    path = tmp_path / "empty.3mf"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Metadata/readme.txt", "no geometry here")
    got = pp.build(str(path))
    assert (got["available"], got["state"]) == (False, "unreadable")


def test_a_missing_file_does_not_raise(tmp_path):
    got = pp.build(str(tmp_path / "nothing.3mf"))
    assert got["available"] is False and got["reason"]


def test_a_format_other_than_3mf_or_stl_is_declined():
    got = pp.build("model.obj")
    assert (got["available"], got["state"]) == (False, "unsupported")


def test_past_the_triangle_budget_nothing_is_returned_rather_than_a_part(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "MAX_TRIANGLES_OUT", 5)
    got = pp.build(str(ORCA_CUBE))
    assert (got["available"], got["state"]) == (False, "limit")
    assert got["meshes"] == [] and got["slots"] == []
    assert "shows the preview only when it can show all of it" in got["reason"]


def test_past_the_painted_facet_budget_nothing_is_returned(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "MAX_PAINTED_FACETS", 1)
    got = pp.build(str(ORCA_CUBE))
    assert (got["available"], got["state"]) == (False, "limit")


def test_a_facet_finer_than_the_decoder_follows_is_a_limit_not_a_partial_drawing(tmp_path, monkeypatch):
    real = pp.paint_codec.decode
    monkeypatch.setattr(pp.paint_codec, "decode", lambda attr, corners: real(attr, corners, max_leaves=1))
    got = pp.build(str(ORCA_CUBE))
    assert (got["available"], got["state"]) == (False, "limit")


# --- geometry-only ---------------------------------------------------------------------------

def _binary_stl(path: Path) -> Path:
    tris = [((0, 0, 0), (10, 0, 0), (0, 10, 0)), ((0, 0, 0), (0, 10, 0), (0, 0, 10))]
    data = b"synthetic".ljust(80, b" ") + struct.pack("<I", len(tris))
    for a, b, c in tris:
        data += struct.pack("<12fH", 0, 0, 1, *a, *b, *c, 0)
    path.write_bytes(data)
    return path


def test_an_stl_is_geometry_only_and_is_not_a_painted_coverage_result(tmp_path):
    got = pp.build(str(_binary_stl(tmp_path / "m.stl")))
    assert (got["state"], got["kind"]) == ("ok", "geometry")
    assert got["slots"] == []
    assert triangles(got) == {None: 2}
    assert any("no unit" in n for n in got["notes"])


def test_a_3mf_with_no_filament_information_is_geometry_only(tmp_path):
    got = pp.build(str(plain_cube_3mf(tmp_path / "cube.3mf")))
    assert (got["state"], got["kind"]) == ("ok", "geometry")
    assert got["slots"] == [] and got["unknown_default"] is True


# --- repeated instances ----------------------------------------------------------------------

def test_repeated_build_items_are_distinct_instances_of_one_shared_mesh(tmp_path):
    model = model_xml([cube_object("1")], [("1", tf(10, 10, 0)), ("1", tf(60, 10, 0)), ("1", tf(110, 10, 0))])
    got = pp.build(str(three_mf(tmp_path / "three.3mf", model)))
    assert got["state"] == "ok"
    assert len(got["meshes"]) == 1                              # the geometry travels once
    labels = [i["label"] for i in got["instances"]]
    assert labels == ["Object 1 · instance 1 of 3", "Object 1 · instance 2 of 3", "Object 1 · instance 3 of 3"]
    assert len({i["id"] for i in got["instances"]}) == 3
    assert len({tuple(i["world_mm"]) for i in got["instances"]}) == 3   # each at its own place


def test_painted_repeated_instances_share_the_painted_geometry_and_keep_their_places(tmp_path):
    path = bambu_project(tmp_path, meshes=[{"painted": {0: paint(2)}, "extruder": 1}])
    # The root model of the builder places one item; add a second item of the same assembly.
    root = zipfile.ZipFile(path).read("3D/3dmodel.model").decode()
    item = '<item objectid="100" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
    other = '<item objectid="100" transform="1 0 0 0 1 0 0 0 1 80 0 0"/>'
    assert item in root
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["3D/3dmodel.model"] = root.replace(item, item + other).encode()
    with zipfile.ZipFile(path, "w") as z:
        for n, d in parts.items():
            z.writestr(n, d)
    got = pp.build(path)
    assert got["state"] == "ok"
    assert len(got["meshes"]) == 1 and triangles(got) == {1: 1, 2: 1}
    assert len(got["instances"]) == 2
    xs = sorted(i["world_mm"][12] for i in got["instances"])
    assert xs == [0.0, 80.0]


# --- prepared copies written by Studio ------------------------------------------------------

def _summary(result):
    return [(s["slot"], s["colour"], s["painted_triangles"], s["painted_area_mm2"], s["area_mm2"]) for s in result["slots"]]


def test_preparing_without_choices_changes_no_slot_colour_or_painted_region(tmp_path):
    prepared = convert.convert_to_u1(str(ORCA_CUBE), str(tmp_path), "preserve")
    assert prepared.validated_ok and not prepared.blocked
    before, after = pp.build(str(ORCA_CUBE)), pp.build(prepared.output_path)
    assert after["state"] == "ok"
    assert _summary(after) == _summary(before)
    assert triangles(after) == triangles(before)


def test_a_chosen_colour_replaces_exactly_the_chosen_slot_in_the_written_copy(tmp_path):
    prepared = convert.convert_to_u1(str(ORCA_CUBE), str(tmp_path), "preserve", confirmed_colours={1: "#112233"})
    assert prepared.validated_ok and not prepared.blocked
    before, after = pp.build(str(ORCA_CUBE)), pp.build(prepared.output_path)
    assert slot(after, 2)["colour"] == "#112233"
    assert slot(before, 2)["colour"] == "#FFFFFF"
    # Nothing else moved: same slots, other colours untouched, the painted geometry identical.
    for number in (1, 3, 4, 5):
        assert slot(after, number) == slot(before, number)
    assert {k: v for k, v in slot(after, 2).items() if k != "colour"} == {k: v for k, v in slot(before, 2).items() if k != "colour"}
    assert triangles(after) == triangles(before)


def test_more_than_four_colours_survive_preparation_with_all_their_colours(tmp_path):
    prepared = convert.convert_to_u1(str(SLAB), str(tmp_path), "preserve")
    assert prepared.validated_ok and not prepared.blocked
    before, after = pp.build(str(SLAB)), pp.build(prepared.output_path)
    assert [s["slot"] for s in after["slots"]] == [1, 2, 3, 4, 5]
    assert _summary(after) == _summary(before)
    assert slot(after, 5)["colour"] == "#DE4343"      # the fifth colour is neither dropped nor mixed into a head's


# --- determinism and the route -------------------------------------------------------------

def test_the_same_file_gives_the_same_answer():
    assert pp.build(str(ORCA_CUBE)) == pp.build(str(ORCA_CUBE))


def test_the_response_names_no_local_path():
    blob = json.dumps(pp.build(str(ORCA_CUBE)))
    assert str(FIXTURES) not in blob and "\\Users\\" not in blob


# --- review repairs: what is not drawn, what is not guessed, what is bounded ----------------------

import scene_fixtures as sf  # noqa: E402


def test_a_project_with_a_modifier_or_negative_part_is_declined_not_drawn_as_printing_surface(tmp_path):
    path = sf.bambu_project(tmp_path / "mod.3mf", parts=3, items=[("100", sf.tf(10, 10, 0))], plates=[(1, [("100", None)])],
                            roles=["normal_part", "modifier_part", "negative_part"])
    got = pp.build(str(path))
    assert (got["available"], got["state"]) == (False, "unsupported")
    assert "modifiers" in got["reason"] and got["meshes"] == []


def test_a_prusa_modifier_volume_inside_a_mesh_is_declined(tmp_path):
    path = sf.prusa_project(tmp_path / "mod.3mf", volumes=[(0, 11, "ModelPart"), (12, 23, "ParameterModifier")])
    assert pp.build(str(path))["state"] == "unsupported"


def test_an_unrecognised_unit_is_declined_and_never_drawn_as_guessed_millimetres(tmp_path):
    path = three_mf(tmp_path / "odd.3mf", model_xml([cube_object("1")], [("1", tf(0, 0, 0))], unit="furlong"))
    got = pp.build(str(path))
    assert (got["available"], got["state"]) == (False, "unsupported")
    assert "unit" in got["reason"] and got["meshes"] == []


def test_the_drawn_triangle_budget_counts_every_placed_copy(tmp_path, monkeypatch):
    items = [("1", tf(i * 15, 0, 0)) for i in range(6)]
    path = three_mf(tmp_path / "six.3mf", model_xml([cube_object("1")], items))
    assert pp.build(str(path))["counts"]["triangles_drawn"] == 6 * 12
    monkeypatch.setattr(pp, "MAX_RENDERED_TRIANGLES", 6 * 12 - 1)
    got = pp.build(str(path))
    assert (got["available"], got["state"]) == (False, "limit")
    assert "every placed copy" in got["reason"]


def test_a_file_replaced_while_it_is_being_read_is_refused_not_mixed(tmp_path, monkeypatch):
    path = plain_cube_3mf(tmp_path / "a.3mf")
    real, calls = pp._stamp, []

    def moving(p):
        calls.append(1)
        stamp = real(p)
        return stamp if len(calls) == 1 else (stamp[0] + 1, stamp[1])

    monkeypatch.setattr(pp, "_stamp", moving)
    got = pp.build(str(path))
    assert (got["available"], got["state"]) == (False, "unreadable")
    assert "changed while" in got["reason"]


def test_a_multi_part_object_is_one_object_node_however_many_meshes_it_has(tmp_path):
    path = sf.bambu_project(tmp_path / "three.3mf", parts=3, items=[("100", sf.tf(10, 10, 0))], plates=[(1, [("100", None)])])
    got = pp.build(str(path))
    assert got["state"] == "ok"
    assert len(got["instances"]) == 3
    assert len({i["object_node"] for i in got["instances"]}) == 1

