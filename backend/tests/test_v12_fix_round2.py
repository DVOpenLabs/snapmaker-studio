"""v1.2 fix round 2 (Opus N1/N2/N4, Sol 3/5) — backend items R2-B1..R2-B5.
Each test is written to FAIL against the round-1 code first, then the fix
makes it pass; this file is that record.
"""
from __future__ import annotations

from snapstudio_api import service
from snapstudio_core import (
    material_providers as providers, nozzle_confirm as nc, post_slice,
    preflight as pf, send_check, send_state,
)


# --- R2-B1: null ("not sure") entries never render as "None mm" -------------

def test_preflight_unknown_evidence_never_says_none_for_a_null_confirmed_entry():
    """UNKNOWN branch (a null entry means an unrelated position is not fully
    known): confirmed [0.4, None, 0.4, 0.4] -> evidence says "not sure", never
    "None"."""
    project = {"nozzle_diameters": {"value": ["0.4"], "confidence": "confirmed"}}
    printer = {"nozzle_diameters": [0.4, None, 0.4, 0.4], "nozzle_confirmed_by": "user"}
    out = pf.evaluate(project, printer)
    check = next(c for c in out["checks"] if c["id"] == "nozzle.match")
    assert "not sure" in check["evidence"]
    assert "None" not in check["evidence"]


def test_preflight_attention_evidence_never_says_none_for_a_null_confirmed_entry():
    """ATTENTION branch (a proven mismatch elsewhere) with a null entry among
    the per-toolhead values shown in the evidence text."""
    project = {"nozzle_diameters": {"value": ["0.4", "0.6"], "confidence": "confirmed"},
              "nozzle_diameters_by_toolhead": {"value": ["0.4", "0.6", "0.4"], "confidence": "confirmed"}}
    printer = {"nozzle_diameters": [0.4, 0.8, None], "nozzle_confirmed_by": "user"}
    out = pf.evaluate(project, printer)
    check = next(c for c in out["checks"] if c["id"] == "nozzle.match")
    assert check["result"] == pf.ATTENTION
    assert "not sure" in check["evidence"]
    assert "None" not in check["evidence"]


def test_post_slice_attention_evidence_never_says_none_for_a_null_confirmed_entry():
    facts = {"available": True, "nozzle_diameter_mm": [0.4, 0.4, 0.4, 0.4], "tools_used": None}
    printer = {"nozzle_diameters": [0.4, None, 0.6, 0.4], "nozzle_confirmed_by": "user"}
    out = post_slice.analyse(facts, printer)
    check = next(c for c in out["checks"] if c["id"] == "gcode.nozzle")
    assert check["result"] == post_slice.ATTENTION
    assert "not sure" in check["evidence"]
    assert "None" not in check["evidence"]


# --- R2-B2: ordered path — a position with no expected size is not a mismatch

def test_match_verdict_ordered_skips_positions_beyond_the_wanted_list():
    """G-code nozzle list [0.4], tools_used None (-> required = all reported
    positions), printer 4x0.4 -> OK: positions 1-3 have no expected size at
    all (beyond `ordered`'s length) and must be skipped, never ATTENTION."""
    assert nc.match_verdict([0, 1, 2, 3], [0.4], {"0.4"}, [0.4, 0.4, 0.4, 0.4]) == nc.OK


def test_post_slice_v1_1_0_parity_short_ordered_list_full_printer_report():
    facts = {"available": True, "nozzle_diameter_mm": [0.4], "tools_used": None}
    printer = {"nozzle_diameters": [0.4, 0.4, 0.4, 0.4], "nozzle_confirmed_by": "printer"}
    out = post_slice.analyse(facts, printer)
    check = next(c for c in out["checks"] if c["id"] == "gcode.nozzle")
    assert check["result"] == post_slice.OK


# --- R2-B3: nozzle_notes fingerprint tracks the STORED snapshot -------------

