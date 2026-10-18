"""A saved job is trusted only as far as its files still are what they were.

Resuming a job after a restart reuses three files: the project that came in, the
prepared copy Studio wrote, and the sliced G-code that came back. Any of them can
be moved, deleted, regenerated or overwritten in between. This checks each file
against the size and hash recorded earlier, and says which of them it can vouch for.
It only reads; it never repeats preparation, slicing or sending.
"""
from __future__ import annotations

import hashlib
import os

import pytest

from snapstudio_core import job_identity


def _write(path, data: bytes):
    path.write_bytes(data)
    return {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _one(result, role="original"):
    return next(item for item in result["files"] if item["role"] == role)


def test_recording_a_file_returns_its_size_and_hash(tmp_path):
    f = tmp_path / "a.3mf"
    expected = _write(f, b"project bytes")
    out = job_identity.check([{"role": "original", "path": str(f)}])
    item = _one(out)
    assert item["status"] == "recorded"
    assert item["observed"] == expected


def test_an_unchanged_file_is_same(tmp_path):
    f = tmp_path / "a.3mf"
    expected = _write(f, b"project bytes")
    item = _one(job_identity.check([{"role": "original", "path": str(f), "expected": expected}]))
    assert item["status"] == "same"


def test_a_file_changed_in_place_is_changed_even_at_the_same_size(tmp_path):
    f = tmp_path / "a.3mf"
    expected = _write(f, b"aaaa")
    f.write_bytes(b"bbbb")
    item = _one(job_identity.check([{"role": "original", "path": str(f), "expected": expected}]))
    assert item["status"] == "changed"
    assert item["observed"]["size_bytes"] == expected["size_bytes"]


def test_a_missing_file_is_missing_not_changed(tmp_path):
    expected = {"size_bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}
    item = _one(job_identity.check([{"role": "sliced", "path": str(tmp_path / "gone.gcode"), "expected": expected}]), "sliced")
    assert item["status"] == "missing"
    assert "observed" not in item or item["observed"] is None


def test_a_directory_in_its_place_is_unreadable(tmp_path):
    d = tmp_path / "a.3mf"
    d.mkdir()
    expected = {"size_bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}
    item = _one(job_identity.check([{"role": "original", "path": str(d), "expected": expected}]))
    assert item["status"] == "unreadable"


def test_a_file_too_large_to_hash_is_unverified_never_same(tmp_path, monkeypatch):
    monkeypatch.setattr(job_identity, "MAX_HASH_BYTES", 4)
    f = tmp_path / "big.gcode"
    f.write_bytes(b"0123456789")
    item = _one(job_identity.check([{"role": "sliced", "path": str(f), "expected": {"size_bytes": 10, "sha256": None}}]), "sliced")
    assert item["status"] == "unverified"
    assert item["observed"] == {"size_bytes": 10, "sha256": None}


def test_a_recorded_hash_with_a_different_size_is_changed_without_hashing(tmp_path):
    f = tmp_path / "a.3mf"
    expected = _write(f, b"abc")
    f.write_bytes(b"abcd")
    item = _one(job_identity.check([{"role": "original", "path": str(f), "expected": expected}]))
    assert item["status"] == "changed"


def test_roles_stay_apart_and_order_is_kept(tmp_path):
    a = tmp_path / "a.3mf"; b = tmp_path / "b.3mf"; c = tmp_path / "c.gcode"
    ea, eb, ec = _write(a, b"1"), _write(b, b"2"), _write(c, b"3")
    out = job_identity.check([
        {"role": "original", "path": str(a), "expected": ea},
        {"role": "prepared", "path": str(b), "expected": ec},   # wrong identity on purpose
        {"role": "sliced", "path": str(c), "expected": ec},
    ])
    assert [i["role"] for i in out["files"]] == ["original", "prepared", "sliced"]
    assert [i["status"] for i in out["files"]] == ["same", "changed", "same"]


def test_unknown_role_and_too_many_entries_are_refused(tmp_path):
    with pytest.raises(ValueError):
        job_identity.check([{"role": "other", "path": str(tmp_path / "x")}])
    with pytest.raises(ValueError):
        job_identity.check([{"role": "original", "path": str(tmp_path / "x")}] * (job_identity.MAX_ENTRIES + 1))


def test_a_malformed_expectation_is_refused_not_treated_as_a_match(tmp_path):
    f = tmp_path / "a.3mf"; f.write_bytes(b"x")
    with pytest.raises(ValueError):
        job_identity.check([{"role": "original", "path": str(f), "expected": {"size_bytes": "big", "sha256": 5}}])


def test_checking_never_modifies_the_file(tmp_path):
    f = tmp_path / "a.3mf"
    expected = _write(f, b"keep me")
    before = (f.read_bytes(), os.stat(f).st_mtime_ns)
    job_identity.check([{"role": "original", "path": str(f), "expected": expected}])
    assert (f.read_bytes(), os.stat(f).st_mtime_ns) == before


def test_the_http_route_answers_and_refuses_a_bad_request(tmp_path):
    """The route is wired: a good call returns the report, a malformed one is a 400, not a 500."""
    import json
    import threading
    import urllib.error
    import urllib.request

    from snapstudio_api import server

    httpd, token = server.build_server("127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/job_check"
        f = tmp_path / "a.3mf"
        expected = _write(f, b"bytes")

        def post(body):
            req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "X-Auth-Token": token})
            return urllib.request.urlopen(req, timeout=5)

        ok = json.loads(post({"files": [{"role": "original", "path": str(f), "expected": expected}]}).read())
        assert ok["files"][0]["status"] == "same"
        with pytest.raises(urllib.error.HTTPError) as bad:
            post({"files": [{"role": "nonsense", "path": str(f)}]})
        assert bad.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as missing:
            post({})
        assert missing.value.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_file_that_cannot_be_opened_is_unreadable_even_when_its_size_differs(tmp_path, monkeypatch):
    f = tmp_path / "a.3mf"
    expected = _write(f, b"abc")
    f.write_bytes(b"abcd")
    real_open = open

    def denied(path, *a, **k):
        if str(path) == str(f):
            raise PermissionError("denied")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", denied)
    item = _one(job_identity.check([{"role": "original", "path": str(f), "expected": expected}]))
    assert item["status"] == "unreadable"


def test_an_oversize_file_that_cannot_be_opened_is_unreadable_not_unverified(tmp_path, monkeypatch):
    f = tmp_path / "big.gcode"
    f.write_bytes(b"0123456789")
    monkeypatch.setattr(job_identity, "MAX_HASH_BYTES", 4)
    real_open = open
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: (_ for _ in ()).throw(PermissionError()) if str(p) == str(f) else real_open(p, *a, **k))
    item = _one(job_identity.check([{"role": "sliced", "path": str(f), "expected": {"size_bytes": 10, "sha256": None}}]), "sliced")
    assert item["status"] == "unreadable"


def test_a_missing_files_key_is_named_plainly():
    with pytest.raises(ValueError, match="list"):
        job_identity.check(None)
