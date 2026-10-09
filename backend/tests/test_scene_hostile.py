"""scene/1 against hostile and broken input: every case ends in a clear, coded refusal -- never a
crash, a hang, a partial scene or a silently shortened one."""
import time
import zipfile

import pytest

from snapstudio_core import scene, scene_limits as L
from tests import scene_fixtures as fx

REV = "cd" * 32


def refuse(path, code):
    with pytest.raises(scene.SceneError) as e:
        scene.build_scene(str(path), REV)
    assert e.value.code == code, (e.value.code, e.value.message)
    return e.value


def model(objects=None, items=None, **kw):
    return fx.model_xml(objects or [fx.cube_object("1")], items or [("1", None)], **kw)


# ------------------------------------------------------------------------------ format

def test_wrong_extension_and_not_an_archive(tmp_path):
    p = tmp_path / "x.obj"
    p.write_bytes(b"v 0 0 0")
    refuse(p, "UNSUPPORTED_FORMAT")
    q = tmp_path / "x.3mf"
    q.write_bytes(b"this is not a zip file at all" * 10)
    refuse(q, "INVALID_ARCHIVE")


def test_missing_root_model_and_unresolved_references(tmp_path):
    refuse(fx.write_zip(tmp_path / "a.3mf", {"_rels/.rels": fx.rels_xml()}), "UNRESOLVED_REFERENCE")
    missing_file = model([fx.composite_object("5", [("1", "/3D/Objects/nope.model", None)])], [("5", None)])
    refuse(fx.three_mf(tmp_path / "b.3mf", missing_file), "UNRESOLVED_REFERENCE")
    missing_obj = model([fx.composite_object("5", [("77", None, None)])], [("5", None)])
    refuse(fx.three_mf(tmp_path / "c.3mf", missing_obj), "UNRESOLVED_REFERENCE")
    missing_item = model([fx.cube_object("1")], [("42", None)])
    refuse(fx.three_mf(tmp_path / "d.3mf", missing_item), "UNRESOLVED_REFERENCE")


# ------------------------------------------------------------------------------ archive structure

@pytest.mark.parametrize("name", ["../evil.model", "/abs.model", "a/../../b.model", "..\\win.model", "C:/x.model",
                                  "a/\x01b"])
def test_traversal_looking_entry_names_are_rejected(tmp_path, name):
    entries = {"_rels/.rels": fx.rels_xml(), "3D/3dmodel.model": model(), name: "x"}
    refuse(fx.write_zip(tmp_path / "t.3mf", entries), "INVALID_ARCHIVE")


@pytest.mark.parametrize("second", ["3d/3DMODEL.model", "3D\\3dmodel.model", "3D//3dmodel.model", "./3D/3dmodel.model"])
def test_colliding_normalized_names_are_rejected(tmp_path, second):
    import warnings
    entries = {"_rels/.rels": fx.rels_xml(), "3D/3dmodel.model": model(), second: model()}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        path = fx.write_zip(tmp_path / "c.3mf", entries)
    refuse(path, "INVALID_ARCHIVE")


def test_exact_duplicate_entry_names_are_rejected(tmp_path):
    import warnings
    path = tmp_path / "dup.3mf"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
            z.writestr("_rels/.rels", fx.rels_xml())
            z.writestr("3D/3dmodel.model", model())
            z.writestr("3D/3dmodel.model", model())
    refuse(path, "INVALID_ARCHIVE")


def test_external_relationships_are_rejected_anywhere(tmp_path):
    ext = '<Relationship Id="x" Type="http://example.invalid/t" Target="http://example.invalid/a.model" TargetMode="External"/>'
    refuse(fx.three_mf(tmp_path / "a.3mf", model(), rels=fx.rels_xml(extra=ext)), "INVALID_ARCHIVE")
    rels3d = f'<?xml version="1.0"?><Relationships xmlns="{fx.REL_NS}">{ext}</Relationships>'
    refuse(fx.three_mf(tmp_path / "b.3mf", model(), {"3D/_rels/3dmodel.model.rels": rels3d}), "INVALID_ARCHIVE")


