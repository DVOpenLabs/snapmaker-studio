"""A1.3/A2.5/A2.8/A3.4/A4.1: two stored spellings of the same printer's host
colliding on one slot — legacy alias rewrite-in-place, the duplicate_notes
409, delete-by-id precision, and the synthetic conflict slot's promise that
it never reads as empty or blocks a send.
"""
from __future__ import annotations

import pytest

from snapstudio_api import service
from snapstudio_core import library, material_providers as providers


def _seed_legacy_row(conn, host, slot, **kw):
    kw.setdefault("material", "PLA")
    kw.setdefault("subtype", None)
    kw.setdefault("color", None)
    kw.setdefault("vendor", None)
    kw.setdefault("starting_g", None)
    kw.setdefault("remaining_g", None)
    kw.setdefault("remaining_quality", None)
    kw.setdefault("remaining_as_of", None)
    kw.setdefault("notes", None)
    return library.upsert_spool(conn, host=host, slot=slot, updated_at="2026-01-01T00:00:00Z", **kw)


def test_a_single_legacy_alias_is_found_and_rewritten_in_place_on_save(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    conn = service._conn()
    try:
        _seed_legacy_row(conn, "U1.Local", 0, material="PLA", vendor="Snapmaker",
                         remaining_g=500.0, remaining_quality=providers.USER_CONFIRMED)
    finally:
        conn.close()

    rows = service.save_local_spool("u1.local", 0, notes="found it")
    assert len(rows) == 1
    row = rows[0]
    assert row["host_as_stored"] == "u1.local"      # rewritten in place
    assert row["vendor"] == "Snapmaker"              # fields kept
    assert row["notes"] == "found it"
    assert row["alias_conflict"] is False

    conn = service._conn()
    try:
        assert library.get_spool(conn, "U1.Local", 0) is None  # the old spelling is gone
        assert library.get_spool(conn, "u1.local", 0) is not None
    finally:
        conn.close()


def test_two_or_more_aliases_are_flagged_alias_conflict_on_every_row(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    conn = service._conn()
    try:
        _seed_legacy_row(conn, "U1.Local", 0, material="PLA")
        _seed_legacy_row(conn, "u1.local.", 0, material="PETG")
    finally:
        conn.close()

    out = service.local_spools("u1.local")
    rows = [r for r in out["rows"] if r["slot"] == 0]
    assert len(rows) == 2
    assert all(r["alias_conflict"] is True for r in rows)


def test_save_refuses_with_duplicate_notes_409_when_two_aliases_collide(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    conn = service._conn()
    try:
        _seed_legacy_row(conn, "U1.Local", 0)
        _seed_legacy_row(conn, "u1.local.", 0)
    finally:
        conn.close()

    with pytest.raises(service.DuplicateNotes) as exc:
        service.save_local_spool("u1.local", 0, notes="pick one")
    assert exc.value.slot == 0


def test_mark_used_also_refuses_with_duplicate_notes_on_a_collided_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    conn = service._conn()
    try:
        _seed_legacy_row(conn, "U1.Local", 0, remaining_g=500.0)
        _seed_legacy_row(conn, "u1.local.", 0, remaining_g=500.0)
    finally:
        conn.close()

    with pytest.raises(service.DuplicateNotes):
        service.mark_local_spool_used("u1.local", 0, 10.0)


def test_delete_without_id_removes_every_alias_for_the_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    conn = service._conn()
    try:
        _seed_legacy_row(conn, "U1.Local", 0)
        _seed_legacy_row(conn, "u1.local.", 0)
    finally:
        conn.close()

    rows = service.delete_local_spool("u1.local", 0)
    assert rows == []


def test_delete_by_id_removes_only_the_one_alias_named(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    conn = service._conn()
    try:
        keep_id = _seed_legacy_row(conn, "U1.Local", 0, material="PLA")
        remove_id = _seed_legacy_row(conn, "u1.local.", 0, material="PETG")
    finally:
        conn.close()

    rows = service.delete_local_spool("u1.local", 0, id=remove_id)
    assert len(rows) == 1
    assert rows[0]["id"] == keep_id
    assert rows[0]["alias_conflict"] is False


def test_delete_by_id_mismatched_slot_or_host_is_404_not_a_silent_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    conn = service._conn()
    try:
        wrong_slot_id = _seed_legacy_row(conn, "u1.local", 5, material="PLA")
        other_printer_id = _seed_legacy_row(conn, "another.local", 0, material="PLA")
    finally:
        conn.close()

    with pytest.raises(service.NoSuchNote):
        service.delete_local_spool("u1.local", 0, id=wrong_slot_id)   # right host, wrong slot
    with pytest.raises(service.NoSuchNote):
        service.delete_local_spool("u1.local", 0, id=other_printer_id)  # wrong printer entirely
    with pytest.raises(service.NoSuchNote):
        service.delete_local_spool("u1.local", 0, id=999999)          # no such row at all


# --- A3.4/A2.8/A4.1: the synthetic conflict slot never reads as empty -------

def test_colliding_notes_with_no_printer_reading_is_unknown_not_a_send_blocker(tmp_path, monkeypatch):
    """A4.1's named regression: conflicting notes + no printer reading for
    that slot -> UNKNOWN, never a BLOCKER ('is empty and this job uses it')."""
    from snapstudio_core import send_check

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    conn = service._conn()
    try:
        _seed_legacy_row(conn, "U1.Local", 0, material="PLA")
        _seed_legacy_row(conn, "u1.local.", 0, material="PETG")
    finally:
        conn.close()

    printer = service._with_providers({"reachable": True}, "u1.local", 7125,
                                      provider_url=None, slot_map=None)
    assert printer.get("note_conflicts") == [{"slot": 0, "count": 2}]

    facts = {"available": True, "tools_used": [0],
            "slots": [{"tool": 0, "used": True, "grams": 20.0, "type": "PLA"}]}
    report = send_check.evaluate(facts, printer)
    assert not any(i["kind"] == send_check.BLOCKER and "empty" in i["title"].lower()
                  for i in report["items"])

    from snapstudio_core import material_plan
    plan = material_plan.plan(facts["slots"], printer["loaded_filaments"],
                              slot_facts=printer["slot_facts"])
    assert plan["slots"][0]["state"] == "unknown"
    assert any("two notes exist" in n for n in plan["slots"][0].get("notes") or ())


def test_note_conflicts_slot_is_excluded_from_the_normal_local_note_rows(tmp_path, monkeypatch):
    """The collided slot must never be silently merged/picked — the normal
    local-note material feed excludes it entirely, and it appears ONLY as the
    synthetic conflict entry."""
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    conn = service._conn()
    try:
        _seed_legacy_row(conn, "U1.Local", 0, material="PLA")
        _seed_legacy_row(conn, "u1.local.", 0, material="PETG")
        _seed_legacy_row(conn, "u1.local", 1, material="PETG")  # an uncontested slot
    finally:
        conn.close()

    rows, conflicts = service._local_material_rows("u1.local")
    assert conflicts == [{"slot": 0, "count": 2}]
    assert [r["slot"] for r in rows] == [1]
