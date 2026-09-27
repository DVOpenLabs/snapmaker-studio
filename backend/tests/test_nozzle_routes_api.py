"""The frozen `/nozzles/*` HTTP contract: auth, the error map, privacy (never
echo the submitted host or a DB path), and the local-spool tri-state text
field clearing fix (A1.4/A2.2/A3.3) at the same HTTP layer.
"""
from __future__ import annotations

import threading

from snapstudio_api.server import build_server
from tests.test_api import _request, _run


def test_nozzles_status_requires_the_auth_token(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, _ = _request(port, "/nozzles/status", {"host": "u1.local"}, "wrong-token")
        assert status == 401
        status, _ = _request(port, "/nozzles/confirm",
                             {"host": "u1.local", "diameters": [0.4], "expected_revision": 0},
                             "wrong-token")
        assert status == 401
        status, _ = _request(port, "/nozzles/clear",
                             {"host": "u1.local", "expected_revision": 0}, "wrong-token")
        assert status == 401
    finally:
        httpd.shutdown()


def test_nozzles_confirm_then_status_then_stale_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, body = _request(port, "/nozzles/confirm", {
            "host": "U1.Local", "diameters": [0.4, 0.6, None], "expected_revision": 0,
        }, token)
        assert status == 200
        assert body["host"] == "u1.local"        # canonicalised server-side
        assert body["revision"] == 1
        # B2 fix (v1.2 round-1): row count now floors at the U1 profile's own
        # tool count (4) when nothing else is known (this "u1.local" is not a
        # real reachable printer in this test) — so the stored 3 confirmed
        # toolheads plus one profile-only "unknown" toolhead 3, not just the
        # 3 that were confirmed.
        assert [t["diameter"] for t in body["toolheads"]] == [0.4, 0.6, None, None]
        assert body["toolhead_count_source"] == "profile"

        status, body = _request(port, "/nozzles/status", {"host": "u1.local"}, token)
        assert status == 200 and body["revision"] == 1

        # A stale expected_revision is refused with the fixed message and the
        # current revision — never the host, never a path, never an exception.
        status, body = _request(port, "/nozzles/confirm",
                                {"host": "u1.local", "diameters": [0.4], "expected_revision": 0},
                                token)
        assert status == 409
        assert body == {"error": "stale",
                        "message": "Nozzle notes changed elsewhere. Reload and try again.",
                        "current_revision": 1}

        status, body = _request(port, "/nozzles/clear",
                                {"host": "u1.local", "expected_revision": 1}, token)
        assert status == 200 and body["revision"] == 2
        assert all(t["diameter"] is None for t in body["toolheads"])
    finally:
        httpd.shutdown()


def test_nozzles_confirm_rejects_out_of_bounds_diameters_with_the_fixed_message(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, body = _request(port, "/nozzles/confirm",
                                {"host": "u1.local", "diameters": [3.0], "expected_revision": 0},
                                token)
        assert status == 400
        assert body["error"] == "invalid_diameters"
        assert body["message"] == "Nozzle sizes must be between 0 and 2 mm, one per toolhead, up to 8."
    finally:
        httpd.shutdown()


def test_nozzles_status_rejects_a_malformed_host_and_never_echoes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        submitted = "http://sneaky-internal-host.example/evil"
        status, body = _request(port, "/nozzles/status", {"host": submitted}, token)
        assert status == 400
        assert body["error"] == "invalid_host"
        blob = str(body)
        assert submitted not in blob and "sneaky-internal-host" not in blob
    finally:
        httpd.shutdown()


# --- local spool text-field clearing (A1.4/A2.2/A3.3) at the HTTP layer ----

def test_local_spool_save_clears_a_text_field_with_empty_string_not_null(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        _request(port, "/local_spools/save", {
            "host": "u1.local", "slot": 0, "material": "PLA", "vendor": "Snapmaker",
            "starting_g": 1000.0, "remaining_g": 700.0,
        }, token)
        # Omitting vendor entirely must preserve it...
        status, updated = _request(port, "/local_spools/save",
                                   {"host": "u1.local", "slot": 0, "notes": "warped a bit"}, token)
        assert status == 200
        row = [r for r in updated["rows"] if r["slot"] == 0][0]
        assert row["vendor"] == "Snapmaker"
        # ...while an explicit empty string clears it, and clearing is not an
        # identity change: the remaining weight survives.
        status, updated = _request(port, "/local_spools/save",
                                   {"host": "u1.local", "slot": 0, "vendor": ""}, token)
        assert status == 200
        row = [r for r in updated["rows"] if r["slot"] == 0][0]
        assert row["vendor"] is None
        assert row["remaining_g"] == 700.0
    finally:
        httpd.shutdown()


def test_local_spool_save_rejects_a_malformed_colour_with_the_fixed_message(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, body = _request(port, "/local_spools/save",
                                {"host": "u1.local", "slot": 0, "color": "not-a-colour"}, token)
        assert status == 400
        assert body == {"error": "invalid_color",
                        "message": "Colour must be a hex value like #1A2B3C, or empty."}
    finally:
        httpd.shutdown()


def test_local_spool_save_rejects_weight_over_the_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, body = _request(port, "/local_spools/save",
                                {"host": "u1.local", "slot": 0, "starting_g": 20000.0}, token)
        assert status == 400 and body["error"] == "invalid_weight"
    finally:
        httpd.shutdown()
