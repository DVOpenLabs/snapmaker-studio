"""v1.2 fix round 1 (Opus BLOCK H1-H5/M1-M6/LOW, Sol BLOCK 3-7) — backend
items B1-B9. Each test reproduces the named failure against the pre-fix code
path, then locks in the corrected behaviour.
"""
from __future__ import annotations

import struct

import pytest

from snapstudio_api import service
from snapstudio_core import (
    library, material_providers as providers, nozzle_confirm as nc,
    post_slice, preflight as pf, send_check, send_state,
)
from snapstudio_core.stl_wrap import wrap_stl


def _sample_3mf(tmp_path) -> str:
    """A minimal, real U1 project — same construction test_api.py's own
    `_sample_u1` uses — so `preflight()` has a genuine 3MF to extract traits
    from rather than a fixture path that may not exist in this checkout."""
    head = b"\x00" * 80 + struct.pack("<I", 2)
    for v1, v2, v3 in [((0, 0, 0), (10, 0, 0), (0, 10, 0)),
                       ((0, 0, 0), (0, 10, 0), (0, 0, 10))]:
        head += struct.pack("<12fH", 0, 0, 0, *v1, *v2, *v3, 0)
    stl = tmp_path / "cube.stl"
    stl.write_bytes(head)
    out = tmp_path / "cube_U1.3mf"
    wrap_stl(str(stl)).save(out)
    return str(out)


def _stub_moonraker(monkeypatch, *, reachable=True, nozzle_diameters=None,
                    toolhead_count=4, caps_fails=False, machine_info_fails=False):
    from snapstudio_core import moonraker

    def fake_probe(host, port):
        return {"reachable": reachable, "port": port}

    def fake_capabilities(host, port):
        if caps_fails:
            raise moonraker.PrinterUnavailable("no capabilities")
        return {"toolhead_count": toolhead_count, "bed_mm": {"x": 270, "y": 270},
                "klipper_objects": []}

    def fake_machine_info(host, port):
        if machine_info_fails:
            raise moonraker.PrinterUnavailable("no system_info")
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


# --- B1: match_verdict false-OK / set-fallback -------------------------------

@pytest.mark.parametrize("required,ordered,wanted,reported,expected", [
    # Sol's job [0.4,0.6] tools_used [0] printer [0.4] -> OK (post_slice: the
    # unused toolhead's 0.6 must not matter at all).
    ([0], [0.4, 0.6], {"0.4", "0.6"}, [0.4], nc.OK),
    # A single project size S, printer reports S on one required position and
    # something ELSE on another required position -> ATTENTION, never OK
    # from mere set membership (Opus H1/Sol 3's false-OK bug).
    ([0, 1], None, {"0.4"}, [0.4, 0.6], nc.ATTENTION),
    # preflight unordered {0.4} vs printer [0.4,0.6,0.4,0.4] -> ATTENTION.
    ([0, 1, 2, 3], None, {"0.4"}, [0.4, 0.6, 0.4, 0.4], nc.ATTENTION),
    # 4x0.4 tools_used [0,1,2] vs stored [0.4,0.4,0.6,None] -> ATTENTION
    # (toolhead index 2 has 0.6; toolhead 3 is not required at all).
    ([0, 1, 2], [0.4, 0.4, 0.4, 0.4], {"0.4"}, [0.4, 0.4, 0.6, None], nc.ATTENTION),
    # Zero known required positions -> UNKNOWN (vacuous truth, A3.2).
    ([0, 1], None, {"0.4"}, [], nc.UNKNOWN),
    # Missing required position (prefix match) -> UNKNOWN.
    ([0, 1], [0.4, 0.4], {"0.4"}, [0.4], nc.UNKNOWN),
])
def test_match_verdict_matrix(required, ordered, wanted, reported, expected):
    assert nc.match_verdict(required, ordered, wanted, reported) == expected


def test_b1_through_preflight_single_size_false_ok():
    """The same bug, through preflight._nozzle: project wants one size, the
    printer answers that size on toolhead 0 and something else on toolhead 1
    — must be ATTENTION, never a false OK from set membership."""
    project = {"nozzle_diameters": {"value": ["0.4"], "confidence": "confirmed"}}
    printer = {"toolhead_count": 2, "nozzle_diameters": [0.4, 0.6],
              "nozzle_confirmed_by": "printer"}
    out = pf.evaluate(project, printer)
    check = next(c for c in out["checks"] if c["id"] == "nozzle.match")
    assert check["result"] == pf.ATTENTION


