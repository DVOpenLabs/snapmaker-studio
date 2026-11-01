"""Engines track routes for a user-configured Lumina-compatible service.

The service in every test is the synthetic loopback `LuminaHttpMock`, not Lumina: evidence is
mock-service-tested and no real Lumina installation is exercised.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

from snapstudio_api import ext_routes, routes_engines
from snapstudio_core.foundation.netguard import clear_write_origins
from tests.mocks.lumina_server import HTTP_ARTIFACTS, LuminaHttpMock

IMAGE_BYTES = b"synthetic-image-bytes-not-a-real-picture"


class FakeHandler:
    def __init__(self):
        self.sent = []

    def _send(self, code, obj):
        self.sent.append((code, obj))


def call(path, data):
    handler = FakeHandler()
    assert ext_routes.dispatch(handler, path, data) is True
    assert len(handler.sent) == 1
    return handler.sent[0]


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    target = tmp_path / "studio-data"
    target.mkdir()
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(target))
    return target


@pytest.fixture
def image(tmp_path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    path = folder / "synthetic.png"
    path.write_bytes(IMAGE_BYTES)
    return path


@pytest.fixture
def service():
    with LuminaHttpMock() as mock:
        yield mock
    clear_write_origins()


def assert_no_path(body, *roots):
    text = json.dumps(body)
    for root in roots:
        for form in (str(root), str(root).replace("\\", "\\\\"), root.as_posix()):
            assert form not in text
    assert "\\Users\\" not in text and "\\\\Users\\\\" not in text and "/Users/" not in text


def request(service, image, fmt, **extra):
    return {"service_url": service.url, "image_path": str(image), "lut_name": "Default", "format": fmt, **extra}


# -- registration ----------------------------------------------------------------

def test_routes_are_registered_under_engines_through_dispatch():
    for suffix in ("formats", "status", "generate"):
        assert f"/engines/lumina/{suffix}" in ext_routes.ROUTES
        assert ext_routes.ROUTES[f"/engines/lumina/{suffix}"].__module__.endswith("routes_engines")
    handled = ext_routes.dispatch(FakeHandler(), "/engines/lumina/nothing", {})
    assert handled is False


def test_dispatch_rejects_a_non_object_body():
    handler = FakeHandler()
    ext_routes.dispatch(handler, "/engines/lumina/formats", [])
    assert handler.sent[0][0] == 400


# -- formats ---------------------------------------------------------------------

def test_formats_list_is_explicit_and_labelled():
    status, body = call("/engines/lumina/formats", {})
    assert status == 200
    assert [f["kind"] for f in body["formats"]] == ["3mf", "png", "glb"]
    assert all(f["evidence"] == "mock-service-tested" and f["meaning"] for f in body["formats"])
    assert body["progress"] == "unknown" and body["cancel"] == "unknown"
    assert "no real Lumina" in body["note"]


# -- status ----------------------------------------------------------------------

def test_status_ok_reports_only_what_was_read(service):
    status, body = call("/engines/lumina/status", {"service_url": service.url})
    assert status == 200
    assert body["status"] == "ok" and body["api_version"] == "2.0" and body["can_generate"] is True
    assert body["progress"] == "unknown" and body["cancel"] == "unknown"
    assert "not proof" in body["note"]


def test_status_unknown_for_unsupported_version_without_body_echo():
    with LuminaHttpMock(version="9.9") as mock:
        status, body = call("/engines/lumina/status", {"service_url": mock.url})
    clear_write_origins()
    assert status == 200 and body["status"] == "unknown" and body["code"] == "unsupported_version"
    assert "9.9" not in json.dumps(body)


def test_status_unknown_when_nothing_is_listening():
    with LuminaHttpMock() as mock:
        url = mock.url
    status, body = call("/engines/lumina/status", {"service_url": url})
    assert status == 200 and body["status"] == "unknown"
    assert body["code"].startswith("network_")


def test_status_refuses_a_non_local_address():
    status, body = call("/engines/lumina/status", {"service_url": "http://8.8.8.8:8000"})
    assert status == 422 and body["error"] == "refusal" and body["code"] == "network_off_network"


def test_status_rejects_a_service_url_with_a_path(service):
    status, body = call("/engines/lumina/status", {"service_url": service.url + "/x"})
    assert status == 422 and body["code"] == "invalid_service_url"


def test_status_requires_a_service_url():
    status, body = call("/engines/lumina/status", {})
    assert status == 400 and body["error"] == "invalid"


# -- generate: success -----------------------------------------------------------

@pytest.mark.parametrize("fmt,preview_id,glb_id,artifact", [
    ("3mf", "mfile", None, "mfile"),
    ("png", "pngfile", "glbfile", "pngfile"),
    ("glb", "pngfile", "glbfile", "glbfile"),
])
def test_generate_writes_the_exact_bytes_as_a_new_file(tmp_path, data_dir, image, fmt, preview_id, glb_id, artifact):
    before = hashlib.sha256(image.read_bytes()).hexdigest()
    with LuminaHttpMock(preview_id=preview_id, glb_id=glb_id) as mock:
        status, body = call("/engines/lumina/generate", request(mock, image, fmt))
        uploaded = mock.uploads[0]["bytes"]
    clear_write_origins()
    expected = HTTP_ARTIFACTS[artifact][1]
    assert status == 200 and body["generated"] is True
    assert body["kind"] == fmt
    assert body["sha256"] == hashlib.sha256(expected).hexdigest() and body["size_bytes"] == len(expected)
    written = data_dir / "lumina-output" / body["file_name"]
    assert written.read_bytes() == expected
    assert os.path.dirname(body["file_name"]) == ""
    assert body["generated_by"] == "a user-configured local Lumina-compatible service (not verified)"
    assert body["location_label"] == "Studio's lumina-output folder"
    assert "did not watch" in body["advisory"]
    assert body["progress"] == "unknown" and body["cancel"] == "unknown"
    assert hashlib.sha256(image.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in image.parent.iterdir()) == ["synthetic.png"]
    assert IMAGE_BYTES in uploaded
    assert_no_path(body, tmp_path, data_dir)


def test_generate_into_a_chosen_folder_and_never_overwrites(tmp_path, data_dir, image):
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    with LuminaHttpMock() as mock:
        s1, b1 = call("/engines/lumina/generate", request(mock, image, "png", out_dir=str(chosen)))
        s2, b2 = call("/engines/lumina/generate", request(mock, image, "png", out_dir=str(chosen)))
    clear_write_origins()
    assert s1 == s2 == 200
    assert b1["location_label"] == "the folder you chose"
    assert b1["file_name"] != b2["file_name"]
    assert len(list(chosen.iterdir())) == 2
    assert_no_path(b1, tmp_path, data_dir)
    assert_no_path(b2, tmp_path, data_dir)


def test_generate_refuses_the_images_own_folder_as_output(tmp_path, data_dir, service, image):
    status, body = call("/engines/lumina/generate", request(service, image, "png", out_dir=str(image.parent)))
    assert status == 400 and "other than the image's own folder" in body["message"]
    assert service.requests == []
    assert_no_path(body, tmp_path, data_dir)


# -- generate: refusals ----------------------------------------------------------

@pytest.mark.parametrize("fmt", ["", "stl", "PNG", "obj", None, 3, ["png"]])
def test_generate_refuses_an_unlisted_format_before_any_request(data_dir, service, image, fmt):
    status, body = call("/engines/lumina/generate", request(service, image, fmt))
    assert status == 400 and body["error"] == "invalid"
    assert "3mf, png, glb" in body["message"]
    assert service.requests == []
    assert not (data_dir / "lumina-output").exists() or not list((data_dir / "lumina-output").iterdir())


def test_generate_requires_a_format(data_dir, service, image):
    payload = request(service, image, "png")
    del payload["format"]
    status, body = call("/engines/lumina/generate", payload)
    assert status == 400 and "3mf, png, glb" in body["message"]
    assert service.requests == []


def test_generate_refuses_a_non_local_service_url(tmp_path, data_dir, image):
    payload = {"service_url": "http://8.8.8.8:8000", "image_path": str(image), "lut_name": "Default", "format": "png"}
    status, body = call("/engines/lumina/generate", payload)
    assert status == 422 and body["code"] == "network_off_network"
    assert "local network" in body["message"] or "own network" in body["message"]
    assert_no_path(body, tmp_path, data_dir)
    assert not (data_dir / "lumina-output").exists() or not list((data_dir / "lumina-output").iterdir())


@pytest.mark.parametrize("path", [
    "\\\\server\\share\\a.png", "//server/share/a.png", "\\/server/share/a.png",
    "\\\\?\\UNC\\server\\share\\a.png", "\\\\?\\C:\\a.png", "\\\\.\\pipe\\a",
    "\\??\\UNC\\server\\share\\a.png", "/??/UNC/server/share/a.png",
])
def test_generate_refuses_unc_and_device_paths_in_any_slash_style(data_dir, service, path):
    status, body = call("/engines/lumina/generate", {
        "service_url": service.url, "image_path": path, "lut_name": "Default", "format": "png"})
    assert status == 400 and "network or device" in body["message"]
    assert service.requests == []


def test_generate_refuses_a_directory_and_a_missing_file(tmp_path, data_dir, service):
    for target in (tmp_path, tmp_path / "missing.png"):
        status, body = call("/engines/lumina/generate", {
            "service_url": service.url, "image_path": str(target), "lut_name": "Default", "format": "png"})
        assert status == 400
        assert_no_path(body, tmp_path)
    assert service.requests == []


def test_generate_refuses_an_oversize_image(tmp_path, data_dir, service, image, monkeypatch):
    monkeypatch.setattr(routes_engines, "MAX_INPUT_BYTES", 8)
    status, body = call("/engines/lumina/generate", request(service, image, "png"))
    assert status == 400 and "at most" in body["message"]
    assert service.requests == []
    assert_no_path(body, tmp_path, data_dir)


def test_generate_refuses_a_link_to_a_network_target(tmp_path, data_dir, service):
    link = tmp_path / "linked.png"
    try:
        os.symlink("\\\\server\\share\\a.png", link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted here")
    status, body = call("/engines/lumina/generate", {
        "service_url": service.url, "image_path": str(link), "lut_name": "Default", "format": "png"})
    assert status == 400 and "network or device" in body["message"]
    assert service.requests == []


def test_generate_refuses_a_missing_or_overlong_lut(data_dir, service, image):
    payload = request(service, image, "png")
    del payload["lut_name"]
    assert call("/engines/lumina/generate", payload)[0] == 400
    payload["lut_name"] = "x" * 257
    assert call("/engines/lumina/generate", payload)[0] == 400
    assert service.requests == []


def test_generate_refuses_an_out_dir_that_is_not_a_local_folder(tmp_path, data_dir, service, image):
    for target in ("\\\\server\\share", str(tmp_path / "nope"), str(image)):
        status, body = call("/engines/lumina/generate", request(service, image, "png", out_dir=target))
        assert status == 400 and "output folder" in body["message"]
        assert_no_path(body, tmp_path)
    assert service.requests == []


# -- generate: engine behaviour --------------------------------------------------

def test_generate_names_what_the_service_returned_when_the_format_differs(tmp_path, data_dir, image):
    with LuminaHttpMock(preview_id="pngfile", glb_id=None) as mock:
        status, body = call("/engines/lumina/generate", request(mock, image, "3mf"))
    clear_write_origins()
    assert status == 422 and body["code"] == "format_not_produced"
    assert "png" in body["message"] and "Nothing was saved" in body["message"]
    assert not (data_dir / "lumina-output").exists() or not list((data_dir / "lumina-output").iterdir())


def test_generate_maps_engine_error_codes_without_body_echo(tmp_path, data_dir, image):
    with LuminaHttpMock(version="9.9") as mock:
        status, body = call("/engines/lumina/generate", request(mock, image, "png"))
    clear_write_origins()
    assert status == 422 and body["code"] == "unsupported_version"
    assert "9.9" not in json.dumps(body)
    with LuminaHttpMock(artifacts={}) as mock:
        status, body = call("/engines/lumina/generate", request(mock, image, "png"))
    clear_write_origins()
    assert status == 422 and body["code"] == "artifact_unavailable"
    assert_no_path(body, tmp_path, data_dir)


@pytest.mark.parametrize("locator", ["bad.id", "..%2Fx", "a b", "x" * 129])
def test_generate_never_fetches_an_invalid_file_id(data_dir, image, locator):
    with LuminaHttpMock(preview_id=locator, glb_id=None) as mock:
        status, body = call("/engines/lumina/generate", request(mock, image, "png"))
        fetched = [r for r in mock.requests if r[1].startswith("/api/files/")]
    clear_write_origins()
    assert status == 422 and body["code"] == "format_not_produced"
    assert fetched == []


def test_write_origin_is_revoked_after_generate(data_dir, image):
    from snapstudio_core.foundation import netguard

    with LuminaHttpMock() as mock:
        call("/engines/lumina/generate", request(mock, image, "png"))
        assert netguard._WRITE_ORIGINS == set()
    clear_write_origins()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path styles")
def test_generate_response_never_holds_a_windows_path(tmp_path, data_dir, image):
    with LuminaHttpMock() as mock:
        status, body = call("/engines/lumina/generate", request(mock, image, "png"))
    clear_write_origins()
    assert status == 200
    assert ":\\" not in json.dumps(body).replace("\\\\", "\\")


def test_link_walk_refuses_a_link_whose_target_is_a_network_path(tmp_path, monkeypatch):
    """Exercised with a faked link so it runs where symlinks cannot be created."""
    import stat as stat_module

    from snapstudio_core.engines import local_input

    fake = str(tmp_path / "linked.png")
    real_lstat = os.lstat

    def fake_lstat(path, *a, **k):
        if os.fspath(path) == fake:
            info = real_lstat(tmp_path)
            return os.stat_result((stat_module.S_IFLNK | 0o777,) + tuple(info)[1:])
        return real_lstat(path, *a, **k)

    monkeypatch.setattr(os, "lstat", fake_lstat)
    monkeypatch.setattr(os, "readlink", lambda p: r"\\server\share\a.png")
    assert local_input.reaches_network(fake) is True
    monkeypatch.setattr(os, "readlink", lambda p: str(tmp_path))
    assert local_input.reaches_network(fake) is False
