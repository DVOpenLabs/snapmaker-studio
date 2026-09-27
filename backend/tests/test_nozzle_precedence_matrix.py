"""End-to-end precedence and conflict reporting across preflight/post_slice/
send_check, through the actual service layer and stored confirmations —
not just the pure `nozzle_confirm.match_verdict` matrix in isolation.
"""
from __future__ import annotations

from snapstudio_api import service
from snapstudio_core import nozzle_confirm as nc


def _stub_moonraker(monkeypatch, *, reachable=True, nozzle_diameters=None,
                    toolhead_count=4):
    from snapstudio_core import moonraker

    def fake_probe(host, port):
        return {"reachable": reachable, "port": port}

    def fake_capabilities(host, port):
        return {"toolhead_count": toolhead_count, "bed_mm": {"x": 270, "y": 270},
                "klipper_objects": []}

    def fake_machine_info(host, port):
        return {"nozzle_diameters": nozzle_diameters} if nozzle_diameters else {}

    def fake_status(host, port, tool_count=None):
        return {"print_state": "standby"}

    def fake_loaded_filaments(host, port):
        return None

    monkeypatch.setattr(moonraker, "probe", fake_probe)
    monkeypatch.setattr(moonraker, "capabilities", fake_capabilities)
    monkeypatch.setattr(moonraker, "machine_info", fake_machine_info)
    monkeypatch.setattr(moonraker, "status", fake_status)
    monkeypatch.setattr(moonraker, "loaded_filaments", fake_loaded_filaments)


def test_preflight_uses_stored_confirmation_when_the_printer_reports_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, nozzle_diameters=None)
    conn = service._conn()
    try:
        nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
    finally:
        conn.close()

    facts = service.printer_facts("u1.local", 7125)
    assert facts["nozzle_diameters"] == [0.4]
    assert facts["nozzle_confirmed_by"] == "user"
    assert facts["nozzle_revision"] == 1


def test_preflight_live_reading_always_wins_over_a_stored_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, nozzle_diameters=[0.6])
    conn = service._conn()
    try:
        nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
    finally:
        conn.close()

    facts = service.printer_facts("u1.local", 7125)
    assert facts["nozzle_diameters"] == [0.6]
    assert facts["nozzle_confirmed_by"] == "printer"
    # A1.7: the disagreement is surfaced even though the caller asked for
    # nothing else — the live value is what is used, but the note that
    # disagrees with it is not silently dropped.
    assert facts["nozzle_conflicts"] == [
        {"toolhead": 0, "printer": 0.6, "confirmed": 0.4, "source": "stored",
         "confirmed_at": "2026-01-01T00:00:00Z"}]


def test_preflight_conflict_check_appears_even_though_live_matches_the_job(tmp_path, monkeypatch):
    """A1.7: 'even when live matches the job' — the conflict check fires on
    the stored-vs-live disagreement alone."""
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, nozzle_diameters=[0.4])
    conn = service._conn()
    try:
        nc.confirm(conn, "u1.local", 7125, [0.6], 0, "2026-01-01T00:00:00Z")
    finally:
        conn.close()

    facts = service.printer_facts("u1.local", 7125)
    from snapstudio_core import preflight as pf
    out = pf.evaluate({"nozzle_diameters": {"value": ["0.4"], "confidence": "confirmed"}}, facts)
    conflict = next((c for c in out["checks"] if c["id"] == "nozzle.confirmation_conflict"), None)
    assert conflict is not None
    assert conflict["result"] == pf.ATTENTION


def test_send_check_inherits_the_conflict_check_from_post_slice(tmp_path, monkeypatch):
    """A1.7: the check is emitted once in post_slice.analyse; send_check must
    not need its own copy to show it."""
    from snapstudio_core import send_check as sc

    printer = {"reachable": True, "nozzle_conflicts": [
        {"toolhead": 0, "printer": 0.4, "confirmed": 0.6, "source": "stored",
         "confirmed_at": "2026-01-01T00:00:00Z"}]}
    facts = {"available": True, "nozzle_diameter_mm": [0.4]}
    report = sc.evaluate(facts, printer)
    assert any(i["title"].startswith("Your nozzle note does not match") for i in report["items"])


def test_diagnostics_never_touches_local_spool_or_nozzle_tables(tmp_path, monkeypatch):
    """A1.10/A2.7 privacy requirement: a diagnostics bundle must exclude
    seeded notes and confirmations. `diagnostics._printer` reads the printer
    directly via moonraker and never joins local storage at all — this is a
    regression guard on that remaining true, not new exclusion logic."""
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, nozzle_diameters=None)
    conn = service._conn()
    try:
        from snapstudio_core import library
        library.upsert_spool(conn, host="u1.local", slot=0, material="A SECRET SPOOL NAME",
                             subtype=None, color=None, vendor=None, starting_g=None,
                             remaining_g=None, remaining_quality=None, remaining_as_of=None,
                             notes="a private note", updated_at="2026-01-01T00:00:00Z")
        nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
    finally:
        conn.close()

    from snapstudio_core import diagnostics as diag
    bundle = diag.collect(host="u1.local", port=7125)
    blob = str(bundle)
    assert "A SECRET SPOOL NAME" not in blob
    assert "a private note" not in blob
