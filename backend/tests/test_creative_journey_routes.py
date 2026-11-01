"""Route level journey: inspect -> prepare -> exported copy verified, original unchanged.

Evidence label: fixture-tested. Archives are SYNTHETIC (see tests/fixtures/creative/PROVENANCE.md). The
real Prepare service runs; Snapmaker Orca, slicers and printers are not involved.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

from snapstudio_api import ext_routes, routes_creative
from snapstudio_core import localpath

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "creative"))
from zip_factory import make_3mf, make_ditherforge, make_kromacut, make_sindricad  # noqa: E402

UNC = r"\\attacker-host\share\project.3mf"
DEVICE = r"\\?\C:\out"


class FakeHandler:
    def __init__(self):
        self.sent = []

    def _send(self, code, obj):
        self.sent.append((code, obj))


def call(route, data):
    h = FakeHandler()
    assert ext_routes.dispatch(h, route, data) is True
    return h.sent[0]


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Studio's data folder, isolated for every test: Prepare keeps a ledger there."""
    target = tmp_path / "studio-data"
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(target))
    return target


def write(tmp_path, blob, name="project.3mf"):
    folder = tmp_path / "src"
    folder.mkdir(exist_ok=True)
    p = folder / name
    p.write_bytes(blob)
    return p


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_routes_are_registered_under_creative():
    for route in ("/creative/inspect", "/creative/formats", "/creative/prepare"):
        assert route in ext_routes.ROUTES


# -- /creative/formats -----------------------------------------------------------------------

def test_formats_route_returns_the_table():
    code, body = call("/creative/formats", {})
    assert code == 200
    assert [f["key"] for f in body["formats"]][:3] == ["ditherforge", "kromacut", "sindricad"]
    assert body["manual_only"] == ["imagemap", "lumina"]
    assert body["evidence"].startswith("fixture-tested")


# -- inspect: new tools ----------------------------------------------------------------------

@pytest.mark.parametrize("blob,name", [(make_ditherforge(), "ditherforge"), (make_kromacut(), "kromacut"),
                                       (make_sindricad(), "sindricad")])
def test_inspect_detects_each_new_tool_with_facts(tmp_path, blob, name):
    code, body = call("/creative/inspect", {"path": str(write(tmp_path, blob))})
    assert code == 200
    assert body["origin"] == {"generator": name, "status": "detected", "candidates": [name]}
    assert body["facts"][name]["application"]
    assert body["format_info"][0]["key"] == name and body["format_info"][0]["not_read"]
    assert body["explanation"] is None
    assert str(tmp_path) not in json.dumps(body)


def test_inspect_ambiguous_markers_explain_and_do_not_guess(tmp_path):
    blob = make_sindricad(extra={"Metadata/kromacut.config": b"x"})
    code, body = call("/creative/inspect", {"path": str(write(tmp_path, blob))})
    assert code == 200
    assert body["origin"]["status"] == "ambiguous" and body["origin"]["generator"] == "unknown"
    assert set(body["origin"]["candidates"]) == {"kromacut", "sindricad"}
    assert body["explanation"]["kind"] == "ambiguous_origin"
    assert body["explanation"]["what_to_do"]


def test_inspect_unknown_explains_what_was_seen(tmp_path):
    blob = make_3mf(settings={"layer_height": "0.2"})
    code, body = call("/creative/inspect", {"path": str(write(tmp_path, blob))})
    assert code == 200 and body["origin"]["status"] == "unknown"
    ex = body["explanation"]
    assert ex["kind"] == "unknown_origin"
    assert "2 parts" in ex["seen"] and "does not say which tool" in ex["not_supported"]


def test_chosen_format_resolves_ambiguity(tmp_path):
    blob = make_sindricad(extra={"Metadata/kromacut.config": b"x"})
    code, body = call("/creative/inspect", {"path": str(write(tmp_path, blob)), "format": "sindricad"})
    assert code == 200 and body["origin"]["status"] == "chosen" and body["origin"]["generator"] == "sindricad"


@pytest.mark.parametrize("fmt", ["ditherforge", "kromacut", "sindricad", "forcaslicer", "lixnix", "fullspectrum"])
def test_wrong_shape_for_chosen_format_is_an_actionable_400(tmp_path, fmt):
    path = write(tmp_path, make_3mf(settings={"layer_height": "0.2"}))
    code, body = call("/creative/inspect", {"path": str(path), "format": fmt})
    assert code == 400 and body["error"] == "invalid"
    message = body["message"]
    assert "does not carry what Studio reads for" in message
    assert "Studio looks for:" in message and "What to do:" in message
    assert "2 parts" in message