def test_b1_through_post_slice_unused_toolhead_never_blocks_a_match():
    """Sol's case through post_slice._nozzle: sliced for [0.4, 0.6], only
    toolhead 0 used, printer answers 0.4 for toolhead 0 -> OK."""
    facts = {"available": True, "nozzle_diameter_mm": [0.4, 0.6], "tools_used": [0]}
    printer = {"nozzle_diameters": [0.4], "nozzle_confirmed_by": "printer"}
    out = post_slice.analyse(facts, printer)
    check = next(c for c in out["checks"] if c["id"] == "gcode.nozzle")
    assert check["result"] == post_slice.OK


def test_b1_through_send_check_inherits_the_corrected_verdict():
    facts = {"available": True, "nozzle_diameter_mm": [0.4, 0.6], "tools_used": [0]}
    printer = {"reachable": True, "nozzle_diameters": [0.4], "nozzle_confirmed_by": "printer"}
    report = send_check.evaluate(facts, printer)
    assert not any("nozzle" in i["title"].lower() and i["kind"] != send_check.UNKNOWN
                  for i in report["items"] if "match" not in i["title"].lower())
    # No nozzle ATTENTION/BLOCKER item at all for this OK case.
    assert not any("does not match" in i["title"] for i in report["items"])


# --- B2: offline stored confirmation + profile-count rows -------------------

def test_printer_facts_uses_a_stored_confirmation_while_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, reachable=False)
    conn = service._conn()
    try:
        nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
    finally:
        conn.close()

    facts = service.printer_facts("u1.local", 7125)
    assert facts["reachable"] is False
    assert facts["nozzle_diameters"] == [0.4]
    assert facts["nozzle_confirmed_by"] == "user"


def test_nozzle_status_row_count_falls_back_to_the_u1_profile_when_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, reachable=False)
    out = service.nozzle_status("u1.local", 7125)
    assert len(out["toolheads"]) == 4
    assert out["toolhead_count_source"] == "profile"
    assert all(t["source"] == "unknown" for t in out["toolheads"])


def test_nozzle_status_row_count_is_len_live_when_capabilities_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, reachable=True, nozzle_diameters=[0.4, 0.6], caps_fails=True)
    out = service.nozzle_status("u1.local", 7125)
    assert len(out["toolheads"]) == 2
    assert out["toolhead_count"] == 2
    assert out["toolhead_count_source"] == "printer"


# --- B3: storage guarded; reads never write ----------------------------------

def test_get_nozzle_confirmations_never_inserts_a_meta_row_on_read(tmp_path):
    db_path = str(tmp_path / "lib.db")
    conn = library.connect(db_path)
    try:
        confirmed, revision = library.get_nozzle_confirmations(conn, "u1.local", 7125)
        assert confirmed == {} and revision == 0
        row = conn.execute(
            "SELECT * FROM nozzle_confirmation_meta WHERE host=? AND port=?",
            ("u1.local", 7125)).fetchone()
        assert row is None  # a pure read must not have written the tombstone
    finally:
        conn.close()


def test_printer_facts_degrades_gracefully_when_storage_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, reachable=True, nozzle_diameters=None)

    def boom(*a, **k):
        raise RuntimeError("disk is unavailable")

    monkeypatch.setattr(service, "_conn", boom)
    facts = service.printer_facts("u1.local", 7125)  # must not raise
    assert facts["nozzle_diameters"] is None
    assert facts["nozzle_storage_error"] == "storage_unavailable"


def test_preflight_post_slice_send_check_material_plan_survive_a_storage_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, reachable=True, nozzle_diameters=None)

    def boom(*a, **k):
        raise RuntimeError("disk is unavailable")

    monkeypatch.setattr(service, "_conn", boom)
    path = _sample_3mf(tmp_path)
    # None of these may raise, storage-broken or not.
    service.preflight(path, host="u1.local", port=7125)
    service.post_slice(path, host="u1.local", port=7125)
    service.send_check(path, host="u1.local", port=7125)
    service.material_plan(path, host="u1.local", port=7125)


# --- B4: combine() conflict text names real sources --------------------------

def test_combine_conflict_names_the_provider_by_its_real_name_not_a_raw_id():
    printer_state = providers._slot(0, material="PLA", confirmed_by=providers.BY_PRINTER)
    stock = {"schema_version": providers.SCHEMA_VERSION, "source": providers.STOCK,
            "available": True, "slots": [printer_state]}
    spoolman_slot = providers._slot(0, material="PETG", source=providers.SPOOLMAN,
                                    confirmed_by=providers.BY_PROVIDER)
    spoolman = {"schema_version": providers.SCHEMA_VERSION, "source": providers.SPOOLMAN,
               "available": True, "slots": [spoolman_slot]}
    combined = providers.combine(stock, spoolman)
    conflicts = combined["slots"][0]["conflicts"]
    assert any("the printer reports" in c for c in conflicts)
    assert any("your provider (Spoolman)" in c for c in conflicts)
    assert not any("spoolman" in c.lower().split("(")[0] for c in conflicts)  # never the raw id bare


