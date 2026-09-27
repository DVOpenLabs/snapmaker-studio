"""CodeRabbit PR #41 (Major): the spool editor could not clear a weight.
`request_validation.bounded_weight` collapsed an explicit "" (clear) into the
`default` (None, "preserve"), and `service.save_local_spool` had no way to
tell "not sent" from "explicitly cleared" for starting_g/remaining_g — so
emptying the field in the editor silently kept the old figure (and its
"entered by you" label), and the send check kept using it.

Fix: the same tri-state rule the text fields already use (A3.3) — MISSING/
null preserves, "" clears (store NULL; clearing remaining_g also resets
remaining_quality/remaining_as_of to NULL/untracked), a number in [0, 10000]
sets. Each test here is written to FAIL on the pre-fix code first.
"""
from __future__ import annotations

import pytest

from snapstudio_api import request_validation as rv, service
from snapstudio_core import material_providers as providers


# --- request_validation.bounded_weight: the tri-state contract --------------

def test_bounded_weight_missing_key_is_the_missing_sentinel():
    assert rv.bounded_weight({}, "starting_g") is rv.MISSING


def test_bounded_weight_explicit_null_is_none():
    assert rv.bounded_weight({"starting_g": None}, "starting_g") is None


def test_bounded_weight_empty_string_is_the_clear_marker():
    assert rv.bounded_weight({"starting_g": ""}, "starting_g") == ""


def test_bounded_weight_whitespace_only_string_is_also_the_clear_marker():
    assert rv.bounded_weight({"starting_g": "   "}, "starting_g") == ""


def test_bounded_weight_a_real_number_is_returned():
    assert rv.bounded_weight({"starting_g": 500.0}, "starting_g") == 500.0


def test_bounded_weight_rejects_a_non_numeric_non_empty_string():
    with pytest.raises(rv.ValidationError):
        rv.bounded_weight({"starting_g": "not a number"}, "starting_g")


def test_bounded_weight_rejects_out_of_range():
    with pytest.raises(rv.ValidationError):
        rv.bounded_weight({"starting_g": 20000.0}, "starting_g")
    with pytest.raises(rv.ValidationError):
        rv.bounded_weight({"starting_g": -1.0}, "starting_g")


# --- service.save_local_spool: clearing a weight ----------------------------

def test_clearing_remaining_g_with_empty_string_resets_quality_and_as_of(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    service.save_local_spool("u1.local", 0, material="PLA", starting_g=1000.0, remaining_g=800.0)
    rows = service.save_local_spool("u1.local", 0, remaining_g="")
    row = next(r for r in rows if r["slot"] == 0)
    assert row["remaining_g"] is None
    assert row["remaining_quality"] == providers.UNTRACKED
    assert row["remaining_as_of"] is None
    # An unrelated field (material) is untouched by clearing the weight.
    assert row["material"] == "PLA"


def test_clearing_starting_g_with_empty_string_stores_null(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    service.save_local_spool("u1.local", 0, material="PLA", starting_g=1000.0, remaining_g=800.0)
    rows = service.save_local_spool("u1.local", 0, starting_g="")
    row = next(r for r in rows if r["slot"] == 0)
    assert row["starting_g"] is None
    # Clearing starting_g alone must not touch remaining_g — it is not an
    # identity change, exactly like clearing a text field.
    assert row["remaining_g"] == 800.0
    assert row["remaining_quality"] == providers.USER_CONFIRMED


def test_omitting_remaining_g_entirely_still_preserves_it(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    service.save_local_spool("u1.local", 0, material="PLA", starting_g=1000.0, remaining_g=800.0)
    rows = service.save_local_spool("u1.local", 0, notes="a bit warped")
    row = next(r for r in rows if r["slot"] == 0)
    assert row["remaining_g"] == 800.0
    assert row["remaining_quality"] == providers.USER_CONFIRMED


def test_explicit_null_remaining_g_also_preserves_it(tmp_path, monkeypatch):
    """None (the collapsed shape MISSING becomes at the server boundary) must
    behave identically to the key being absent — both mean "preserve"."""
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    service.save_local_spool("u1.local", 0, material="PLA", starting_g=1000.0, remaining_g=800.0)
    rows = service.save_local_spool("u1.local", 0, remaining_g=None)
    row = next(r for r in rows if r["slot"] == 0)
    assert row["remaining_g"] == 800.0


def test_a_fresh_remaining_g_still_sets_user_confirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    service.save_local_spool("u1.local", 0, material="PLA", starting_g=1000.0, remaining_g=800.0)
    rows = service.save_local_spool("u1.local", 0, remaining_g=750.0)
    row = next(r for r in rows if r["slot"] == 0)
    assert row["remaining_g"] == 750.0
    assert row["remaining_quality"] == providers.USER_CONFIRMED


# --- HTTP level --------------------------------------------------------------

def test_http_save_clears_remaining_g_and_the_send_check_stops_using_it(tmp_path, monkeypatch):
    from snapstudio_api.server import build_server
    from tests.test_api import _request, _run

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        _request(port, "/local_spools/save", {
            "host": "u1.local", "slot": 0, "material": "PLA",
            "starting_g": 1000.0, "remaining_g": 800.0,
        }, token)
        status, body = _request(port, "/local_spools/save",
                                {"host": "u1.local", "slot": 0, "remaining_g": ""}, token)
        assert status == 200
        row = next(r for r in body["rows"] if r["slot"] == 0)
        assert row["remaining_g"] is None
        assert row["remaining_quality"] == "unknown"

        # material_providers.local_spools must now report it untracked, not
        # carrying the stale "800g entered by you" figure forward.
        state = service.local_spools("u1.local")
        assert state["slots"][0]["remaining_g"] is None
        assert state["slots"][0]["remaining_quality"] == providers.UNTRACKED
    finally:
        httpd.shutdown()


def test_http_save_clears_starting_g(tmp_path, monkeypatch):
    from snapstudio_api.server import build_server
    from tests.test_api import _request, _run

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        _request(port, "/local_spools/save", {
            "host": "u1.local", "slot": 0, "material": "PLA", "starting_g": 1000.0,
        }, token)
        status, body = _request(port, "/local_spools/save",
                                {"host": "u1.local", "slot": 0, "starting_g": ""}, token)
        assert status == 200
        row = next(r for r in body["rows"] if r["slot"] == 0)
        assert row["starting_g"] is None
    finally:
        httpd.shutdown()


def test_http_save_null_still_preserves_the_weight(tmp_path, monkeypatch):
    from snapstudio_api.server import build_server
    from tests.test_api import _request, _run

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        _request(port, "/local_spools/save", {
            "host": "u1.local", "slot": 0, "material": "PLA",
            "starting_g": 1000.0, "remaining_g": 800.0,
        }, token)
        status, body = _request(port, "/local_spools/save",
                                {"host": "u1.local", "slot": 0, "remaining_g": None,
                                 "notes": "warped"}, token)
        assert status == 200
        row = next(r for r in body["rows"] if r["slot"] == 0)
        assert row["remaining_g"] == 800.0
        assert row["notes"] == "warped"
    finally:
        httpd.shutdown()


def test_http_save_invalid_weight_string_is_still_400_invalid_weight(tmp_path, monkeypatch):
    from snapstudio_api.server import build_server
    from tests.test_api import _request, _run

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, body = _request(port, "/local_spools/save",
                                {"host": "u1.local", "slot": 0, "remaining_g": "not a number"},
                                token)
        assert status == 400
        assert body == {"error": "invalid_weight",
                        "message": "Weight must be between 0 and 10000 grams."}
    finally:
        httpd.shutdown()