def test_nozzle_notes_fingerprint_changes_when_the_stored_note_changes_even_though_live_wins():
    printer_with_note = {
        "reachable": True, "nozzle_confirmed_by": "printer",
        "nozzle_diameters": [0.4, 0.4, 0.4, 0.4], "_live_nozzle_diameters": [0.4, 0.4, 0.4, 0.4],
        "nozzle_conflicts": [], "nozzle_revision": 3,
        "_stored_nozzle_confirmations": {0: {"diameter": 0.4, "confirmed_at": "2026-01-01T00:00:00Z"},
                                        1: {"diameter": 0.4, "confirmed_at": "2026-01-01T00:00:00Z"},
                                        2: {"diameter": 0.4, "confirmed_at": "2026-01-01T00:00:00Z"},
                                        3: {"diameter": 0.4, "confirmed_at": "2026-01-01T00:00:00Z"}},
    }
    printer_no_note = {
        "reachable": True, "nozzle_confirmed_by": "printer",
        "nozzle_diameters": [0.4, 0.4, 0.4, 0.4], "_live_nozzle_diameters": [0.4, 0.4, 0.4, 0.4],
        "nozzle_conflicts": [], "nozzle_revision": 0,
        "_stored_nozzle_confirmations": {},
    }
    facts = {"file": "job.gcode"}
    before = send_state.fingerprint(facts, printer_no_note)
    after = send_state.fingerprint(facts, printer_with_note)
    found = {c["part"] for c in send_state.changes(before, after)}
    assert "nozzle_notes" in found


def test_nozzle_notes_fingerprint_is_identical_for_identical_inputs():
    printer = {
        "reachable": True, "nozzle_confirmed_by": "printer",
        "nozzle_diameters": [0.4, 0.4], "_live_nozzle_diameters": [0.4, 0.4],
        "nozzle_conflicts": [], "nozzle_revision": 2,
        "_stored_nozzle_confirmations": {0: {"diameter": 0.4, "confirmed_at": "2026-01-01T00:00:00Z"},
                                        1: {"diameter": 0.4, "confirmed_at": "2026-01-01T00:00:00Z"}},
    }
    facts = {"file": "job.gcode"}
    a = send_state.fingerprint(facts, printer)
    b = send_state.fingerprint(facts, dict(printer))
    assert a["hashes"]["nozzle_notes"] == b["hashes"]["nozzle_notes"]
    assert send_state.changes(a, b) == []


def test_nozzle_notes_fingerprint_still_excludes_observed_at_and_bare_live_value():
    printer_a = {
        "reachable": True, "nozzle_confirmed_by": "printer",
        "nozzle_diameters": [0.4], "_live_nozzle_diameters": [0.4],
        "nozzle_conflicts": [], "nozzle_revision": 1, "observed_at": 111.0,
        "_stored_nozzle_confirmations": {0: {"diameter": 0.6, "confirmed_at": "2026-01-01T00:00:00Z"}},
    }
    printer_b = dict(printer_a, observed_at=222.0)
    facts = {"file": "job.gcode"}
    a = send_state.fingerprint(facts, printer_a)
    b = send_state.fingerprint(facts, printer_b)
    assert a["hashes"]["nozzle_notes"] == b["hashes"]["nozzle_notes"]


# --- R2-B4: exclusion tests use a DISTINCTIVE confirmation + note -----------

_DISTINCTIVE_DIAMETERS = [0.35, 0.45, 0.55, 0.65]
_DISTINCTIVE_NOTE = "zz-distinctive-note-x9k2"


def test_diagnostics_excludes_a_distinctive_seeded_confirmation_and_note(tmp_path, monkeypatch):
    from snapstudio_core import diagnostics as diag, library, moonraker

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(moonraker, "probe", lambda host, port: {"reachable": False})
    conn = service._conn()
    try:
        library.upsert_spool(conn, host="u1.local", slot=0, material="PLA", subtype=None,
                             color=None, vendor=None, starting_g=None, remaining_g=None,
                             remaining_quality=None, remaining_as_of=None,
                             notes=_DISTINCTIVE_NOTE, updated_at="2026-01-01T00:00:00Z")
        nc.confirm(conn, "u1.local", 7125, _DISTINCTIVE_DIAMETERS, 0, "2026-01-01T00:00:00Z")
    finally:
        conn.close()

    bundle = diag.collect(host="u1.local", port=7125)
    blob = str(bundle)
    for value in _DISTINCTIVE_DIAMETERS:
        assert str(value) not in blob
    assert _DISTINCTIVE_NOTE not in blob
    assert "nozzle_confirm" not in blob
    assert "confirmed_nozzle" not in blob


