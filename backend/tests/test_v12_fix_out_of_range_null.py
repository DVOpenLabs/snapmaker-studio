"""CodeRabbit #2 (Sol root-cause): the desktop's "pop trailing nulls"
workaround for `out_of_range` rows loses data because the backend was
emitting an `out_of_range` row for a stored toolhead >= count EVEN when its
stored diameter is `None` ("not sure") — so nulling that position via
`/nozzles/confirm`'s atomic replace ("Remove my note") could never make the
row disappear; a null out-of-range row carries no information and should
simply not exist.

Each test is written to FAIL on the pre-fix code first.
"""
from __future__ import annotations

from snapstudio_core import nozzle_confirm as nc


def _confirmed(diameters: list[float | None]) -> dict[int, dict]:
    return {i: {"diameter": d, "confirmed_at": ("2026-01-01T00:00:00Z" if d is not None else None)}
           for i, d in enumerate(diameters)}


def test_a_null_stored_beyond_count_emits_no_out_of_range_row():
    confirmed = _confirmed([0.4, 0.4, 0.4, 0.4, None, 0.3])
    rows = nc._positions(confirmed, 4)
    out_of_range = [r for r in rows if r["out_of_range"]]
    assert len(out_of_range) == 1
    assert out_of_range[0]["toolhead"] == 5
    assert out_of_range[0]["diameter"] == 0.3
    # The null at index 4 (also beyond count=4) must not appear as a row at
    # all — not in-range, not out-of-range, nothing to show or remove.
    assert not any(r["toolhead"] == 4 for r in rows)


def test_nulling_the_last_real_out_of_range_value_makes_it_disappear_entirely():
    """The exact repro: after "Remove my note" replaces [0.4,0.4,0.4,0.4,None,0.3]
    with [0.4,0.4,0.4,0.4,None,None] (an atomic /nozzles/confirm replace),
    there must be zero out_of_range rows left — not one stuck row the
    desktop's old "pop trailing nulls" hack could never clear."""
    confirmed = _confirmed([0.4, 0.4, 0.4, 0.4, None, None])
    rows = nc._positions(confirmed, 4)
    assert [r for r in rows if r["out_of_range"]] == []
    assert len(rows) == 4  # only the in-range positions


def test_in_range_null_is_still_an_ordinary_unknown_row_unchanged():
    confirmed = _confirmed([0.4, 0.4, None, 0.4])
    rows = nc._positions(confirmed, 4)
    assert len(rows) == 4
    row2 = next(r for r in rows if r["toolhead"] == 2)
    assert row2["out_of_range"] is False
    assert row2["source"] == "unknown"
    assert row2["diameter"] is None


def test_a_real_value_beyond_count_is_still_flagged_out_of_range():
    """Regression guard: this fix must not swallow a GENUINE out-of-range
    value, only a null one."""
    confirmed = _confirmed([0.4, 0.4, 0.4, 0.4, 0.6])
    rows = nc._positions(confirmed, 4)
    out_of_range = [r for r in rows if r["out_of_range"]]
    assert len(out_of_range) == 1
    assert out_of_range[0]["toolhead"] == 4
    assert out_of_range[0]["diameter"] == 0.6


def test_end_to_end_through_status_confirm_then_clear_the_out_of_range_one(tmp_path, monkeypatch):
    from snapstudio_api import service

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    conn = service._conn()
    try:
        rev = nc.confirm(conn, "u1.local", 7125, [0.4, 0.4, 0.4, 0.4, None, 0.3], 0,
                         "2026-01-01T00:00:00Z")
        out = nc.status(conn, "u1.local", 7125, live=None, reachable=False, toolhead_count=4,
                        toolhead_count_source="profile")
        assert len([t for t in out["toolheads"] if t["out_of_range"]]) == 1

        # "Remove my note": the atomic replace nulls that position too.
        nc.confirm(conn, "u1.local", 7125, [0.4, 0.4, 0.4, 0.4, None, None], rev,
                  "2026-01-01T00:00:01Z")
        out2 = nc.status(conn, "u1.local", 7125, live=None, reachable=False, toolhead_count=4,
                         toolhead_count_source="profile")
        assert [t for t in out2["toolheads"] if t["out_of_range"]] == []
    finally:
        conn.close()