def test_references_that_escape_the_package_are_rejected(tmp_path):
    refuse(fx.three_mf(tmp_path / "a.3mf", model(), rels=fx.rels_xml(target="../../etc/passwd")), "INVALID_ARCHIVE")
    escaping = model([fx.composite_object("5", [("1", "/../../x.model", None)])], [("5", None)])
    refuse(fx.three_mf(tmp_path / "b.3mf", escaping), "INVALID_ARCHIVE")


def test_relative_and_rooted_relationship_targets_resolve_but_urls_do_not(tmp_path):
    ok = scene.build_scene_dict(str(fx.three_mf(tmp_path / "rel.3mf", model(), rels=fx.rels_xml(target="3D/3dmodel.model"))), REV)
    assert ok["counts"]["nodes"] == 1
    for target in ("http://example.invalid/a.model", "file:///C:/x.model", "C:/x.model", "ftp://h/x"):
        refuse(fx.three_mf(tmp_path / "url.3mf", model(), rels=fx.rels_xml(target=target)), "INVALID_ARCHIVE")


def test_only_the_needed_parts_are_ever_read(tmp_path):
    big = "x" * (3 * 1024 * 1024)
    path = fx.three_mf(tmp_path / "ok.3mf", model(), {"Metadata/thumbnail.png": big, "Metadata/plate_1.gcode": big,
                                                       "Metadata/project_settings.config": big})
    arcs = []
    real = scene.Archive.__init__

    def spy(self, *a, **k):
        real(self, *a, **k)
        arcs.append(self)
    scene.Archive.__init__ = spy
    try:
        scene.build_scene(str(path), REV)
    finally:
        scene.Archive.__init__ = real
    assert arcs[0].total_read < 4096          # thumbnails, G-code and project settings were never read


# ------------------------------------------------------------------------------ XML hardening

BILLION = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
           "<model>&b;</model>")


def test_dtd_and_entity_declarations_are_rejected_before_parsing(tmp_path):
    refuse(fx.three_mf(tmp_path / "a.3mf", BILLION), "INVALID_ARCHIVE")
    mixed = model(prolog='<?xml version="1.0"?><!DocType model [<!EnTiTy x "y">]>')
    refuse(fx.three_mf(tmp_path / "b.3mf", mixed), "INVALID_ARCHIVE")
    external = model(prolog='<?xml version="1.0"?><!DOCTYPE model SYSTEM "http://example.invalid/x.dtd">')
    refuse(fx.three_mf(tmp_path / "c.3mf", external), "INVALID_ARCHIVE")
    # the same refusal for the .rels and the settings parts
    refuse(fx.three_mf(tmp_path / "d.3mf", model(), rels=BILLION), "INVALID_ARCHIVE")
    settings = '<?xml version="1.0"?><!DOCTYPE c [<!ENTITY e "x">]><config/>'
    refuse(fx.three_mf(tmp_path / "e.3mf", model(), {"Metadata/model_settings.config": settings}), "INVALID_ARCHIVE")


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-32"])
def test_utf16_doctype_bomb_is_rejected_by_encoding_before_parsing(tmp_path, encoding):
    bomb = BILLION.replace("<model>", f'<model xmlns="{fx.CORE}">')
    for with_bom in (True, False):
        raw = bomb.encode(encoding)
        if not with_bom and raw[:2] in (b"\xff\xfe", b"\xfe\xff") or (not with_bom and raw[:4] in (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
            raw = raw[2:] if encoding != "utf-32" else raw[4:]
        path = fx.write_zip(tmp_path / f"u-{encoding}-{with_bom}.3mf",
                            {"_rels/.rels": fx.rels_xml(), "3D/3dmodel.model": raw})
        err = refuse(path, "INVALID_ARCHIVE")
        assert "UTF-8" in err.message


def test_declared_non_utf8_encoding_is_rejected(tmp_path):
    xml = model(prolog='<?xml version="1.0" encoding="UTF-16"?>')
    refuse(fx.three_mf(tmp_path / "a.3mf", xml), "INVALID_ARCHIVE")
    ok = model(prolog='\ufeff<?xml version="1.0" encoding="utf-8"?>')
    scene.build_scene(str(fx.three_mf(tmp_path / "b.3mf", ok.encode("utf-8"))), REV)    # UTF-8 with BOM is fine


def test_parser_level_doctype_check_is_a_second_line_of_defence(tmp_path, monkeypatch):
    path = fx.three_mf(tmp_path / "x.3mf", BILLION.replace("<model>", f'<model xmlns="{fx.CORE}">'))
    original = scene.Archive.open
    monkeypatch.setattr(scene.Archive, "open", lambda self, name, kind, scan=True: original(self, name, kind, scan=False))
    err = refuse(path, "INVALID_ARCHIVE")
    assert "DTD" in err.message


def test_malformed_xml_is_a_clean_refusal(tmp_path):
    refuse(fx.three_mf(tmp_path / "a.3mf", "<model><unclosed></model>"), "INVALID_ARCHIVE")
    refuse(fx.three_mf(tmp_path / "b.3mf", "<notamodel/>"), "INVALID_ARCHIVE")
    refuse(fx.three_mf(tmp_path / "c.3mf", ""), "INVALID_ARCHIVE")


# ------------------------------------------------------------------------------ geometry validation

def _mesh_model(vertices, triangles, transform=None):
    obj = f'<object id="1" type="model">{fx.mesh_xml(vertices, triangles)}</object>'
    return fx.model_xml([obj], [("1", transform)])


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "abc", "", "1e999"])
def test_non_finite_or_invalid_coordinates(tmp_path, bad):
    v = [(0, 0, 0), (1, 0, 0), (0, bad, 0)]
    refuse(fx.three_mf(tmp_path / "v.3mf", _mesh_model(v, [(0, 1, 2)])), "INVALID_GEOMETRY")


