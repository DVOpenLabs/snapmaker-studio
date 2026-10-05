"""register_downloaded_model + POST /library/register_download."""
import hashlib
import os
import shutil
from pathlib import Path

import pytest

from snapstudio_api import service
from snapstudio_api.server import build_server
from snapstudio_core import library
from tests.test_api import _request, _run

PAINTED = Path(__file__).parent / "fixtures" / "painted" / "orcaslicer-2.4.2-painted-cube.3mf"

_TRI = "facet normal 0 0 0\n outer loop\n  vertex {}\n  vertex {}\n  vertex {}\n endloop\nendfacet\n"
_STL = "solid t\n" + "".join(_TRI.format(*t) for t in [
    ("0 0 0", "10 0 0", "0 10 0"), ("0 0 0", "0 0 10", "10 0 0"),
    ("0 0 0", "0 10 0", "0 0 10"), ("10 0 0", "0 0 10", "0 10 0")]) + "endsolid t\n"


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    # Studio's controlled downloads folder: files registered here are accepted.
    monkeypatch.setenv("SNAPSTUDIO_MODEL_DOWNLOADS_DIR", str(tmp_path))
    return tmp_path


def _file(tmp_path, name, content=None):
    p = tmp_path / name
    if content is None:
        shutil.copy(PAINTED, p)
    else:
        p.write_bytes(content if isinstance(content, bytes) else content.encode())
    return str(p)


