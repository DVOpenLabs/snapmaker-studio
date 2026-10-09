"""Repair round 1: each test here fails without the corresponding fix (finding id in the docstring)."""
import hashlib
import json
import re
import struct
import time
import tracemalloc

import pytest

from snapstudio_core import scene, scene_limits as L, units
from tests import scene_fixtures as fx
from tests.test_scene_build import build, codes, node
from tests.test_scene_contract import assert_valid, sub_validator

REV = "ef" * 32


def refuse(path, code):
    with pytest.raises(scene.SceneError) as e:
        scene.build_scene(str(path), REV)
    assert e.value.code == code, (e.value.code, e.value.message)
    return e.value


# ------------------------------------------------------------------ A1: build items with p:path

def test_a1_build_item_p_path_uses_the_referenced_file_not_the_root(tmp_path):
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(5, 5, 0), "/3D/Objects/ext.model")])
    ext = fx.sub_model_xml([fx.cube_object("1", 30)])
    sc = build(fx.three_mf(tmp_path / "p.3mf", root, {"3D/Objects/ext.model": ext}))
    n = node(sc, "b0")
    assert n["resource"] == {"part": "3D/Objects/ext.model", "object_id": "1"}
    assert n["bounds_mm"] == {"min": [5.0, 5.0, 0.0], "max": [35.0, 35.0, 30.0]}        # the 30 mm cube
    assert [m["key"]["part"] for m in sc["meshes"]] == ["3D/Objects/ext.model"]          # the root cube is not substituted


def test_a1_unresolvable_p_path_is_an_error_not_a_fallback_to_the_root(tmp_path):
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", None, "/3D/Objects/missing.model")])
    refuse(fx.three_mf(tmp_path / "a.3mf", root), "UNRESOLVED_REFERENCE")
    ext = fx.sub_model_xml([fx.cube_object("7", 30)])                      # file exists, object 1 does not
    root2 = fx.model_xml([fx.cube_object("1", 10)], [("1", None, "/3D/Objects/ext.model")])
    refuse(fx.three_mf(tmp_path / "b.3mf", root2, {"3D/Objects/ext.model": ext}), "UNRESOLVED_REFERENCE")


def test_a1_same_object_id_in_two_files_is_not_a_repeated_instance(tmp_path):
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(5, 5, 0), "/3D/Objects/ext.model"), ("1", fx.tf(100, 5, 0))])
    ext = fx.sub_model_xml([fx.cube_object("1", 30)])
    sc = build(fx.three_mf(tmp_path / "r.3mf", root, {"3D/Objects/ext.model": ext}))
    assert "REPEATED_INSTANCE_PLACEMENT_UNVERIFIED" not in codes(sc)
    assert node(sc, "b0")["resource"]["part"] == "3D/Objects/ext.model" and node(sc, "b1")["resource"]["part"] == "3D/3dmodel.model"
    twice = fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(5, 5, 0), "/3D/Objects/ext.model"), ("1", fx.tf(100, 5, 0), "/3D/Objects/ext.model")])
    assert "REPEATED_INSTANCE_PLACEMENT_UNVERIFIED" in codes(build(fx.three_mf(tmp_path / "t.3mf", twice, {"3D/Objects/ext.model": ext})))


# ------------------------------------------------------------------ A2: the unit header, read from the real root

CORE = fx.CORE


def _prefixed(xml: str) -> str:
    xml = re.sub(r"<(/?)(model|resources|object|mesh|vertices|vertex|triangles|triangle|components|component|build|item)\b",
                 r"<\1m:\2", xml)
    return xml.replace(f'xmlns="{CORE}"', f'xmlns:m="{CORE}"')


UNIT_DOCS = {
    "prefixed": lambda: _prefixed(fx.model_xml([fx.cube_object("1", 12)], [("1", None)], unit="inch")),
    "long_comment": lambda: fx.model_xml([fx.cube_object("1", 12)], [("1", None)], unit="inch",
                                         prolog='<?xml version="1.0" encoding="UTF-8"?><!-- ' + "x" * 200_000 + ' -->'),
    "pi_and_comments": lambda: fx.model_xml([fx.cube_object("1", 12)], [("1", None)], unit="inch",
                                            prolog='<?xml version="1.0"?><?pi stuff?><!-- c --><?pi2 more?>'),
    "decoy_comment": lambda: fx.model_xml([fx.cube_object("1", 12)], [("1", None)], unit="millimeter",
                                          prolog='<?xml version="1.0"?><!-- <model unit="inch"> -->'),
    "absent": lambda: fx.model_xml([fx.cube_object("1", 12)], [("1", None)]).replace(' unit="millimeter"', ""),
}
EXPECT = {"prefixed": "inch", "long_comment": "inch", "pi_and_comments": "inch", "decoy_comment": "millimeter", "absent": "millimeter"}


@pytest.mark.parametrize("name", sorted(UNIT_DOCS))
def test_a2_the_unit_comes_from_the_real_root_element(tmp_path, name):
    xml = UNIT_DOCS[name]()
    want = EXPECT[name]
    assert units.read_unit(xml.encode()).name == want
    assert units.mm_per_unit(xml.encode()) == units.MM_PER_UNIT[want]
    sc = build(fx.three_mf(tmp_path / f"{name}.3mf", xml))
    assert sc["sources"][0]["unit"] == want                 # the scene parser and the shared helper agree
    b = node(sc, "b0")["bounds_mm"]
    assert b["max"][0] == pytest.approx(12 * units.MM_PER_UNIT[want], abs=1e-4)