def test_verify_printer_excludes_a_distinctive_seeded_confirmation_and_note(tmp_path, monkeypatch):
    from snapstudio_core import hardware_verify, library, moonraker

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(moonraker, "probe", lambda host, port: {"reachable": False})
    conn = service._conn()
    try:
        library.upsert_spool(conn, host="u1.local", slot=0, material="PLA", subtype=None,
                             color=None, vendor=None, starting_g=None, remaining_g=None,
                             remaining_quality=None, remaining_as_of=None,
                             notes=_DISTINCTIVE_NOTE, updated_at="2026-01-01T00:00:00Z")
        nc.confirm(conn, "u1.local", 7125, _DISTINCTIVE_DIAMETERS, 0, "2026-01-01T00:00:00Z")
    finally:
        conn.close()

    bundle = hardware_verify.build_evidence("u1.local", port=7125)
    blob = str(bundle)
    for value in _DISTINCTIVE_DIAMETERS:
        assert str(value) not in blob
    assert _DISTINCTIVE_NOTE not in blob
    assert "nozzle_confirm" not in blob
    assert "confirmed_nozzle" not in blob


# --- R2-B5: match_verdict matrix additions + a tighter send_check assertion -

def test_match_verdict_mixed_size_swap_is_attention():
    # ordered swap: wanted [0.4,0.6], reported [0.6,0.4] -> ATTENTION.
    assert nc.match_verdict([0, 1], [0.4, 0.6], {"0.4", "0.6"}, [0.6, 0.4]) == nc.ATTENTION


def test_match_verdict_mixed_size_all_known_matching_set_is_never_ok():
    assert nc.match_verdict([0, 1], None, {"0.4", "0.6"}, [0.4, 0.6]) == nc.UNKNOWN


# --- R2-B6: /nozzles/status probe=false skips the printer entirely --------

def test_nozzle_status_probe_false_skips_moonraker_entirely_and_is_instant(tmp_path, monkeypatch):
    from snapstudio_core import moonraker

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))

    def boom(*a, **k):
        raise AssertionError("moonraker must not be called at all when probe=False")

    monkeypatch.setattr(moonraker, "probe", boom)
    monkeypatch.setattr(moonraker, "machine_info", boom)
    monkeypatch.setattr(moonraker, "capabilities", boom)

    conn = service._conn()
    try:
        nc.confirm(conn, "u1.local", 7125, [0.4, 0.6], 0, "2026-01-01T00:00:00Z")
    finally:
        conn.close()

    out = service.nozzle_status("u1.local", 7125, probe=False)
    assert out["reachable"] is False
    assert out["live"] is None
    assert out["live_error"] == "not_checked"
    # Stored + profile rows still returned instantly.
    assert len(out["toolheads"]) == 4
    assert out["toolhead_count_source"] == "profile"
    assert [t["diameter"] for t in out["toolheads"]] == [0.4, 0.6, None, None]


def test_nozzle_status_probe_defaults_to_true():
    import inspect
    assert inspect.signature(service.nozzle_status).parameters["probe"].default is True


def test_nozzles_status_route_forwards_probe_false(tmp_path, monkeypatch):
    from snapstudio_api.server import build_server
    from snapstudio_core import moonraker
    from tests.test_api import _request, _run

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))

    def boom(*a, **k):
        raise AssertionError("moonraker must not be called at all when probe=false")

    monkeypatch.setattr(moonraker, "probe", boom)
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, body = _request(port, "/nozzles/status",
                                {"host": "u1.local", "probe": False}, token)
        assert status == 200
        assert body["live_error"] == "not_checked"
    finally:
        httpd.shutdown()


def test_b1_through_send_check_asserts_the_nozzle_check_explicitly():
    """R2-B5: replaces the earlier weak assertion (merely 'no title contains
    does not match') with an explicit check id + result lookup."""
    facts = {"available": True, "nozzle_diameter_mm": [0.4, 0.6], "tools_used": [0]}
    printer = {"reachable": True, "nozzle_diameters": [0.4], "nozzle_confirmed_by": "printer"}
    from snapstudio_core import post_slice as ps
    checks = ps.analyse(facts, printer)["checks"]
    nozzle_check = next(c for c in checks if c["id"] == "gcode.nozzle")
    assert nozzle_check["result"] == ps.OK
    report = send_check.evaluate(facts, printer)
    assert not any(i["kind"] in (send_check.BLOCKER, send_check.WARNING)
                  and "nozzle" in (i.get("source") or "").lower() for i in report["items"])