def test_combine_conflict_between_a_provider_and_a_note_never_credits_the_printer():
    """B4: when neither side is actually the printer, the sentence must not
    say 'the printer reports' for a value that came from a provider."""
    spoolman_slot = providers._slot(0, material="PLA", source=providers.SPOOLMAN,
                                    confirmed_by=providers.BY_PROVIDER)
    spoolman = {"schema_version": providers.SCHEMA_VERSION, "source": providers.SPOOLMAN,
               "available": True, "slots": [spoolman_slot]}
    local_slot = providers._slot(0, material="PETG", source=providers.LOCAL,
                                 confirmed_by=providers.BY_PROVIDER)
    local = {"schema_version": providers.SCHEMA_VERSION, "source": providers.LOCAL,
            "available": True, "slots": [local_slot]}
    combined = providers.combine(spoolman, local)
    conflicts = combined["slots"][0]["conflicts"]
    assert conflicts, "expected a material disagreement"
    assert not any("the printer reports" in c for c in conflicts)
    assert any("your provider (Spoolman)" in c for c in conflicts)
    assert any("your note says" in c for c in conflicts)


def test_combine_printer_confirmed_empty_vs_a_note_names_the_note():
    stock_empty = providers._slot(0, present=False, confirmed_by=providers.BY_PRINTER)
    stock = {"schema_version": providers.SCHEMA_VERSION, "source": providers.STOCK,
            "available": True, "slots": [stock_empty]}
    local_present = providers._slot(0, material="PLA", source=providers.LOCAL,
                                    confirmed_by=providers.BY_PROVIDER)
    local = {"schema_version": providers.SCHEMA_VERSION, "source": providers.LOCAL,
            "available": True, "slots": [local_present]}
    combined = providers.combine(stock, local)
    conflicts = combined["slots"][0]["conflicts"]
    assert any("your note says" in c and "the printer" in c for c in conflicts)


# --- B5: error map precision + storage_error on the read route --------------

def test_nozzles_status_bad_port_is_invalid_request_not_invalid_host(tmp_path, monkeypatch):
    from snapstudio_api.server import build_server
    from tests.test_api import _request, _run

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, body = _request(port, "/nozzles/status",
                                {"host": "u1.local", "port": 999999}, token)
        assert status == 400
        assert body["error"] == "invalid_request"
    finally:
        httpd.shutdown()


def test_nozzles_confirm_bad_expected_revision_is_invalid_request_not_invalid_diameters(tmp_path, monkeypatch):
    from snapstudio_api.server import build_server
    from tests.test_api import _request, _run

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, body = _request(port, "/nozzles/confirm",
                                {"host": "u1.local", "diameters": [0.4]}, token)  # no expected_revision
        assert status == 400
        assert body["error"] == "invalid_request"
    finally:
        httpd.shutdown()


def test_nozzles_status_storage_failure_is_200_with_storage_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, reachable=False)

    def boom():
        raise RuntimeError("disk is unavailable")

    monkeypatch.setattr(service, "_conn", boom)
    out = service.nozzle_status("u1.local", 7125)  # must not raise
    assert out["storage_error"] == "storage_unavailable"
    assert out["toolheads"]  # never empty just because storage failed


# --- B6: printer.nozzle_revision present on both paths -----------------------

def test_preflight_reports_the_stored_revision_on_the_stored_confirmation_path(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, reachable=True, nozzle_diameters=None)
    conn = service._conn()
    try:
        nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
        nc.confirm(conn, "u1.local", 7125, [0.6], 1, "2026-01-01T00:00:01Z")
    finally:
        conn.close()

    out = service.preflight(_sample_3mf(tmp_path), host="u1.local", port=7125)
    assert out["printer"]["nozzle_revision"] == 2


def test_preflight_reports_the_stored_revision_on_the_request_override_path(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, reachable=True, nozzle_diameters=None)
    conn = service._conn()
    try:
        nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
    finally:
        conn.close()

    out = service.preflight(_sample_3mf(tmp_path), host="u1.local", port=7125,
                            confirmed_nozzle_diameters=[0.6])
    assert out["printer"]["nozzle_revision"] == 1  # never 0 when a stored snapshot exists


# --- B7: confirmed_at/confirmed_by reflect the source actually used ---------

