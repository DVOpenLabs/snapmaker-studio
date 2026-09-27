"""CodeRabbit (commit 9b672e3): `request_validation._as_number` called
`float(v)` on a JSON integer with no length limit. A huge integer (e.g.
10**400) parses fine as a Python int but raises `OverflowError` on
`float(v)`, uncaught, so /local_spools/save (and every other numeric
validator built on `_as_number`) returned 500 storage_unavailable instead of
a clean 400. Each test is written to FAIL on the pre-fix code first.
"""
from __future__ import annotations

from snapstudio_api import request_validation as rv
from snapstudio_api.server import build_server
from tests.test_api import _request, _run

_HUGE = 10 ** 400


def test_as_number_rejects_a_huge_integer_with_validation_error_not_overflow():
    try:
        rv.bounded_weight({"starting_g": _HUGE}, "starting_g")
        assert False, "expected a ValidationError"
    except OverflowError:
        raise AssertionError("OverflowError leaked out of _as_number/bounded_weight")
    except rv.ValidationError:
        pass


def test_http_save_huge_remaining_g_is_400_invalid_weight_not_500(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, body = _request(port, "/local_spools/save",
                                {"host": "u1.local", "slot": 0, "remaining_g": _HUGE}, token)
        assert status == 400
        assert body == {"error": "invalid_weight",
                        "message": "Weight must be between 0 and 10000 grams."}
    finally:
        httpd.shutdown()


def test_http_mark_used_huge_used_g_is_400_invalid_weight_not_500(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, body = _request(port, "/local_spools/mark_used",
                                {"host": "u1.local", "slot": 0, "used_g": _HUGE}, token)
        assert status == 400
        assert body["error"] == "invalid_weight"
    finally:
        httpd.shutdown()


def test_http_nozzles_confirm_huge_diameter_is_400_invalid_diameters_not_500(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, body = _request(port, "/nozzles/confirm",
                                {"host": "u1.local", "diameters": [_HUGE], "expected_revision": 0},
                                token)
        assert status == 400
        assert body["error"] == "invalid_diameters"
    finally:
        httpd.shutdown()