def _rows():
    conn = service._conn()
    try:
        return (conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM project_sources").fetchone()[0])
    finally:
        conn.close()


def _source(pid):
    conn = service._conn()
    try:
        return library.get_source(conn, pid)
    finally:
        conn.close()


def test_valid_3mf_registers_with_hash_size_and_provenance(data):
    p = _file(data, "cube.3mf")
    r = service.register_downloaded_model(p, "www.printables.com",
                                          "https://www.printables.com/model/1-cube?utm=x#files")
    raw = Path(p).read_bytes()
    assert r["ok"] is True
    assert r["sha256"] == hashlib.sha256(raw).hexdigest() and r["size_bytes"] == len(raw)
    assert (r["site"], r["site_name"], r["filename"], r["name"]) == (
        "printables.com", "Printables", "cube.3mf", "cube.3mf")
    assert r["ready_hint"] in ("check", "prepare")
    assert set(r) == {"ok", "project_id", "name", "filename", "site", "site_name", "sha256",
                      "size_bytes", "source_family", "verdict", "filament_count", "is_u1",
                      "ready_hint"}
    s = _source(r["project_id"])
    assert s["page_url"] == "https://www.printables.com/model/1-cube"
    assert s["sha256"] == r["sha256"] and s["filename"] == "cube.3mf"
    assert str(data) not in repr(r) and os.sep not in r["filename"]


def test_valid_stl_registers(data):
    r = service.register_downloaded_model(_file(data, "t.STL", _STL), "thingiverse.com")
    assert r["ok"] and r["site_name"] == "Thingiverse" and r["ready_hint"] == "prepare"
    assert _rows() == (1, 1)


@pytest.mark.parametrize("name", ["a.zip", "a.gcode", "a.exe", "a.3mf.exe", "noext"])
def test_unsupported_extensions_refused_with_no_rows(data, name):
    with pytest.raises(service.DownloadRefused):
        service.register_downloaded_model(_file(data, name, b"PK\x03\x04data"), "printables.com")
    assert _rows() == (0, 0)


def test_empty_missing_and_directory_refused(data):
    for p in (_file(data, "e.3mf", b""), str(data / "nope.3mf"), str(data)):
        with pytest.raises(service.DownloadRefused):
            service.register_downloaded_model(p, "printables.com")
    assert _rows() == (0, 0)


def test_oversized_refused(data, monkeypatch):
    monkeypatch.setattr(service, "MAX_DOWNLOAD_BYTES", 100)
    with pytest.raises(service.DownloadRefused):
        service.register_downloaded_model(_file(data, "big.3mf"), "printables.com")
    assert _rows() == (0, 0)


@pytest.mark.parametrize("name,content", [("bad.3mf", b"this is not a zip"),
                                          ("bad.stl", b"garbage bytes, no mesh")])
def test_unreadable_model_leaves_no_rows(data, name, content):
    with pytest.raises(service.DownloadRefused):
        service.register_downloaded_model(_file(data, name, content), "printables.com")
    assert _rows() == (0, 0)


@pytest.mark.parametrize("site", ["example.com", "printables.com.evil.example", "notprintables.com",
                                  "evilprintables.com", "", "https://printables.com",
                                  "printables.com:443"])
def test_off_allowlist_or_lookalike_site_refused(data, site):
    with pytest.raises(service.DownloadRefused):
        service.register_downloaded_model(_file(data, "c.3mf"), site)
    assert _rows() == (0, 0)


@pytest.mark.parametrize("host,key,name", [
    ("makerworld.com", "makerworld.com", "MakerWorld"), ("CULTS3D.com", "cults3d.com", "Cults3D"),
    ("files.thangs.com", "thangs.com", "Thangs"),
    ("myminifactory.com", "myminifactory.com", "MyMiniFactory")])
def test_allowed_sites_normalised(data, host, key, name):
    r = service.register_downloaded_model(_file(data, "c.3mf"), host)
    assert (r["site"], r["site_name"]) == (key, name)


@pytest.mark.parametrize("url,expected", [
    ("https://www.printables.com/model/1?a=b", "https://www.printables.com/model/1"),
    ("https://printables.com/model/1#frag", "https://printables.com/model/1"),
    ("http://printables.com/model/1", None),
    ("https://evil.example/model/1", None),
    ("https://printables.com.evil.example/m", None),
    ("https://user:pw@printables.com/m", None),
    ("https://thingiverse.com/thing:1", None),
    ("not a url", None), (None, None)])
def test_page_url_normalisation(data, url, expected):
    r = service.register_downloaded_model(_file(data, "c.3mf"), "printables.com", url)
    assert _source(r["project_id"])["page_url"] == expected


def test_reregister_is_idempotent(data):
    p = _file(data, "c.3mf")
    a = service.register_downloaded_model(p, "printables.com")
    b = service.register_downloaded_model(p, "makerworld.com")
    assert a["project_id"] == b["project_id"] and _rows() == (1, 1)
    assert _source(a["project_id"])["site"] == "makerworld.com"


def test_route_success_auth_and_error_maps(data, monkeypatch):
    p = _file(data, "c.3mf")
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        route = "/library/register_download"
        assert _request(port, route, {"path": p, "site": "printables.com"}, "wrong")[0] == 401
        st, body = _request(port, route, {"path": p, "site": "printables.com",
                                          "page_url": "https://printables.com/model/1?x=1"}, token)
        assert st == 200 and body["ok"] and body["sha256"]
        assert str(data) not in repr(body) and "x=1" not in repr(body)
        for bad in ({"site": "printables.com"}, {"path": p}, {"path": 5, "site": "printables.com"},
                    {"path": p, "site": ["printables.com"]},
                    {"path": p, "site": "printables.com", "page_url": 7},
                    {"path": "x" * 5000, "site": "printables.com"},
                    {"path": p, "site": "s" * 300},
                    {"path": p, "site": "printables.com", "page_url": "h" * 3000}):
            assert _request(port, route, bad, token)[0] == 400, bad
        for bad in ({"path": p, "site": "evil.example"},
                    {"path": _file(data, "z.zip", b"x"), "site": "printables.com"},
                    {"path": _file(data, "n.3mf", b"not a zip"), "site": "printables.com"},
                    {"path": str(data / "missing.3mf"), "site": "printables.com"}):
            st, body = _request(port, route, bad, token)
            assert st == 422 and body["refusal"] == "DownloadRefused", bad
            assert str(data) not in repr(body)
        assert _rows() == (1, 1)
    finally:
        httpd.shutdown()


def test_file_in_controlled_folder_is_accepted(tmp_path, monkeypatch):
    root = tmp_path / "model-downloads"
    root.mkdir()
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SNAPSTUDIO_MODEL_DOWNLOADS_DIR", str(root))
    r = service.register_downloaded_model(_file(root, "cube.3mf"), "printables.com")
    assert r["ok"] is True


def test_nested_file_in_controlled_folder_is_accepted(tmp_path, monkeypatch):
    root = tmp_path / "model-downloads"
    (root / "sub").mkdir(parents=True)
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SNAPSTUDIO_MODEL_DOWNLOADS_DIR", str(root))
    assert service.register_downloaded_model(_file(root / "sub", "c.3mf"), "printables.com")["ok"]


def test_file_elsewhere_is_refused_with_no_rows(tmp_path, monkeypatch):
    root = tmp_path / "model-downloads"
    root.mkdir()
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SNAPSTUDIO_MODEL_DOWNLOADS_DIR", str(root))
    with pytest.raises(service.DownloadRefused):
        service.register_downloaded_model(_file(tmp_path, "elsewhere.3mf"), "printables.com")
    assert _rows() == (0, 0)


def test_sibling_folder_with_same_prefix_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "model-downloads"
    other = tmp_path / "model-downloads-evil"
    root.mkdir(); other.mkdir()
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SNAPSTUDIO_MODEL_DOWNLOADS_DIR", str(root))
    with pytest.raises(service.DownloadRefused):
        service.register_downloaded_model(_file(other, "x.3mf"), "printables.com")


def test_unset_downloads_folder_accepts_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("SNAPSTUDIO_MODEL_DOWNLOADS_DIR", raising=False)
    with pytest.raises(service.DownloadRefused):
        service.register_downloaded_model(_file(tmp_path, "x.3mf"), "printables.com")


def test_symlink_inside_folder_pointing_outside_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "model-downloads"
    root.mkdir()
    outside = _file(tmp_path, "outside.3mf")
    link = root / "link.3mf"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SNAPSTUDIO_MODEL_DOWNLOADS_DIR", str(root))
    with pytest.raises(service.DownloadRefused):
        service.register_downloaded_model(str(link), "printables.com")
    assert _rows() == (0, 0)


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are Windows-only")
def test_junction_inside_folder_pointing_outside_is_refused(tmp_path, monkeypatch):
    import subprocess
    root = tmp_path / "model-downloads"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _file(outside, "o.3mf")
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "j"), str(outside)],
                       capture_output=True)
    if r.returncode != 0:
        pytest.skip("cannot create a junction here")
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SNAPSTUDIO_MODEL_DOWNLOADS_DIR", str(root))
    with pytest.raises(service.DownloadRefused):
        service.register_downloaded_model(str(root / "j" / "o.3mf"), "printables.com")
    assert _rows() == (0, 0)
