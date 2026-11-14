"""input -> inspect -> Prepare -> exported project, for the creative paths Prepare can vouch for.

Evidence label: fixture-tested. Archives are SYNTHETIC, built from the exporters' documented shape (see
tests/fixtures/creative/PROVENANCE.md); no genuine DitherForge or Kromacut export was available. The real
Prepare service runs; Snapmaker Orca, slicers and printers are not involved.

Why two shapes are covered and one is refused:
  * Kromacut's exporter puts every colour layer in the root model and builds its assembly from components
    that carry no p:path. That is valid 3MF Core. Studio's validator used to look for mesh objects only in
    p:path files and so refused it; it now also counts mesh objects the root model defines.
  * DitherForge's Bambu path writes outer object 2 -> component objectid 1 -> part id 1, and Prepare accepts it.
  * DitherForge's generic path writes `<part id="1">` under a component whose objectid is 2 or more, so the
    part ids do not match the component ids. Studio's check is unchanged and still refuses it.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

from snapstudio_api import ext_routes, routes_creative
from snapstudio_core import multipart

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "creative"))
from zip_factory import make_ditherforge, make_ditherforge_bambu, make_kromacut  # noqa: E402


class FakeHandler:
    def __init__(self):
        self.sent = []

    def _send(self, code, obj):
        self.sent.append((code, obj))


def call(route, data):
    handler = FakeHandler()
    assert ext_routes.dispatch(handler, route, data) is True
    return handler.sent[0]


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    target = tmp_path / "studio-data"
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(target))
    return target


def write(tmp_path, blob, name="project.3mf"):
    folder = tmp_path / "src"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(blob)
    return path


def members(path):
    with zipfile.ZipFile(path) as archive:
        return {n: archive.read(n) for n in archive.namelist() if not n.endswith("/")}


def prepare(tmp_path, data_dir, blob):
    """Run the whole journey; return (inspect body, prepare body, source path, exported members)."""
    src = write(tmp_path, blob)
    before = hashlib.sha256(blob).hexdigest()
    code, inspected = call("/creative/inspect", {"path": str(src)})
    assert code == 200, inspected
    code, body = call("/creative/prepare", {"path": str(src)})
    assert code == 200 and body["prepared"] is True, body.get("refusal")
    assert src.read_bytes() == blob and hashlib.sha256(src.read_bytes()).hexdigest() == before
    assert body["original"]["original_unchanged"] is True
    assert body["original"]["sha256_before"] == before == body["original"]["sha256_after"]
    out = data_dir / routes_creative.DEFAULT_OUT_FOLDER / body["output"]["name"]
    assert out.is_file() and out != src
    assert [p.name for p in src.parent.iterdir()] == ["project.3mf"]
    return inspected, body, src, members(out)


def test_kromacut_journey_exports_a_verified_project(tmp_path, data_dir):
    blob = make_kromacut(layers=3)
    original = zipfile.ZipFile(__import__("io").BytesIO(blob))
    inspected, body, _src, exported = prepare(tmp_path, data_dir, blob)

    assert inspected["origin"]["generator"] == "kromacut" and inspected["origin"]["status"] == "detected"
    ver = body["verification"]
    assert ver["opens_as_zip"] is True
    cmp = ver["comparison"]
    # geometry, material table, component graph and part records come through byte-identical
    assert "3D/3dmodel.model" in cmp["preserved"] and "Metadata/model_settings.config" in cmp["preserved"]
    assert "Metadata/kromacut.config" in cmp["preserved"]
    assert cmp["dropped"] == [] and cmp["added"] == []
    assert cmp["modified"] == ["Metadata/project_settings.config"]
    for name in ("3D/3dmodel.model", "Metadata/model_settings.config", "Metadata/kromacut.config"):
        assert exported[name] == original.read(name), name
    root = exported["3D/3dmodel.model"].decode()
    assert root.count("<mesh>") == 3 and root.count("<basematerials") == 1
    assert len(re.findall(r'pid="1" pindex="\d"', root)) == 3
    assert ver["settings"]["removed_keys"] == []
    # the exported project passes the same structure check Prepare ran
    assert multipart.validate_archive(_Archive(exported))["ok"] is True


def test_ditherforge_bambu_path_journey_keeps_geometry_and_paint(tmp_path, data_dir):
    # bambu.go also writes Metadata/plate_1.json; Prepare drops plate_*.json as a stale slice cache (orca_import.SLICE_CACHE_*)
    blob = make_ditherforge_bambu(extra={"Metadata/plate_1.json": b"{}"})
    original = zipfile.ZipFile(__import__("io").BytesIO(blob))
    inspected, body, _src, exported = prepare(tmp_path, data_dir, blob)

    assert inspected["origin"]["generator"] == "ditherforge" and inspected["origin"]["status"] == "detected"
    ver = body["verification"]
    cmp = ver["comparison"]
    assert "3D/Objects/object_1.model" in cmp["preserved"] and cmp["added"] == []
    assert cmp["dropped"] == ["Metadata/plate_1.json"] and "Metadata/plate_1.json" not in exported
    assert exported["3D/Objects/object_1.model"] == original.read("3D/Objects/object_1.model")
    assert exported["3D/3dmodel.model"] == original.read("3D/3dmodel.model")
    # per-triangle paint survives: 3 painted triangles in, 3 out, same paint codes
    assert ver["per_face_paint"] == {"original_triangles": 3, "exported_triangles": 3, "kept": True}
    assert re.findall(r'paint_color="([^"]+)"', exported["3D/Objects/object_1.model"].decode()) == ["4", "8", "0C"]
    assert ver["settings"]["removed_keys"] == []


def test_ditherforge_generic_path_is_still_refused_with_the_real_reason(tmp_path, data_dir):
    """The upstream generic exporter writes part id 1 under component objectid 2. The check is unchanged."""
    blob = make_ditherforge(parts=1)
    src = write(tmp_path, blob)
    code, inspected = call("/creative/inspect", {"path": str(src)})
    assert code == 200 and inspected["origin"]["generator"] == "ditherforge"
    code, body = call("/creative/prepare", {"path": str(src)})
    assert code == 200 and body["prepared"] is False
    assert body["refusal"]["kind"] == "prepare_refused"
    assert body["refusal"]["problems"] == ["object 2: part ids ['1'] do not match its component ids ['2']"]
    assert src.read_bytes() == blob
    folder = data_dir / routes_creative.DEFAULT_OUT_FOLDER
    assert not folder.exists() or not list(folder.iterdir())


# -- negatives for the validator change: root-defined objects count only when they are real geometry --------

class _Archive:
    def __init__(self, parts):
        self.parts = parts

    def has_part(self, name):
        return name in self.parts

    def read_part(self, name):
        return self.parts[name]


def _kromacut_parts(mutate):
    parts = {n: v for n, v in members_from(make_kromacut(layers=2)).items()}
    mutate(parts)
    return _Archive(parts)


def members_from(blob):
    import io
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return {n: archive.read(n) for n in archive.namelist() if not n.endswith("/")}


def test_validator_accepts_the_kromacut_shape():
    result = multipart.validate_archive(_kromacut_parts(lambda parts: None))
    assert result["ok"] is True, result["problems"]


def test_validator_refuses_a_root_component_whose_object_does_not_exist():
    def drop_layer(parts):
        model = parts["3D/3dmodel.model"].decode()
        parts["3D/3dmodel.model"] = re.sub(r'<object id="3"[^>]*>.*?</object>', "", model, count=1, flags=re.S).encode()

    result = multipart.validate_archive(_kromacut_parts(drop_layer))
    assert result["ok"] is False
    assert any("reference an object that no file defines" in p and "'3'" in p for p in result["problems"])


def test_validator_refuses_a_root_mesh_object_with_no_triangles():
    def empty_mesh(parts):
        model = parts["3D/3dmodel.model"].decode()
        parts["3D/3dmodel.model"] = re.sub(r"<triangles>.*?</triangles>", "<triangles></triangles>", model, count=1,
                                            flags=re.S).encode()

    result = multipart.validate_archive(_kromacut_parts(empty_mesh))
    assert result["ok"] is False
    assert any("in the root model carries no geometry" in p for p in result["problems"])


def test_an_assembly_object_is_not_counted_as_geometry():
    """A component that points at the assembly itself (components, no mesh) is not a mesh object."""
    def point_at_assembly(parts):
        model = parts["3D/3dmodel.model"].decode()
        parts["3D/3dmodel.model"] = model.replace('<component objectid="2"', '<component objectid="4"', 1).encode()

    result = multipart.validate_archive(_kromacut_parts(point_at_assembly))
    assert result["ok"] is False
    assert any("'4'" in p and "no file defines" in p for p in result["problems"])


def test_a_pathless_component_cannot_borrow_an_object_from_a_path_file():
    """Root-defined ids and p:path ids are separate namespaces: a pathless component needs a root object."""
    def move_layer_to_file(parts):
        model = parts["3D/3dmodel.model"].decode()
        match = re.search(r'<object id="2"[^>]*>.*?</object>', model, re.S)
        parts["3D/3dmodel.model"] = model.replace(match.group(0), "", 1).encode()
        parts["3D/Objects/object_1.model"] = (
            '<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources>'
            + match.group(0) + "</resources></model>").encode()
        parts["3D/_rels/3dmodel.model.rels"] = b'<Relationships><Relationship Target="/3D/Objects/object_1.model"/></Relationships>'
        # a second, pathed component makes the validator scan the file, so object 2 is a known path-file id;
        # the original component still has no p:path and must not be satisfied by it
        model = parts["3D/3dmodel.model"].decode()
        parts["3D/3dmodel.model"] = model.replace(
            "</components>", '<component p:path="/3D/Objects/object_1.model" objectid="2"/></components>', 1).encode()
    result = multipart.validate_archive(_kromacut_parts(move_layer_to_file))
    assert result["ok"] is False
    assert any("no file defines" in p for p in result["problems"])


def test_prepare_still_never_writes_when_a_layer_is_missing(tmp_path, data_dir):
    blob = members_from(make_kromacut(layers=2))
    model = blob["3D/3dmodel.model"].decode()
    blob["3D/3dmodel.model"] = re.sub(r'<object id="3"[^>]*>.*?</object>', "", model, count=1, flags=re.S).encode()
    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, value in blob.items():
            archive.writestr(name, value)
    src = write(tmp_path, buffer.getvalue())
    code, body = call("/creative/prepare", {"path": str(src)})
    assert code == 200 and body["prepared"] is False
    assert any("no file defines" in p for p in body["refusal"]["problems"])
    folder = data_dir / routes_creative.DEFAULT_OUT_FOLDER
    assert not folder.exists() or not list(folder.iterdir())
    assert json.dumps(body).count(str(tmp_path)) == 0


# -- Sol R4-F1 / R4-F2: separate id namespaces for types, and no nested objects -------------------------------

_NS = 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
_MESH = ('<mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/><vertex x="0" y="1" z="0"/>'
         '<vertex x="0" y="0" z="1"/></vertices><triangles><triangle v1="0" v2="2" v3="1"/>'
         '<triangle v1="0" v2="1" v3="3"/></triangles></mesh>')


def _collision_archive(*, file_type, root_type):
    """Assembly 10 holds one PATHED component (object 1 in object_1.model). The root also defines an unrelated
    mesh object that happens to be id 1. The part under object 10 is a normal_part, which needs type model."""
    root = (f'<model {_NS} xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"><resources>'
            f'<object id="1" type="{root_type}">{_MESH}</object>'
            f'<object id="10" type="model"><components><component p:path="/3D/Objects/object_1.model" objectid="1"/>'
            f'</components></object></resources><build><item objectid="10"/></build></model>')
    return _Archive({
        "3D/3dmodel.model": root.encode(),
        "3D/_rels/3dmodel.model.rels": b'<Relationships><Relationship Target="/3D/Objects/object_1.model"/></Relationships>',
        "3D/Objects/object_1.model": f'<model {_NS}><resources><object id="1" type="{file_type}">{_MESH}</object>'
                                     f'</resources></model>'.encode(),
        "Metadata/model_settings.config": (b'<config><object id="10"><part id="1" subtype="normal_part"></part></object>'
                                           b'</config>')})


def test_a_root_object_with_the_same_id_does_not_hide_a_path_file_type_mismatch():
    """The path file's object 1 is typed 'other' under a normal_part: still refused, whatever the root's id 1 is."""
    result = multipart.validate_archive(_collision_archive(file_type="other", root_type="model"))
    assert result["ok"] is False
    assert any("is a normal_part and the geometry under it is typed 'other'" in p for p in result["problems"])


def test_a_root_object_with_the_same_id_does_not_reject_a_correct_path_file_reference():
    """The path file's object 1 is typed 'model' under a normal_part: accepted even if the root's id 1 is 'other'."""
    result = multipart.validate_archive(_collision_archive(file_type="model", root_type="other"))
    assert result["ok"] is True, result["problems"]


def _with_nested_object():
    parts = members_from(make_kromacut(layers=2))
    model = parts["3D/3dmodel.model"].decode()
    match = re.search(r'(<object id="2"[^>]*>)(.*?)(</object>)', model, re.S)
    nested = f'{match.group(1)}<object id="9" type="model">{match.group(2)}</object>{match.group(3)}'
    parts["3D/3dmodel.model"] = model.replace(match.group(0), nested, 1).encode()
    return parts


def test_a_mesh_nested_inside_a_root_object_is_not_credited_to_the_outer_object():
    result = multipart.validate_archive(_Archive(_with_nested_object()))
    assert result["ok"] is False
    assert any("object 2 in the root model contains another object" in p for p in result["problems"])
    assert any("no file defines" in p and "'2'" in p for p in result["problems"])


def test_prepare_refuses_the_nested_shape_and_writes_nothing(tmp_path, data_dir):
    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, value in _with_nested_object().items():
            archive.writestr(name, value)
    src = write(tmp_path, buffer.getvalue())
    code, body = call("/creative/prepare", {"path": str(src)})
    assert code == 200 and body["prepared"] is False
    assert any("contains another object" in p for p in body["refusal"]["problems"])
    folder = data_dir / routes_creative.DEFAULT_OUT_FOLDER
    assert not folder.exists() or not list(folder.iterdir())
    assert src.read_bytes() == buffer.getvalue()


def test_one_assembly_may_not_mix_root_and_file_components_with_the_same_id():
    """Sol R5-F1: parts name a number, not a namespace, so a mixed same-id assembly is refused, not guessed."""
    archive = _collision_archive(file_type="other", root_type="model")
    root = archive.parts["3D/3dmodel.model"].decode()
    archive.parts["3D/3dmodel.model"] = root.replace(
        "</components>", '<component objectid="1"/></components>', 1).encode()
    archive.parts["Metadata/model_settings.config"] = (
        b'<config><object id="10"><part id="1" subtype="normal_part"></part>'
        b'<part id="1" subtype="normal_part"></part></object></config>')
    result = multipart.validate_archive(archive)
    assert result["ok"] is False
    assert any("referenced both from the root model and from a file" in p for p in result["problems"])