def test_coordinate_out_of_range(tmp_path):
    refuse(fx.three_mf(tmp_path / "v.3mf", _mesh_model([(0, 0, 0), (1, 0, 0), (0, 1e30, 0)], [(0, 1, 2)])), "INVALID_GEOMETRY")


@pytest.mark.parametrize("tri", [(0, 1, 3), (0, 1, 99999999999), (0, -1, 2)])
def test_invalid_triangle_indices(tmp_path, tri):
    refuse(fx.three_mf(tmp_path / "t.3mf", _mesh_model([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [tri])), "INVALID_GEOMETRY")


def test_missing_attributes_and_empty_meshes(tmp_path):
    body = ('<object id="1"><mesh><vertices><vertex x="0" y="0"/></vertices><triangles/></mesh></object>')
    refuse(fx.three_mf(tmp_path / "a.3mf", fx.model_xml([body], [("1", None)])), "INVALID_GEOMETRY")
    empty = '<object id="1"><mesh><vertices/><triangles/></mesh></object>'
    refuse(fx.three_mf(tmp_path / "b.3mf", fx.model_xml([empty], [("1", None)])), "INVALID_GEOMETRY")
    nothing = '<object id="1"/>'
    refuse(fx.three_mf(tmp_path / "c.3mf", fx.model_xml([nothing], [("1", None)])), "INVALID_GEOMETRY")


@pytest.mark.parametrize("transform", ["1 0 0 0 1 0 0 0 1 0 0 nan", "1 0 0 0 1 0 0 0 1 0 0 inf", "1 0 0 0 1 0 0 0 1 0 0",
                                       "a b c d e f g h i j k l", "1 0 0 0 1 0 0 0 1 0 0 0 0"])
def test_invalid_transforms(tmp_path, transform):
    refuse(fx.three_mf(tmp_path / "x.3mf", model(items=[("1", transform)])), "INVALID_GEOMETRY")


def test_transform_overflow_in_composition_is_refused(tmp_path):
    big = "1e200 0 0 0 1e200 0 0 0 1e200 0 0 0"
    objs = [fx.cube_object("1"), fx.composite_object("2", [("1", None, big)]), fx.composite_object("3", [("2", None, big)])]
    refuse(fx.three_mf(tmp_path / "o.3mf", fx.model_xml(objs, [("3", None)])), "INVALID_GEOMETRY")


def test_component_cycles_and_duplicate_ids(tmp_path):
    cyc = [fx.composite_object("1", [("2", None, None)]), fx.composite_object("2", [("1", None, None)])]
    refuse(fx.three_mf(tmp_path / "c.3mf", fx.model_xml(cyc, [("1", None)])), "INVALID_ARCHIVE")
    selfref = [fx.composite_object("1", [("1", None, None)])]
    refuse(fx.three_mf(tmp_path / "s.3mf", fx.model_xml(selfref, [("1", None)])), "INVALID_ARCHIVE")
    dup = [fx.cube_object("1"), fx.cube_object("1")]
    refuse(fx.three_mf(tmp_path / "d.3mf", fx.model_xml(dup, [("1", None)])), "INVALID_ARCHIVE")
    both = '<object id="1"><mesh><vertices><vertex x="0" y="0" z="0"/></vertices><triangles><triangle v1="0" v2="0" v3="0"/></triangles></mesh><components><component objectid="1"/></components></object>'
    refuse(fx.three_mf(tmp_path / "b.3mf", fx.model_xml([both], [("1", None)])), "INVALID_ARCHIVE")


# ------------------------------------------------------------------------------ budgets (never truncate)

def test_zip_bomb_is_refused_without_reading_it(tmp_path):
    path = tmp_path / "bomb.3mf"
    head = f'<?xml version="1.0"?><model unit="millimeter" xmlns="{fx.CORE}"><resources>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("_rels/.rels", fx.rels_xml())
        z.writestr("3D/3dmodel.model", head + " " * (40 * 1024 * 1024) + "</resources><build/></model>")
    assert path.stat().st_size < 200_000
    t = time.monotonic()
    refuse(path, "LIMIT_EXCEEDED")
    assert time.monotonic() - t < 2.0


def test_total_expansion_budget_is_metered_while_reading(tmp_path, monkeypatch):
    sub = fx.sub_model_xml([fx.cube_object("1")])
    root = model([fx.composite_object("9", [("1", "/3D/Objects/a.model", None)])], [("9", None)])
    path = fx.three_mf(tmp_path / "m.3mf", root, {"3D/Objects/a.model": sub})
    scene.build_scene(str(path), REV)
    monkeypatch.setattr(L, "ARCHIVE_EXPANSION_BYTES", 1500)
    refuse(path, "LIMIT_EXCEEDED")
    monkeypatch.setattr(L, "ARCHIVE_EXPANSION_BYTES", 128 * 1024 * 1024)
    monkeypatch.setattr(L, "MODEL_XML_BYTES", 1000)
    refuse(path, "LIMIT_EXCEEDED")


def test_entry_count_and_part_count_budgets(tmp_path, monkeypatch):
    path = fx.three_mf(tmp_path / "e.3mf", model(), {f"x/{i}.txt": "a" for i in range(20)})
    monkeypatch.setattr(L, "ARCHIVE_MAX_ENTRIES", 10)
    refuse(path, "LIMIT_EXCEEDED")


@pytest.mark.parametrize("limit,value", [("MAX_PARSED_TRIANGLES", 11), ("MAX_VERTICES", 7)])
def test_triangle_and_vertex_budgets_are_enforced_during_parsing(tmp_path, monkeypatch, limit, value):
    path = fx.plain_cube_3mf(tmp_path / "c.3mf")
    monkeypatch.setattr(L, limit, value)
    refuse(path, "LIMIT_EXCEEDED")


def test_refusal_names_the_triangle_count_and_the_limit(tmp_path, monkeypatch):
    path = fx.big_grid_3mf(tmp_path / "g.3mf", 400)
    monkeypatch.setattr(L, "MAX_PARSED_TRIANGLES", 100)
    err = refuse(path, "LIMIT_EXCEEDED")
    assert "101" in err.message and "100" in err.message
    monkeypatch.undo()
    stl = fx.binary_stl(tmp_path / "c.stl")
    monkeypatch.setattr(L, "MAX_PARSED_TRIANGLES", 11)
    assert "12" in refuse(stl, "LIMIT_EXCEEDED").message


def test_rendered_triangles_count_every_repetition(tmp_path, monkeypatch):
    path = fx.three_mf(tmp_path / "r.3mf", fx.model_xml([fx.cube_object("1")], [("1", fx.tf(i * 20, 0, 0)) for i in range(5)]))
    monkeypatch.setattr(L, "MAX_RENDERED_TRIANGLES", 59)           # 5 x 12 = 60
    refuse(path, "LIMIT_EXCEEDED")
    monkeypatch.setattr(L, "MAX_RENDERED_TRIANGLES", 60)
    assert scene.build_scene_dict(str(path), REV)["counts"]["rendered_triangles"] == 60


def test_node_and_depth_budgets(tmp_path, monkeypatch):
    path = fx.three_mf(tmp_path / "n.3mf", fx.model_xml([fx.cube_object("1")], [("1", fx.tf(i * 20, 0, 0)) for i in range(5)]))
    monkeypatch.setattr(L, "MAX_NODES", 4)
    refuse(path, "LIMIT_EXCEEDED")
    chain = [fx.cube_object("0")] + [fx.composite_object(str(i), [(str(i - 1), None, None)]) for i in range(1, 70)]
    deep = fx.three_mf(tmp_path / "d.3mf", fx.model_xml(chain, [("69", None)]))
    refuse(deep, "LIMIT_EXCEEDED")
    monkeypatch.setattr(L, "MAX_NODES", 2000)
    shallow = fx.three_mf(tmp_path / "s.3mf", fx.model_xml(chain[:60], [("59", None)]))
    assert scene.build_scene_dict(str(shallow), REV)["counts"]["nodes"] == 60


def test_whole_body_cap_applies_to_the_exact_bytes(tmp_path, monkeypatch):
    path = fx.plain_cube_3mf(tmp_path / "c.3mf")
    size = len(scene.build_scene(str(path), REV))
    monkeypatch.setattr(L, "MAX_RESPONSE_BYTES", size)
    assert len(scene.build_scene(str(path), REV)) == size
    monkeypatch.setattr(L, "MAX_RESPONSE_BYTES", size - 1)
    refuse(path, "LIMIT_EXCEEDED")


def test_geometry_preflight_rejects_before_any_encoding(tmp_path, monkeypatch):
    path = fx.plain_cube_3mf(tmp_path / "c.3mf")
    monkeypatch.setattr(L, "MAX_RESPONSE_BYTES", 100)
    monkeypatch.setattr(scene, "_encode_f32", lambda *a: pytest.fail("encoded before the size check"))
    refuse(path, "LIMIT_EXCEEDED")


def test_stl_budgets(tmp_path, monkeypatch):
    stl = fx.binary_stl(tmp_path / "c.stl")
    monkeypatch.setattr(L, "MAX_PARSED_TRIANGLES", 11)
    refuse(stl, "LIMIT_EXCEEDED")
    monkeypatch.undo()
    text = tmp_path / "t.stl"
    text.write_text("solid x\n" + "facet normal 0 0 0\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\n" * 5 + "endsolid\n")
    assert scene.build_scene_dict(str(text), REV)["counts"]["triangles"] == 5
    monkeypatch.setattr(L, "MAX_PARSED_TRIANGLES", 4)
    err = refuse(text, "LIMIT_EXCEEDED")                       # ASCII is line-streamed with a running counter
    assert "5" in err.message and "4" in err.message
    garbage = tmp_path / "g.stl"
    garbage.write_bytes(b"not an stl at all" * 20)
    monkeypatch.undo()
    refuse(garbage, "INVALID_GEOMETRY")


# ------------------------------------------------------------------------------ cooperative interruption

class CountingControl(scene.Control):
    def __init__(self, cancel_at=None):
        self.checks, self.cancel_at = 0, cancel_at

    def check(self):
        self.checks += 1
        if self.cancel_at is not None and self.checks >= self.cancel_at:
            raise scene.SceneCancelled()


def test_cancel_is_observed_inside_parsing_and_encoding(tmp_path):
    path = fx.big_grid_3mf(tmp_path / "big.3mf", 30_000)
    full = CountingControl()
    scene.build_scene_dict(str(path), REV, full)
    assert full.checks > 100                                  # checked far more often than once per phase
    for at in (3, full.checks // 2, full.checks - 2):
        c = CountingControl(cancel_at=at)
        with pytest.raises(scene.SceneCancelled):
            scene.build_scene_dict(str(path), REV, c)
        assert c.checks == at                                   # stops at the first check after the flag


def test_deadline_is_a_timeout_not_a_hang(tmp_path):
    path = fx.big_grid_3mf(tmp_path / "big.3mf", 30_000)

    class Late(scene.Control):
        def check(self):
            raise scene.SceneTimeout()
    with pytest.raises(scene.SceneTimeout):
        scene.build_scene_dict(str(path), REV, Late())