def test_a2_legacy_readers_see_the_same_unit_through_a_long_preamble(tmp_path):
    from snapstudio_core.intelligence import project_info
    xml = UNIT_DOCS["long_comment"]()
    path = str(fx.three_mf(tmp_path / "l.3mf", xml))
    assert project_info(path)["dimensions_mm"] == {"x": 304.8, "y": 304.8, "z": 304.8}
    decoy = str(fx.three_mf(tmp_path / "d.3mf", UNIT_DOCS["decoy_comment"]()))
    assert project_info(decoy)["dimensions_mm"] == {"x": 12.0, "y": 12.0, "z": 12.0}


def test_a2_an_unrecognised_unit_is_not_the_same_as_an_absent_one():
    absent = units.read_unit(b'<model xmlns="x"/>')
    yard = units.read_unit(b'<model xmlns="x" unit="yard"/>')
    assert absent.recognized and not absent.declared and absent.factor == 1.0
    assert not yard.recognized and yard.declared and yard.name == "yard" and yard.factor == 1.0   # legacy fallback, flagged
    assert units.unit_of(b'<model xmlns="x" unit="yard"/>') == ("yard", None)


# ------------------------------------------------------------------ A4 / D4: metadata present but unmatched is never a printable part

def test_a4_prusa_attribute_order_does_not_matter(tmp_path):
    vols = [(0, 11, "ModelPart"), (12, 23, "ParameterModifier")]
    normal = build(fx.prusa_project(tmp_path / "a.3mf", volumes=vols))
    swapped = build(fx.prusa_project(tmp_path / "b.3mf", volumes=vols, last_first=True))
    assert swapped["meshes"][0]["volumes"] == normal["meshes"][0]["volumes"]
    assert [v["role"] for v in swapped["meshes"][0]["volumes"]] == ["part", "modifier"]
    assert node(swapped, "b0")["has_non_part_volumes"] is True


def test_a4_bambu_part_missing_from_the_settings_is_unknown_not_printable(tmp_path):
    path = fx.bambu_project(tmp_path / "m.3mf", parts=2, items=[("100", fx.tf(10, 10, 0))], plates=[(1, [("100", 0)])],
                            origins=[(0, 0, 0), (500, 0, 0)], omit_parts=(2,))
    sc = build(path)
    missing = node(sc, "b0.c1")
    assert missing["role_context"] == "unknown" and missing["printable"] is None and missing["bounds_mm"] is None
    lim = next(l for l in sc["limitations"] if l["code"] == "UNKNOWN_VOLUME_ROLE")
    assert lim["target_ids"] == ["b0.c1"] and sc["status"] == "partial"
    assert node(sc, "b0")["bounds_mm"] == {"min": [10.0, 10.0, 0.0], "max": [20.0, 20.0, 10.0]}   # the unknown part does not count
    assert node(sc, "b0.c1")["finding_ids"] == [] and sc["findings"] == []


def test_a4_an_object_with_no_metadata_at_all_keeps_the_synthetic_part(tmp_path):
    sc = build(fx.plain_cube_3mf(tmp_path / "p.3mf"))
    assert sc["meshes"][0]["volumes"][0]["role"] == "part" and node(sc, "b0")["role_context"] is None


# ------------------------------------------------------------------ A5: roles follow the traversal context

def _shared_project(tmp_path, roles):
    sub = fx.sub_model_xml([fx.cube_object("1", 10)])
    comp = [("1", "/3D/Objects/o.model", None)]
    root = fx.model_xml([fx.composite_object("100", comp), fx.composite_object("101", comp)],
                        [("100", fx.tf(10, 10, 0)), ("101", fx.tf(60, 10, 0))])
    settings = fx.model_settings_xml({"100": [("1", roles[0])], "101": [("1", roles[1])]}, [(1, [("100", 0), ("101", 0)])])
    return fx.three_mf(tmp_path / "s.3mf", root, {"3D/Objects/o.model": sub, "Metadata/model_settings.config": settings})


def test_a5_a_shared_mesh_keeps_each_use_s_role(tmp_path):
    sc = build(_shared_project(tmp_path, ("negative_part", "normal_part")))
    assert len(sc["meshes"]) == 1                                         # one mesh, two uses
    neg, part = node(sc, "b0.c0"), node(sc, "b1.c0")
    assert (neg["role_context"], neg["printable"], neg["bounds_mm"]) == ("negative", False, None)
    assert (part["role_context"], part["printable"]) == ("part", True)
    assert part["bounds_mm"]["min"] == [60.0, 10.0, 0.0]
    flipped = build(_shared_project(tmp_path, ("normal_part", "modifier_part")))
    assert (node(flipped, "b0.c0")["role_context"], node(flipped, "b1.c0")["role_context"]) == ("part", "modifier")


def test_a5_a_negative_part_over_an_assembly_applies_to_everything_beneath(tmp_path):
    sub = fx.sub_model_xml([fx.cube_object("1", 10), fx.composite_object("2", [("1", None, None), ("1", None, fx.tf(20, 0, 0))])])
    root = fx.model_xml([fx.composite_object("100", [("2", "/3D/Objects/o.model", None)])], [("100", fx.tf(10, 10, 0))])
    settings = fx.model_settings_xml({"100": [("2", "negative_part")]}, [(1, [("100", 0)])])
    sc = build(fx.three_mf(tmp_path / "a.3mf", root, {"3D/Objects/o.model": sub, "Metadata/model_settings.config": settings}))
    assert [n["id"] for n in sc["nodes"]] == ["b0", "b0.c0", "b0.c0.c0", "b0.c0.c1"]
    for nid in ("b0.c0", "b0.c0.c0", "b0.c0.c1"):
        n = node(sc, nid)
        assert n["role_context"] == "negative" and n["printable"] is False and n["bounds_mm"] is None and n["has_non_part_volumes"]
    assert node(sc, "b0")["printable"] is False and node(sc, "b0")["bounds_mm"] is None
    assert sc["findings"] == []


