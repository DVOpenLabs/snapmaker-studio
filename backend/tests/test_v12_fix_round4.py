"""v1.2 fix round 4, backend part (R4-B1) — spec: v12-fix-round4.md.
Failing-first test with a raising moonraker stub, then the fix.
"""
from __future__ import annotations

from snapstudio_api import service
from snapstudio_core import nozzle_confirm as nc


def _stub_moonraker_raises(monkeypatch):
    from snapstudio_core import moonraker

    def boom(*a, **k):
        raise AssertionError("moonraker must not be called at all — confirm/clear "
                             "must answer without probing the printer (probe=false semantics)")

    monkeypatch.setattr(moonraker, "probe", boom)
    monkeypatch.setattr(moonraker, "machine_info", boom)
    monkeypatch.setattr(moonraker, "capabilities", boom)


def test_nozzle_confirm_save_succeeds_and_returns_rows_without_probing_the_printer(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    _stub_moonraker_raises(monkeypatch)

    out = service.nozzle_confirm_save("u1.local", 7125, [0.4, 0.6], 0)
    assert out["reachable"] is False
    assert out["live_error"] == "not_checked"
    assert out["toolhead_count_source"] == "profile"
    assert [t["diameter"] for t in out["toolheads"]] == [0.4, 0.6, None, None]


def test_nozzle_clear_succeeds_and_returns_rows_without_probing_the_printer(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    conn = service._conn()
    try:
        nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
    finally:
        conn.close()

    _stub_moonraker_raises(monkeypatch)
    out = service.nozzle_clear("u1.local", 7125, 1)
    assert out["reachable"] is False
    assert out["live_error"] == "not_checked"
    assert out["toolhead_count_source"] == "profile"
    assert all(t["diameter"] is None for t in out["toolheads"])
