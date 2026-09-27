"""Per-printer nozzle confirmation: storage, canonical host keys, the shared
precedence resolver, the frozen `/nozzles/*` routes and their error map.
"""
from __future__ import annotations

import threading

import pytest

from snapstudio_core import library, nozzle_confirm as nc


def _conn(tmp_path, monkeypatch, name="lib.db"):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    return library.connect(str(tmp_path / name))


# --- canonical_host -----------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("U1.Local", "u1.local"),
    ("  u1.local  ", "u1.local"),
    ("u1.local.", "u1.local"),
    ("192.168.1.50", "192.168.1.50"),
    ("[FE80::1]", "[fe80::1]"),
    ("fe80::1", "[fe80::1]"),
    ("fe80:0:0:0:0:0:0:1", "[fe80::1]"),  # compressed on the way in
])
def test_canonical_host_normalises_equivalent_spellings(raw, expected):
    assert nc.canonical_host(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "http://u1.local", "u1.local/path", "user@u1.local",
    "u1.local:7125", "not a host", "not-ipv6:::::", "u1.\tlocal",
])
def test_canonical_host_rejects_scheme_path_whitespace_and_embedded_port(raw):
    with pytest.raises(nc.InvalidHost):
        nc.canonical_host(raw)


def test_canonical_host_case_and_whitespace_alias_to_one_storage_key(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    rev = library.replace_nozzle_confirmations(
        conn, nc.canonical_host("U1.Local "), 7125, [0.4], "2026-01-01T00:00:00Z", 0)
    confirmed, revision = library.get_nozzle_confirmations(conn, nc.canonical_host("u1.local"), 7125)
    assert confirmed[0]["diameter"] == 0.4
    assert revision == rev


# --- schema: idempotent, downgrade-safe ---------------------------------

def test_v2_db_with_data_opens_gains_the_new_tables_and_keeps_data(tmp_path):
    db_path = str(tmp_path / "v11.db")
    conn = library.connect(db_path)
    library.upsert_spool(conn, host="u1.local", slot=0, material="PLA", subtype=None,
                         color=None, vendor=None, starting_g=1000.0, remaining_g=800.0,
                         remaining_quality="user_confirmed", remaining_as_of="2026-01-01T00:00:00Z",
                         notes=None, updated_at="2026-01-01T00:00:00Z")
    conn.close()

    # A v1.1.0-style v2 DB (no nozzle tables yet) opening again must gain them
    # idempotently, without touching the data already there.
    conn2 = library.connect(db_path)
    cur = conn2.execute("PRAGMA user_version").fetchone()[0]
    assert cur == library.SCHEMA_VERSION == 2
    rows = conn2.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'nozzle_%'").fetchall()
    assert {r["name"] for r in rows} == {"nozzle_confirmations", "nozzle_confirmation_meta"}
    assert library.get_spool(conn2, "u1.local", 0)["remaining_g"] == 800.0

    # Re-open again: still idempotent, still restart-safe.
    conn2.close()
    conn3 = library.connect(db_path)
    assert conn3.execute("PRAGMA user_version").fetchone()[0] == 2
    conn3.close()


# --- confirm / clear / revision -----------------------------------------

def test_confirm_then_status_round_trips_diameters(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    rev = nc.confirm(conn, "u1.local", 7125, [0.4, 0.4, 0.6, None], 0, "2026-01-01T00:00:00Z")
    assert rev == 1
    out = nc.status(conn, "u1.local", 7125, live=None, reachable=False)
    assert out["revision"] == 1
    assert [t["diameter"] for t in out["toolheads"]] == [0.4, 0.4, 0.6, None]
    assert out["toolheads"][3]["source"] == "unknown"
    assert out["toolheads"][0]["source"] == "user"


def test_confirm_with_a_stale_expected_revision_raises_with_the_current_one(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
    with pytest.raises(nc.StaleRevision) as exc:
        nc.confirm(conn, "u1.local", 7125, [0.6], 0, "2026-01-01T00:00:01Z")
    assert exc.value.current_revision == 1


def test_clear_is_idempotent_and_still_revision_guarded(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
    rev = nc.clear(conn, "u1.local", 7125, 1)
    assert rev == 2
    confirmed, revision = library.get_nozzle_confirmations(conn, "u1.local", 7125)
    assert confirmed == {}
    assert revision == 2
    # Clearing again with the now-current revision is fine — idempotent.
    rev2 = nc.clear(conn, "u1.local", 7125, 2)
    assert rev2 == 3
    # ...but a stale one is still refused.
    with pytest.raises(nc.StaleRevision):
        nc.clear(conn, "u1.local", 7125, 2)


def test_out_of_range_stored_toolhead_is_preserved_and_flagged(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    nc.confirm(conn, "u1.local", 7125, [0.4, 0.4, 0.6, 0.4, 0.8], 0, "2026-01-01T00:00:00Z")
    out = nc.status(conn, "u1.local", 7125, live=None, reachable=True, toolhead_count=4,
                    toolhead_count_source="printer")
    rows = {t["toolhead"]: t for t in out["toolheads"]}
    assert len(rows) == 5
    assert rows[4]["out_of_range"] is True
    assert rows[0]["out_of_range"] is False


def test_two_connections_racing_the_same_expected_revision_split_one_ok_one_stale(tmp_path, monkeypatch):
    """A3.5: exactly one 200(-equivalent success), one 409(-equivalent
    StaleRevision), and the revision incremented exactly once — never a lost
    update, never two winners."""
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    db_path = str(tmp_path / "race.db")
    library.connect(db_path).close()  # create + migrate once, up front

    results: list = []

    def worker():
        conn = library.connect(db_path)
        try:
            try:
                rev = nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
                results.append(("ok", rev))
            except nc.StaleRevision as exc:
                results.append(("stale", exc.current_revision))
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    kinds = sorted(r[0] for r in results)
    assert kinds == ["ok", "stale"]
    conn = library.connect(db_path)
    _, final_revision = library.get_nozzle_confirmations(conn, "u1.local", 7125)
    conn.close()
    assert final_revision == 1  # bumped exactly once, not twice


# --- diameters validation ------------------------------------------------

@pytest.mark.parametrize("bad", [[], [None] * 9, [2.1], [0], [-0.4], ["0.4"], [True]])
def test_confirm_rejects_invalid_diameter_lists(tmp_path, monkeypatch, bad):
    conn = _conn(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        nc.confirm(conn, "u1.local", 7125, bad, 0, "2026-01-01T00:00:00Z")


# --- the shared precedence resolver --------------------------------------

def test_resolve_prefers_live_over_stored(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    nc.confirm(conn, "u1.local", 7125, [0.6], 0, "2026-01-01T00:00:00Z")
    out = nc.resolve(conn, "u1.local", 7125, [0.4], None)
    assert out["diameters"] == [0.4]
    assert out["confirmed_by"] == "printer"
    assert out["conflicts"] and out["conflicts"][0]["source"] == "stored"


def test_resolve_uses_stored_when_no_live_reading(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
    out = nc.resolve(conn, "u1.local", 7125, None, None)
    assert out["diameters"] == [0.4]
    assert out["confirmed_by"] == "user"


def test_resolve_request_replaces_stored_for_this_call_only(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    nc.confirm(conn, "u1.local", 7125, [0.4], 0, "2026-01-01T00:00:00Z")
    out = nc.resolve(conn, "u1.local", 7125, None, [0.6])
    assert out["diameters"] == [0.6]
    # The stored value was never touched by a read-only resolve() call.
    confirmed, _ = library.get_nozzle_confirmations(conn, "u1.local", 7125)
    assert confirmed[0]["diameter"] == 0.4


def test_resolve_with_nothing_at_all_is_unknown(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    out = nc.resolve(conn, "u1.local", 7125, None, None)
    assert out["diameters"] is None
    assert out["confirmed_by"] is None