def test_manual_only_format_still_inspects_a_plain_3mf(tmp_path):
    path = write(tmp_path, make_3mf(settings={"layer_height": "0.2"}))
    for fmt in ("imagemap", "lumina"):
        code, body = call("/creative/inspect", {"path": str(path), "format": fmt})
        assert code == 200 and body["origin"]["status"] == "chosen"
        assert body["format_info"][0]["selection"] == "manual only"


def test_inspect_still_refuses_a_non_3mf_for_a_chosen_format(tmp_path):
    path = write(tmp_path, b"not a zip", "x.3mf")
    code, body = call("/creative/inspect", {"path": str(path), "format": "imagemap"})
    assert code == 400 and "not a readable 3MF" in body["message"]


# -- prepare: end to end ---------------------------------------------------------------------

def test_prepare_sindricad_writes_a_new_verified_copy_in_the_studio_folder(tmp_path, data_dir):
    blob = make_sindricad()
    src = write(tmp_path, blob)
    mtime = src.stat().st_mtime_ns
    code, body = call("/creative/prepare", {"path": str(src)})
    assert code == 200 and body["prepared"] is True, body
    out = Path(body["output"]["path"])
    assert out.is_file() and out != src
    assert out.parent == data_dir / routes_creative.DEFAULT_OUT_FOLDER
    assert body["output"]["in_source_folder"] is False and body["output"]["location"] == "studio_default"
    # nothing was written next to the original
    assert [p.name for p in src.parent.iterdir()] == ["project.3mf"]
    assert src.read_bytes() == blob and src.stat().st_mtime_ns == mtime
    assert body["original"]["original_unchanged"] is True
    assert body["original"]["sha256_before"] == hashlib.sha256(blob).hexdigest() == body["original"]["sha256_after"]
    # the exported archive is opened and its members listed with their hashes
    ver = body["verification"]
    assert ver["opens_as_zip"] is True and ver["sha256"] == sha(out)
    with zipfile.ZipFile(out) as z:
        actual = {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith("/")}
    assert {m["name"]: m["sha256"] for m in ver["members"]} == actual
    # member comparison: geometry and body names kept byte-identical, project settings rewritten by Prepare
    cmp = ver["comparison"]
    assert "3D/3dmodel.model" in cmp["preserved"] and "Metadata/model_settings.config" in cmp["preserved"]
    assert cmp["modified"] == ["Metadata/project_settings.config"]
    assert cmp["dropped"] == [] and cmp["added"] == []
    assert ver["per_face_paint"] == {"original_triangles": 2, "exported_triangles": 2, "kept": True}
    assert ver["settings"]["removed_keys"] == [] and ver["settings"]["added_key_count"] > 0
    assert "ready" not in json.dumps({k: v for k, v in body.items() if k != "output"}).lower().replace("already", "")


def test_prepare_fullspectrum_keeps_unknown_members_and_reports_the_rewritten_settings(tmp_path, data_dir):
    blob = make_3mf(settings={"mixed_filament_definitions": "1,2,1,0,50,0,u7", "layer_height": "0.2"},
                    members={"Metadata/plate_1.png": b"opaque-bytes"})
    src = write(tmp_path, blob)
    code, body = call("/creative/prepare", {"path": str(src)})
    assert code == 200 and body["prepared"] is True
    cmp = body["verification"]["comparison"]
    assert "Metadata/plate_1.png" in cmp["preserved"] and cmp["dropped"] == []
    assert body["verification"]["settings"]["removed_keys"] == []
    assert body["original"]["original_unchanged"] is True and src.read_bytes() == blob


def test_prepare_chosen_imagemap_to_an_explicit_out_dir(tmp_path):
    src = write(tmp_path, make_3mf(settings={"layer_height": "0.2"}))
    out_dir = tmp_path / "chosen-out"
    out_dir.mkdir()
    code, body = call("/creative/prepare", {"path": str(src), "format": "imagemap", "out_dir": str(out_dir)})
    assert code == 200 and body["prepared"] is True
    assert Path(body["output"]["path"]).parent == out_dir and body["output"]["location"] == "chosen"
    assert [p.name for p in src.parent.iterdir()] == ["project.3mf"]
    assert body["original"]["original_unchanged"] is True


def test_prepare_can_write_beside_the_original_only_when_out_dir_says_so(tmp_path):
    src = write(tmp_path, make_sindricad())
    before = sha(src)
    code, body = call("/creative/prepare", {"path": str(src), "out_dir": str(src.parent)})
    assert code == 200 and body["prepared"] is True and body["output"]["in_source_folder"] is True
    out = Path(body["output"]["path"])
    assert out != src and sha(src) == before and sorted(p.name for p in src.parent.iterdir()) == sorted(["project.3mf", out.name])


