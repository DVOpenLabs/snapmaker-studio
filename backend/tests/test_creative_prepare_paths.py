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
    # the exported project passes the same check Prepare ran
    assert body["verification"]["comparison"]["added"] == []


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
        parts["3D/3dmodel.model"] = model.replace('<component objectid="2"', '<component objectid="5"', 1).encode()

    result = multipart.validate_archive(_kromacut_parts(point_at_assembly))
    assert result["ok"] is False
    assert any("'5'" in p and "no file defines" in p for p in result["problems"])


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
        # the component still has no p:path
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