def test_confirmed_at_is_absent_when_the_live_reading_wins_even_with_a_request_value(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, reachable=True, nozzle_diameters=[0.4])
    out = service.preflight(_sample_3mf(tmp_path), host="u1.local", port=7125,
                            confirmed_nozzle_diameters=[0.6],
                            confirmed_nozzle_at="2099-01-01T00:00:00Z")
    assert out["printer"]["nozzle_confirmed_by"] == "printer"
    assert out["printer"]["nozzle_confirmed_at"] is None


def test_count_mismatch_is_always_a_bool(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, reachable=False)
    out = service.nozzle_status("u1.local", 7125)
    assert isinstance(out["count_mismatch"], bool)


# --- B8: send_state nozzle_notes copy + provenance separation ---------------

def test_send_state_nozzle_notes_consequence_is_plain_user_text():
    assert "design note" not in send_state.CONSEQUENCE["nozzle_notes"].lower()
    assert "never reported as" not in send_state.CONSEQUENCE["nozzle_notes"]


def test_a_live_only_reading_change_is_reported_under_printer_not_nozzle_notes():
    printer_a = {"reachable": True, "nozzle_confirmed_by": "printer",
                "nozzle_diameters": [0.4], "_live_nozzle_diameters": [0.4], "nozzle_conflicts": []}
    printer_b = {"reachable": True, "nozzle_confirmed_by": "printer",
                "nozzle_diameters": [0.6], "_live_nozzle_diameters": [0.6], "nozzle_conflicts": []}
    facts = {"file": "job.gcode"}
    before = send_state.fingerprint(facts, printer_a)
    after = send_state.fingerprint(facts, printer_b)
    found = {c["part"] for c in send_state.changes(before, after)}
    assert "printer" in found
    assert "nozzle_notes" not in found


# --- B9: fingerprint reacts to a real note change; exclusion regressions ----

def test_send_state_fingerprint_changes_when_a_confirmation_changes():
    """Superseded in shape (not intent) by R2-B3: the `nozzle_notes` part now
    keys on the STORED snapshot + stored revision, not the resolved
    `nozzle_diameters` value — see test_v12_fix_round2.py for the full
    round-2 spec of this fingerprint part. This test still proves the
    original B9 guarantee (a confirmation change is caught) using the
    current, correct shape."""
    facts = {"file": "job.gcode"}
    before_printer = {"reachable": True, "nozzle_confirmed_by": "user",
                      "nozzle_diameters": [0.4], "_live_nozzle_diameters": None,
                      "nozzle_conflicts": [], "nozzle_revision": 1,
                      "_stored_nozzle_confirmations": {0: {"diameter": 0.4, "confirmed_at": "t"}}}
    after_printer = {"reachable": True, "nozzle_confirmed_by": "user",
                     "nozzle_diameters": [0.6], "_live_nozzle_diameters": None,
                     "nozzle_conflicts": [], "nozzle_revision": 2,
                     "_stored_nozzle_confirmations": {0: {"diameter": 0.6, "confirmed_at": "t2"}}}
    before = send_state.fingerprint(facts, before_printer)
    after = send_state.fingerprint(facts, after_printer)
    found = {c["part"] for c in send_state.changes(before, after)}
    assert "nozzle_notes" in found


def test_verify_printer_evidence_excludes_seeded_local_spool_notes_and_confirmations(tmp_path, monkeypatch):
    from snapstudio_core import hardware_verify

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, reachable=False)
    conn = service._conn()
    try:
        library.upsert_spool(conn, host="u1.local", slot=0, material="A SEEDED SECRET",
                             subtype=None, color=None, vendor=None, starting_g=None,
                             remaining_g=None, remaining_quality=None, remaining_as_of=None,
                             notes="a private note", updated_at="2026-01-01T00:00:00Z")
        nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
    finally:
        conn.close()

    bundle = hardware_verify.build_evidence("u1.local", port=7125)
    blob = str(bundle)
    assert "A SEEDED SECRET" not in blob
    assert "a private note" not in blob


def test_diagnostics_excludes_seeded_local_spool_notes_and_nozzle_confirmations(tmp_path, monkeypatch):
    from snapstudio_core import diagnostics as diag

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker(monkeypatch, reachable=True, nozzle_diameters=None)
    conn = service._conn()
    try:
        library.upsert_spool(conn, host="u1.local", slot=0, material="ANOTHER SEEDED SECRET",
                             subtype=None, color=None, vendor=None, starting_g=None,
                             remaining_g=None, remaining_quality=None, remaining_as_of=None,
                             notes="also private", updated_at="2026-01-01T00:00:00Z")
        nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
    finally:
        conn.close()

    bundle = diag.collect(host="u1.local", port=7125)
    blob = str(bundle)
    assert "ANOTHER SEEDED SECRET" not in blob
    assert "also private" not in blob