def test_prepare_never_overwrites_a_previous_output(tmp_path, data_dir):
    src = write(tmp_path, make_sindricad())
    first = call("/creative/prepare", {"path": str(src)})[1]["output"]["path"]
    second = call("/creative/prepare", {"path": str(src)})[1]["output"]["path"]
    assert first != second and Path(first).is_file() and Path(second).is_file()


@pytest.mark.parametrize("blob,tool", [(make_ditherforge(), "DitherForge"), (make_kromacut(), "Kromacut")])
def test_prepare_refusal_is_explained_when_the_engine_cannot_vouch_for_a_copy(tmp_path, data_dir, blob, tool):
    """Studio's Prepare checks the component graph and part ids; these tools' documented shapes fail that
    check, so no copy is written and the refusal says why."""
    src = write(tmp_path, blob)
    code, body = call("/creative/prepare", {"path": str(src)})
    assert code == 200 and body["prepared"] is False
    ref = body["refusal"]
    assert ref["kind"] == "prepare_refused" and tool in ref["seen"]
    assert "cannot vouch" in ref["not_supported"] and ref["what_to_do"] and ref["problems"]
    assert src.read_bytes() == blob
    assert not (data_dir / routes_creative.DEFAULT_OUT_FOLDER).exists() or not list(
        (data_dir / routes_creative.DEFAULT_OUT_FOLDER).iterdir())


def test_prepare_refuses_unknown_origin_with_an_explanation_and_writes_nothing(tmp_path, data_dir):
    src = write(tmp_path, make_3mf(settings={"layer_height": "0.2"}))
    code, body = call("/creative/prepare", {"path": str(src)})
    assert code == 200 and body["prepared"] is False
    ref = body["refusal"]
    assert ref["kind"] == "unknown_origin" and "Nothing was prepared." in ref["not_supported"]
    assert ref["seen"] and ref["what_to_do"]
    assert [p.name for p in src.parent.iterdir()] == ["project.3mf"]
    assert not data_dir.exists()


def test_prepare_refuses_ambiguous_origin_until_a_format_is_chosen(tmp_path, data_dir):
    src = write(tmp_path, make_sindricad(extra={"Metadata/kromacut.config": b"x"}))
    code, body = call("/creative/prepare", {"path": str(src)})
    assert code == 200 and body["prepared"] is False and body["refusal"]["kind"] == "ambiguous_origin"
    code, body = call("/creative/prepare", {"path": str(src), "format": "sindricad"})
    assert code == 200 and body["prepared"] is True


def test_prepare_wrong_shape_for_chosen_format_is_refused_before_any_write(tmp_path, data_dir):
    src = write(tmp_path, make_3mf(settings={"layer_height": "0.2"}))
    code, body = call("/creative/prepare", {"path": str(src), "format": "sindricad"})
    assert code == 400 and "What to do:" in body["message"]
    assert not data_dir.exists()


# -- path guards -----------------------------------------------------------------------------

@pytest.fixture
def no_filesystem_probe(monkeypatch):
    def guarded(real):
        def wrapper(*a, **k):
            if a and isinstance(a[0], str) and localpath.is_network_or_device_path(a[0]):
                raise AssertionError("a network or device path reached the filesystem")
            return real(*a, **k)
        return wrapper
    monkeypatch.setattr(os, "stat", guarded(os.stat))
    monkeypatch.setattr("builtins.open", guarded(open))


@pytest.mark.parametrize("route", ["/creative/inspect", "/creative/prepare"])
def test_unc_source_is_refused_before_any_filesystem_access(no_filesystem_probe, route):
    code, body = call(route, {"path": UNC})
    assert code == 400 and body["error"] == "invalid"


def test_unc_and_device_out_dir_are_refused(tmp_path, no_filesystem_probe):
    src = write(tmp_path, make_sindricad())
    for bad in (UNC, DEVICE, "//attacker-host/share/out"):
        code, body = call("/creative/prepare", {"path": str(src), "out_dir": bad})
        assert code == 400 and "output folder" in body["message"]
    assert [p.name for p in src.parent.iterdir()] == ["project.3mf"]


def test_out_dir_must_exist_and_be_a_directory(tmp_path):
    src = write(tmp_path, make_sindricad())
    for bad in (str(tmp_path / "absent"), str(src), 5, "a\x00b"):
        code, _ = call("/creative/prepare", {"path": str(src), "out_dir": bad})
        assert code == 400


def test_prepare_copy_has_no_banned_wording():
    text = (routes_creative.PREPARE_ADVISORY + routes_creative.ADVISORY + routes_creative.EVIDENCE).lower()
    for banned in ("guarantee", "100%", "ready", "simultaneous", "coming soon"):
        assert banned not in text