# ------------------------------------------------------------------ A7: the response cap never allocates the whole body first

def test_a7_part_names_longer_than_the_schema_are_refused_before_they_are_placed(tmp_path):
    name = "3D/Objects/" + "n" * 300 + ".model"
    sub = fx.sub_model_xml([fx.cube_object("1", 10)])
    root = fx.model_xml([fx.composite_object("9", [("1", "/" + name, fx.tf(i % 50, i // 50, 0)) for i in range(2000)])], [("9", None)])
    path = fx.three_mf(tmp_path / "long.3mf", root, {name: sub})
    tracemalloc.start()
    err = refuse(path, "LIMIT_EXCEEDED")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert "part name" in err.message and peak < 50 * 1024 * 1024


def test_a7_part_names_at_the_limit_still_yield_a_schema_valid_scene(tmp_path):
    name = "3D/Objects/" + "n" * (L.MAX_PART_NAME_LENGTH - len("3D/Objects/.model")) + ".model"
    assert len(name) == L.MAX_PART_NAME_LENGTH
    sub = fx.sub_model_xml([fx.cube_object("1", 10)])
    root = fx.model_xml([fx.composite_object("9", [("1", "/" + name, fx.tf(i % 50, i // 50, 0)) for i in range(600)])], [("9", None)])
    sc = build(fx.three_mf(tmp_path / "ok.3mf", root, {name: sub}))
    assert sc["counts"]["nodes"] == 601 and len(scene.serialize(sc)) <= L.MAX_RESPONSE_BYTES


def test_a7_serializer_checks_the_cap_while_building_and_never_dumps_the_whole_body(tmp_path, monkeypatch):
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(i % 20 * 12, i // 20 * 12, 0)) for i in range(300)])
    sc = scene.build_scene_dict(str(fx.three_mf(tmp_path / "many.3mf", root)), REV)
    full = len(json.dumps(sc, separators=(",", ":")))
    assert full > 100_000
    monkeypatch.setattr(L, "MAX_RESPONSE_BYTES", 30_000)
    seen = []
    real = json.dumps

    def spy(value, *a, **k):
        text = real(value, *a, **k)
        seen.append(len(text))
        return text
    monkeypatch.setattr(scene.json, "dumps", spy)
    with pytest.raises(scene.SceneError) as e:
        scene.serialize(sc)
    assert e.value.code == "LIMIT_EXCEEDED"
    assert max(seen) < 30_000 and sum(seen) < 30_000 + 5_000            # stopped one element past the cap
    monkeypatch.undo()
    size = len(scene.serialize(sc))
    monkeypatch.setattr(L, "MAX_RESPONSE_BYTES", size)
    assert len(scene.serialize(sc)) == size                              # the accounting is exact
    monkeypatch.setattr(L, "MAX_RESPONSE_BYTES", size - 1)
    with pytest.raises(scene.SceneError):
        scene.serialize(sc)


# ------------------------------------------------------------------ A8 / D3: parse-time memory bounds cover every element

def test_a8_hundreds_of_thousands_of_unused_objects_are_rejected_early(tmp_path):
    objects = "".join(f'<object id="{i}"/>' for i in range(2, 300_002))
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", None)]).replace("</resources>", objects + "</resources>")
    t = time.monotonic()
    err = refuse(fx.three_mf(tmp_path / "objs.3mf", root), "LIMIT_EXCEEDED")
    assert "objects" in err.message and time.monotonic() - t < 10


def test_d3_junk_elements_are_capped_and_memory_stays_bounded(tmp_path):
    junk = "<x/>" * 2_000_000                                          # 8 MB of unknown elements
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", None)]).replace("</resources>", junk + "</resources>")
    path = fx.three_mf(tmp_path / "junk.3mf", root)
    tracemalloc.start()
    err = refuse(path, "LIMIT_EXCEEDED")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert "elements" in err.message and peak <= 300 * 1024 * 1024


# ------------------------------------------------------------------ A9: STL is decoded incrementally

def _stl_with_header(path, n):
    path.write_bytes(b"\0" * 80 + struct.pack("<I", n) + b"\0" * (50 * n))
    return path


def test_a9_an_oversize_binary_header_is_rejected_before_any_triangle_is_decoded(tmp_path, monkeypatch):
    from snapstudio_core import stl_io
    path = _stl_with_header(tmp_path / "big.stl", L.MAX_PARSED_TRIANGLES + 1)
    monkeypatch.setattr(stl_io, "_decode_binary_batch", lambda *a: pytest.fail("decoded before the header was judged"))
    err = refuse(path, "LIMIT_EXCEEDED")
    assert f"{L.MAX_PARSED_TRIANGLES + 1:,}" in err.message and f"{L.MAX_PARSED_TRIANGLES:,}" in err.message


def test_a9_cancel_is_observed_during_a_large_stl_decode(tmp_path):
    path = _stl_with_header(tmp_path / "ok.stl", L.MAX_PARSED_TRIANGLES)

    class C(scene.Control):
        checks = 0
        flagged = None

        def check(self):
            self.checks += 1
            if self.checks == 3:
                self.flagged = time.monotonic()
                raise scene.SceneCancelled()
    c = C()
    with pytest.raises(scene.SceneCancelled):
        scene.build_scene_dict(str(path), REV, c)
    assert c.checks == 3 and time.monotonic() - c.flagged <= 2.0         # inside the decode, not after it


# ------------------------------------------------------------------ A12 / D6: relationships and the byte prescan

@pytest.mark.parametrize("rels", [
    '<Relationships><Relationship Id="x" Type="t" Target="/3D/other.model" TargetMode="External"/></Relationships>',
    f'<r:Relationships xmlns:r="{fx.REL_NS}"><r:Relationship Id="x" Type="t" Target="other.model" TargetMode="External"/></r:Relationships>',
])
def test_a12_external_relationship_is_rejected_whatever_the_namespace(tmp_path, rels):
    path = fx.three_mf(tmp_path / "e.3mf", fx.model_xml([fx.cube_object("1")], [("1", None)]),
                       {"3D/_rels/3dmodel.model.rels": '<?xml version="1.0"?>' + rels})
    err = refuse(path, "INVALID_ARCHIVE")
    assert "external" in err.message


def test_d6_the_byte_prescan_rejects_a_doctype_in_a_config_read_without_an_xml_parser(tmp_path):
    cfg = '<?xml version="1.0"?><!DOCTYPE c [<!ENTITY e "x">]><config/>'
    path = fx.three_mf(tmp_path / "c.3mf", fx.model_xml([fx.cube_object("1")], [("1", None)]), {"Metadata/Slic3r_PE_model.config": cfg})
    arc = scene.Archive(str(path), scene.Control())
    try:
        with pytest.raises(scene.SceneError) as e:
            arc.read_small("Metadata/Slic3r_PE_model.config")
        assert e.value.code == "INVALID_ARCHIVE"
    finally:
        arc.close()


# ------------------------------------------------------------------ A13: ids fit by construction

def test_a13_ids_fit_128_characters_at_the_deepest_allowed_nesting(tmp_path):
    chain = [fx.cube_object("0")] + [fx.composite_object(str(i), [(str(i - 1), None, None)]) for i in range(1, L.MAX_DEPTH)]
    path = fx.three_mf(tmp_path / "deep.3mf", fx.model_xml(chain, [(str(L.MAX_DEPTH - 1), None)]))
    sc = build(path)
    ids = [n["id"] for n in sc["nodes"]]
    assert len(ids) == L.MAX_DEPTH == len(set(ids)) and max(map(len, ids)) <= 128
    assert any("~" in i for i in ids)                                      # long ancestries are digested, not truncated
    assert [n["id"] for n in build(path)["nodes"]] == ids                  # deterministic
    parents = {n["id"]: n["parent_id"] for n in sc["nodes"]}
    assert all(p is None or p in parents for p in parents.values())
    assert node(sc, ids[-1])["instance_ref"]["component_path"] == [0] * (L.MAX_DEPTH - 1)
    assert hashlib.sha256(ids[-1].encode()).hexdigest()                     # (ids are plain strings)


# ------------------------------------------------------------------ D5: schema closure and plate state

def test_d5_error_response_is_closed_and_a_known_plate_needs_an_id():
    err = sub_validator("error_response")
    assert not list(err.iter_errors({"error": "EXPIRED", "message": "x"}))
    assert list(err.iter_errors({"error": "EXPIRED", "message": "x", "extra": 1}))
    plate = sub_validator("plate_ref")
    assert not list(plate.iter_errors({"state": "known", "plate_id": "p1", "source": "plate_config"}))
    assert list(plate.iter_errors({"state": "known", "plate_id": None, "source": "plate_config"}))
    assert not list(plate.iter_errors({"state": "unknown", "plate_id": None, "source": None}))


def test_d5_a_node_on_no_plate_of_a_project_with_plates_gets_no_fit_finding_and_is_partial(tmp_path):
    path = fx.bambu_project(tmp_path / "np.3mf", parts=1, items=[("100", fx.tf(900, 900, 0))], plates=[(1, [])])
    sc = build(path)
    assert node(sc, "b0")["plate"]["state"] == "unknown"
    assert sc["findings"] == [] and sc["status"] == "partial" and "PLATE_MEMBERSHIP_UNKNOWN" in codes(sc)
    on_plate = build(fx.bambu_project(tmp_path / "op.3mf", parts=1, items=[("100", fx.tf(900, 900, 0))], plates=[(1, [("100", 0)])]))
    assert [f["kind"] for f in on_plate["findings"]] == ["placement"]       # with membership proven, the finding returns


# ================================================================== repair round 2

import os


def _config(tmp_path, name, settings_xml, model=None, extra=None):
    root = model or fx.model_xml([fx.cube_object("1", 10)], [("1", None)])
    return fx.three_mf(tmp_path / name, root, dict({"Metadata/model_settings.config": settings_xml}, **(extra or {})))


# ------------------------------------------------------------------ B1: STL kind and bounds

def test_b1_a_large_solid_payload_with_no_newlines_is_rejected_without_allocating_it(tmp_path):
    path = tmp_path / "bomb.stl"
    with open(path, "wb") as fh:
        fh.write(b"solid ")
        for _ in range(64):
            fh.write(b"a" * (1024 * 1024))                                 # 64 MiB, not one newline
    tracemalloc.start()
    t = time.monotonic()
    err = refuse(path, "INVALID_GEOMETRY")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert time.monotonic() - t < 5 and peak < 20 * 1024 * 1024, (peak, err.message)


def test_b1_a_header_over_the_budget_with_trailing_bytes_is_rejected_before_any_decoding(tmp_path, monkeypatch):
    from snapstudio_core import stl_io
    n = L.MAX_PARSED_TRIANGLES + 1
    path = tmp_path / "trail.stl"
    path.write_bytes(b"solid mislabelled binary".ljust(80, b" ") + struct.pack("<I", n) + b"\0" * (50 * 100 + 7))
    monkeypatch.setattr(stl_io, "_decode_binary_batch", lambda *a: pytest.fail("decoded"))
    err = refuse(path, "LIMIT_EXCEEDED")
    assert f"{n:,}" in err.message
    small = tmp_path / "mismatch.stl"
    small.write_bytes(b"\0" * 80 + struct.pack("<I", 10) + b"\0" * 77)    # plausible count, wrong size
    refuse(small, "INVALID_GEOMETRY")


def test_b1_a_cr_only_ascii_stl_is_accepted_like_the_other_readers(tmp_path):
    facet = "facet normal 0 0 0\router loop\rvertex 0 0 0\rvertex 1 0 0\rvertex 0 1 0\rendloop\rendfacet\r"
    path = tmp_path / "cr.stl"
    path.write_bytes(("solid x\r" + facet * 3 + "endsolid\r").encode())
    assert scene.build_scene_dict(str(path), REV)["counts"]["triangles"] == 3
    crlf = tmp_path / "crlf.stl"
    crlf.write_bytes(("solid x\r\n" + facet.replace("\r", "\r\n") * 2 + "endsolid\r\n").encode())
    assert scene.build_scene_dict(str(crlf), REV)["counts"]["triangles"] == 2
    from snapstudio_core import geometry
    assert geometry.load_mesh(str(path)) is not None                       # the legacy loader agrees


def test_b1_an_overlong_ascii_line_is_refused(tmp_path):
    path = tmp_path / "long.stl"
    good = b"facet normal 0 0 0\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\n"
    path.write_bytes(b"solid x\n" + good + b"facet " + b"9" * 5000 + b"\nendsolid\n")
    refuse(path, "INVALID_GEOMETRY")


# ------------------------------------------------------------------ B2: settings, Prusa config and .rels are counted and pruned

JUNK = "<x/>" * 2_000_000                                                   # 8,000,000 bytes: under the 8 MiB part cap


@pytest.mark.parametrize("which", ["bambu", "prusa", "rels"])
def test_b2_millions_of_tiny_elements_in_a_small_part_are_rejected_early(tmp_path, which):
    if which == "bambu":
        path = _config(tmp_path, "b.3mf", "<config>" + JUNK + "</config>")
    elif which == "prusa":
        path = fx.three_mf(tmp_path / "p.3mf", fx.model_xml([fx.cube_object("1", 10)], [("1", None)]),
                           {"Metadata/Slic3r_PE_model.config": "<config>" + JUNK + "</config>"})
    else:
        path = fx.three_mf(tmp_path / "r.3mf", fx.model_xml([fx.cube_object("1", 10)], [("1", None)]),
                           rels=f'<Relationships xmlns="{fx.REL_NS}">' + JUNK + "</Relationships>")
    tracemalloc.start()
    err = refuse(path, "LIMIT_EXCEEDED")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert "elements" in err.message and peak <= 300 * 1024 * 1024


def test_b2_unrecognised_elements_are_released_as_they_complete(tmp_path, monkeypatch):
    calls = []
    real = scene._free
    monkeypatch.setattr(scene, "_free", lambda e: (calls.append(e.tag), real(e))[1])
    junk = "<x/>" * 3000
    scene.build_scene_dict(str(_config(tmp_path, "j.3mf", "<config>" + junk + "</config>")), REV)
    assert sum(1 for t in calls if t == "x") >= 3000
    calls.clear()
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", None)]).replace("</resources>", junk + "</resources>")
    scene.build_scene_dict(str(fx.three_mf(tmp_path / "m.3mf", root)), REV)
    assert sum(1 for t in calls if t.endswith("}x") or t == "x") >= 3000


# ------------------------------------------------------------------ B3: p:path rules

def test_b3_a_relative_build_item_path_is_refused(tmp_path):
    ext = fx.sub_model_xml([fx.cube_object("1", 30)])
    root = fx.model_xml([], [("1", None, "3D/Objects/ext.model")])
    refuse(fx.three_mf(tmp_path / "a.3mf", root, {"3D/Objects/ext.model": ext}), "UNRESOLVED_REFERENCE")
    ok = fx.model_xml([], [("1", None, "/3D/Objects/ext.model")])
    assert scene.build_scene_dict(str(fx.three_mf(tmp_path / "b.3mf", ok, {"3D/Objects/ext.model": ext})), REV)["counts"]["nodes"] == 1


def test_b3_a_relative_component_path_is_refused(tmp_path):
    ext = fx.sub_model_xml([fx.cube_object("1", 30)])
    root = fx.model_xml([fx.composite_object("9", [("1", "3D/Objects/ext.model", None)])], [("9", None)])
    refuse(fx.three_mf(tmp_path / "a.3mf", root, {"3D/Objects/ext.model": ext}), "UNRESOLVED_REFERENCE")


def test_b3_component_paths_are_honoured_only_from_the_root_model(tmp_path):
    leaf = fx.sub_model_xml([fx.cube_object("1", 10)])
    mid = fx.sub_model_xml([fx.composite_object("2", [("1", "/3D/Objects/leaf.model", None)])])
    root = fx.model_xml([fx.composite_object("9", [("2", "/3D/Objects/mid.model", None)])], [("9", None)])
    err = refuse(fx.three_mf(tmp_path / "n.3mf", root, {"3D/Objects/mid.model": mid, "3D/Objects/leaf.model": leaf}),
                 "UNRESOLVED_REFERENCE")
    assert "root model" in err.message


# ------------------------------------------------------------------ B4: duplicate records never silently overwrite

def _two_part_settings(records):
    return ('<?xml version="1.0"?><config>' + records +
            '<plate><metadata key="plater_id" value="1"/><model_instance><metadata key="object_id" value="100"/>'
            '<metadata key="instance_id" value="0"/></model_instance></plate></config>')


def _bambu_one_part(tmp_path, name, settings):
    sub = fx.sub_model_xml([fx.cube_object("1", 10)])
    root = fx.model_xml([fx.composite_object("100", [("1", "/3D/Objects/o.model", None)])], [("100", fx.tf(10, 10, 0))])
    return fx.three_mf(tmp_path / name, root, {"3D/Objects/o.model": sub, "Metadata/model_settings.config": settings})


def test_b4_duplicate_records_that_disagree_make_the_role_unknown(tmp_path):
    neg = '<object id="100"><part id="1" subtype="negative_part"/></object>'
    part = '<object id="100"><part id="1" subtype="normal_part"/></object>'
    both = '<object id="100"><part id="1" subtype="negative_part"/><part id="1" subtype="normal_part"/></object>'
    for name, records in (("objects", neg + part), ("parts", both)):
        sc = build(_bambu_one_part(tmp_path, name + ".3mf", _two_part_settings(records)))
        n = node(sc, "b0.c0")
        assert n["role_context"] == "unknown" and n["printable"] is None
        assert sc["status"] == "partial" and "UNKNOWN_VOLUME_ROLE" in codes(sc) and sc["findings"] == []
    same = build(_bambu_one_part(tmp_path, "same.3mf", _two_part_settings(neg + neg)))
    assert node(same, "b0.c0")["role_context"] == "negative"                  # identical duplicates are fine


# ------------------------------------------------------------------ B5: build objects in another file fail closed

def test_b5_a_negative_part_assembly_in_another_file_is_unknown_and_never_judged(tmp_path):
    a = fx.sub_model_xml([fx.cube_object("1", 10), fx.composite_object("2", [("1", None, None)])])
    root = fx.model_xml([], [("2", fx.tf(900, 100, 0), "/3D/Objects/a.model")])
    settings = fx.model_settings_xml({"2": [("1", "negative_part")]}, [(1, [("2", 0)])])
    sc = build(fx.three_mf(tmp_path / "x.3mf", root, {"3D/Objects/a.model": a, "Metadata/model_settings.config": settings}))
    assert [n["role_context"] for n in sc["nodes"]] == ["unknown", "unknown"]
    assert all(n["printable"] is None for n in sc["nodes"])
    assert sc["status"] == "partial" and "UNKNOWN_VOLUME_ROLE" in codes(sc)
    assert sc["findings"] == []


def test_b5_without_any_settings_a_file_qualified_build_object_is_still_ordinary(tmp_path):
    root = fx.model_xml([], [("1", fx.tf(5, 5, 0), "/3D/Objects/a.model")])
    a = fx.sub_model_xml([fx.cube_object("1", 10)])
    sc = build(fx.three_mf(tmp_path / "plain.3mf", root, {"3D/Objects/a.model": a}))
    assert node(sc, "b0")["printable"] is True and node(sc, "b0")["role_context"] is None


# ------------------------------------------------------------------ B6: plate matching is file-qualified

def test_b6_a_bare_object_id_shared_across_files_cannot_prove_plate_membership(tmp_path):
    ext = fx.sub_model_xml([fx.cube_object("1", 10)])
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(900, 10, 0)), ("1", fx.tf(5, 5, 0), "/3D/Objects/ext.model")])
    settings = fx.model_settings_xml({}, [(1, [("1", 0)])])
    sc = build(fx.three_mf(tmp_path / "s.3mf", root, {"3D/Objects/ext.model": ext, "Metadata/model_settings.config": settings}))
    assert [node(sc, "b0")["plate"]["state"], node(sc, "b1")["plate"]["state"]] == ["ambiguous", "ambiguous"]
    assert all(node(sc, i)["plate"]["plate_id"] is None for i in ("b0", "b1"))
    lim = next(l for l in sc["limitations"] if l["code"] == "PLATE_MEMBERSHIP_UNKNOWN")
    assert set(lim["target_ids"]) == {"b0", "b1"}
    assert sc["findings"] == [] and sc["status"] == "partial"                  # the root cube at X=900 is NOT reported


# ------------------------------------------------------------------ B7: unsupported unit names its nodes

def test_b7_unsupported_unit_lists_the_affected_nodes(tmp_path):
    sub = fx.sub_model_xml([fx.cube_object("1", 10)], unit="yard")
    root = fx.model_xml([fx.composite_object("9", [("1", "/3D/Objects/y.model", None)]), fx.cube_object("2", 10)],
                        [("9", None), ("2", fx.tf(50, 0, 0))])
    sc = build(fx.three_mf(tmp_path / "u.3mf", root, {"3D/Objects/y.model": sub}))
    lim = next(l for l in sc["limitations"] if l["code"] == "UNSUPPORTED_UNIT")
    assert lim["target_ids"] == ["b0.c0"]                                # only the nodes living in the yard part
    assert {s["part"]: s["unit"] for s in sc["sources"]}["3D/Objects/y.model"] == "millimeter"   # the documented fallback
    description = scene.load_schema()["$defs"]["source"]["description"]
    assert "UNSUPPORTED_UNIT" in description and "fallback" in description.lower()


# ------------------------------------------------------------------ B8: the failure wording is pinned

def test_b8_a_failed_move_says_it_kept_no_copy(tmp_path, monkeypatch):
    from snapstudio_core import plate_placement
    path = str(fx.three_mf(tmp_path / "m.3mf", fx.model_xml([fx.cube_object("1", 25.4)], [("1", fx.tf(290.0, 3.0, 0.0))])))
    monkeypatch.setattr(plate_placement, "_rewrite_items", lambda raw, offset_for: (raw, 1))
    monkeypatch.setattr(plate_placement, "verify_only_placement_moved", lambda a, b: {"passed": True, "checks": []})
    res = plate_placement.prepare_placed_copy(path, out_dir=str(tmp_path / "out"))
    assert res["ok"] is False
    assert res["reason"] == ("Studio could not move the objects onto the plate, so it did not keep a copy. "
                             "Open the original in Snapmaker Orca and use Arrange.")


# ------------------------------------------------------------------ B9: id collisions are detected

def test_b9_a_node_id_collision_is_an_internal_error(tmp_path, monkeypatch):
    monkeypatch.setattr(scene.Traversal, "_node_id", staticmethod(lambda ctx, parent, path: "same"))
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", None), ("1", fx.tf(20, 0, 0))])
    refuse(fx.three_mf(tmp_path / "c.3mf", root), "INTERNAL")


# ------------------------------------------------------------------ B10: surviving mutants

def test_b10_an_assembly_role_is_inherited_under_a_root_file_parent_and_the_outer_role_wins(tmp_path):
    root = fx.model_xml([fx.cube_object("1", 10), fx.composite_object("50", [("1", None, None)]),
                         fx.composite_object("100", [("50", None, None)])], [("100", fx.tf(10, 10, 0))])
    settings = fx.model_settings_xml({"100": [("50", "negative_part")], "50": [("1", "normal_part")]}, [(1, [("100", 0)])])
    sc = build(fx.three_mf(tmp_path / "r.3mf", root, {"Metadata/model_settings.config": settings}))
    assert [node(sc, i)["role_context"] for i in ("b0.c0", "b0.c0.c0")] == ["negative", "negative"]
    assert node(sc, "b0.c0.c0")["printable"] is False and sc["findings"] == []


def test_b10_an_unreadable_prusa_range_makes_the_whole_mesh_unknown_and_partial(tmp_path):
    cfg = ('<config><object id="1"><volume firstid="0" lastid="5"><metadata type="volume" key="volume_type" value="ModelPart"/></volume>'
           '<volume firstid="x" lastid="11"><metadata type="volume" key="volume_type" value="ModelPart"/></volume>'
           '</object></config>')
    sc = build(fx.three_mf(tmp_path / "p.3mf", fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(900, 900, 0))]),
                           {"Metadata/Slic3r_PE_model.config": cfg}))
    assert [v["role"] for v in sc["meshes"][0]["volumes"]] == ["unknown"]
    assert node(sc, "b0")["printable"] is None and sc["status"] == "partial" and sc["findings"] == []


def test_b10_binary_stl_is_decoded_in_bounded_batches_with_the_hook_between_them(tmp_path, monkeypatch):
    from snapstudio_core import stl_io
    path = _stl_with_header(tmp_path / "b.stl", 12_000)
    sizes, checks = [], []
    real = stl_io._decode_binary_batch
    monkeypatch.setattr(stl_io, "_decode_binary_batch", lambda raw, *a: (sizes.append(len(raw) // 50), real(raw, *a))[1])
    with open(path, "rb") as fh:
        stl_io.decode_stl_stream(fh, os.path.getsize(path), max_triangles=250_000, max_vertices=300_000,
                                 check=lambda: checks.append(1))
    assert sizes == [5000, 5000, 2000] and len(checks) >= 3


# ================================================================== repair round 3

def _bambu_part_at_900(tmp_path, name, object_xml, plate_extra=""):
    settings = ('<?xml version="1.0"?><config>' + object_xml +
                '<plate><metadata key="plater_id" value="1"/><model_instance><metadata key="object_id" value="100"/>'
                '<metadata key="instance_id" value="0"/></model_instance>' + plate_extra + '</plate></config>')
    sub = fx.sub_model_xml([fx.cube_object("1", 10)])
    root = fx.model_xml([fx.composite_object("100", [("1", "/3D/Objects/o.model", None)])], [("100", fx.tf(900, 10, 0))])
    return fx.three_mf(tmp_path / name, root, {"3D/Objects/o.model": sub, "Metadata/model_settings.config": settings})


@pytest.mark.parametrize("name,obj", [
    ("after", '<object id="100"><part id="1" subtype="negative_part"/><text_info/></object>'),
    ("between", '<object id="100"><part id="1" subtype="negative_part"/><x/><part id="2" subtype="normal_part"/></object>'),
    ("leading", '<object id="100"><x/><y/><part id="1" subtype="negative_part"/><z/></object>'),
])
def test_r3_1_an_unknown_element_next_to_a_part_record_never_changes_its_role(tmp_path, name, obj):
    sc = build(_bambu_part_at_900(tmp_path, f"{name}.3mf", obj))
    n = node(sc, "b0.c0")
    assert n["role_context"] == "negative" and n["printable"] is False
    assert sc["findings"] == []                                    # a negative part is never judged against the bed


def test_r3_1_an_unknown_element_after_a_model_instance_keeps_plate_membership(tmp_path):
    obj = '<object id="100"><part id="1" subtype="normal_part"/></object>'
    sc = build(_bambu_part_at_900(tmp_path, "pl.3mf", obj, plate_extra="<x/><y/>"))
    assert node(sc, "b0")["plate"] == {"state": "known", "plate_id": "p1", "source": "plate_config"}
    assert [f["kind"] for f in sc["findings"]] == ["placement"]    # and the part at X=900 is judged, as before


@pytest.mark.parametrize("junk", ["", "<x/>", "<cut_id/><x/>"])
def test_r3_1_an_unknown_element_after_a_prusa_volume_never_drops_it(tmp_path, junk):
    verts, tris = [], []
    for k in range(2):
        base = len(verts)
        verts += fx.cube_vertices(10.0, (k * 20.0, 0.0, 0.0))
        tris += [(a + base, b + base, c + base) for a, b, c in fx.CUBE_TRIS]
    obj = f'<object id="1" type="model">{fx.mesh_xml(verts, tris)}</object>'
    vol = lambda a, b, vt: f'<volume firstid="{a}" lastid="{b}"><metadata type="volume" key="volume_type" value="{vt}"/></volume>'
    cfg = ('<config><object id="1">' + vol(0, 11, "ModelPart") + junk + vol(12, 23, "NegativeVolume") + junk + "</object>" + junk + "</config>")
    sc = build(fx.three_mf(tmp_path / "p.3mf", fx.model_xml([obj], [("1", fx.tf(900, 100, 0))]),
                           {"Metadata/Slic3r_PE_model.config": cfg}))
    assert [v["role"] for v in sc["meshes"][0]["volumes"]] == ["part", "negative"]
    assert node(sc, "b0")["bounds_mm"]["max"][0] == pytest.approx(910.0)       # the negative cube (to 930) does not count


# ------------------------------------------------------------------ R3-2: every completed element is released

def test_r3_2_relationships_and_namespaced_settings_elements_are_released(tmp_path, monkeypatch):
    seen = []
    real = scene._free
    monkeypatch.setattr(scene, "_free", lambda e: (seen.append(e.tag), real(e))[1])
    rels = f'<Relationships xmlns="{fx.REL_NS}">' + '<Relationship Id="r" Type="t" Target="/a"/>' * 50 + "</Relationships>"
    cfg = '<config xmlns="urn:x">' + "<object/>" * 50 + "</config>"
    path = fx.three_mf(tmp_path / "r.3mf", fx.model_xml([fx.cube_object("1", 10)], [("1", None)]),
                       {"3D/_rels/x.rels": rels, "Metadata/model_settings.config": cfg})
    scene.build_scene_dict(str(path), REV)
    assert seen.count(f"{{{fx.REL_NS}}}Relationship") >= 50
    assert seen.count("{urn:x}object") >= 50


def test_r3_2_hundreds_of_thousands_of_small_records_stay_within_a_memory_gate(tmp_path):
    rels = f'<Relationships xmlns="{fx.REL_NS}">' + '<Relationship Target="/a"/>' * 300_000 + "</Relationships>"
    assert len(rels) < L.CONFIG_PART_BYTES
    cfg = '<config xmlns="urn:x">' + "<object/>" * 880_000 + "</config>"
    assert len(cfg) < L.CONFIG_PART_BYTES
    path = fx.three_mf(tmp_path / "big.3mf", fx.model_xml([fx.cube_object("1", 10)], [("1", None)]),
                       {"3D/_rels/x.rels": rels, "Metadata/model_settings.config": cfg})
    tracemalloc.start()
    sc = scene.build_scene_dict(str(path), REV)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert sc["counts"]["nodes"] == 1 and peak <= 300 * 1024 * 1024


# ------------------------------------------------------------------ R3-3: a present-but-empty p:path is an error

def test_r3_3_an_empty_build_item_path_is_not_treated_as_absent(tmp_path):
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", None, "")])       # object 1 EXISTS in this model
    refuse(fx.three_mf(tmp_path / "i.3mf", root), "UNRESOLVED_REFERENCE")


def test_r3_3_an_empty_component_path_is_not_treated_as_absent(tmp_path):
    root = fx.model_xml([fx.cube_object("1", 10), fx.composite_object("9", [("1", "", None)])], [("9", None)])
    refuse(fx.three_mf(tmp_path / "c.3mf", root), "UNRESOLVED_REFERENCE")


# ------------------------------------------------------------------ R3-4: a part record without an id still means "has metadata"

def test_r3_4_a_part_record_without_an_id_makes_the_object_have_metadata(tmp_path):
    sc = build(_bambu_part_at_900(tmp_path, "noid.3mf", '<object id="100"><part subtype="negative_part"/></object>'))
    n = node(sc, "b0.c0")
    assert n["role_context"] == "unknown" and n["printable"] is None
    assert sc["status"] == "partial" and "UNKNOWN_VOLUME_ROLE" in codes(sc) and sc["findings"] == []
    plain = build(_bambu_part_at_900(tmp_path, "nometa.3mf", '<object id="100"><metadata key="name" value="x"/></object>'))
    assert node(plain, "b0.c0")["role_context"] is None                      # an object with no part records is unchanged


# ------------------------------------------------------------------ R3-5: the root unit reaches external build items

def test_r3_5_a_bad_root_unit_names_the_external_build_item_nodes(tmp_path):
    ext = fx.sub_model_xml([fx.cube_object("1", 10)])
    root = fx.model_xml([], [("1", fx.tf(5, 5, 0), "/3D/Objects/e.model")], unit="yard")
    sc = build(fx.three_mf(tmp_path / "y.3mf", root, {"3D/Objects/e.model": ext}))
    lim = next(l for l in sc["limitations"] if l["code"] == "UNSUPPORTED_UNIT")
    assert lim["target_ids"] == ["b0"]                                       # its translation is in the unrecognized unit
    assert sc["findings"] == []


# ------------------------------------------------------------------ R3-6: a non-ASCII solid name is text

def test_r3_6_an_ascii_stl_with_a_non_ascii_name_loads(tmp_path):
    facet = "facet normal 0 0 0\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\n"
    path = tmp_path / "wuerfel.stl"
    path.write_bytes(("solid Würfel_größe\n" + facet * 3 + "endsolid Würfel_größe\n").encode("utf-8"))
    assert scene.build_scene_dict(str(path), REV)["counts"]["triangles"] == 3
    binary = tmp_path / "bin.stl"                                            # high bytes that are NOT UTF-8 stay binary
    binary.write_bytes(bytes(range(128, 256)) * 3 + struct.pack("<I", L.MAX_PARSED_TRIANGLES + 1) + b"\xff" * 10)
    refuse(binary, "LIMIT_EXCEEDED")
