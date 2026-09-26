from snapstudio_core import library


def _db(tmp_path):
    return library.connect(str(tmp_path / "library.db"))


def test_upsert_list_and_update(tmp_path):
    conn = _db(tmp_path)
    pid = library.upsert_project(
        conn, name="Sample Project", source_path="C:/x/Sample Project.3mf",
        source_family="bambu", verdict="REPAIRABLE", score=90, filament_count=5,
        last_action="doctor", updated_at="2026-06-18T20:00:00Z")
    rows = library.list_projects(conn)
    assert len(rows) == 1 and rows[0]["name"] == "Sample Project" and rows[0]["score"] == 90

    # upsert by same source_path updates in place (no duplicate row)
    pid2 = library.upsert_project(
        conn, name="Sample Project", source_path="C:/x/Sample Project.3mf",
        source_family="bambu", output_path="C:/x/Sample Project_SnapmakerU1.3mf",
        verdict="READY", score=100, filament_count=5, last_action="convert",
        updated_at="2026-06-18T20:05:00Z")
    assert pid2 == pid
    rows = library.list_projects(conn)
    assert len(rows) == 1
    assert rows[0]["verdict"] == "READY" and rows[0]["score"] == 100
    assert rows[0]["output_path"].endswith("_SnapmakerU1.3mf")


def test_search_and_tags(tmp_path):
    conn = _db(tmp_path)
    a = library.upsert_project(conn, name="Liberty Eagle", source_path="C:/a.3mf",
                               updated_at="2026-06-18T10:00:00Z")
    library.upsert_project(conn, name="Calibration Cube", source_path="C:/b.stl",
                           updated_at="2026-06-18T11:00:00Z")
    assert [r["name"] for r in library.search_projects(conn, "eagle")] == ["Liberty Eagle"]
    library.add_tag(conn, a, "flags")
    tagged = library.search_projects(conn, tag="flags")
    assert len(tagged) == 1 and tagged[0]["name"] == "Liberty Eagle"
    assert library.search_projects(conn, tag="missing") == []


def test_history_and_delete(tmp_path):
    conn = _db(tmp_path)
    pid = library.upsert_project(conn, name="X", source_path="C:/x.3mf",
                                 updated_at="2026-06-18T09:00:00Z")
    library.add_history(conn, pid, "doctor", "REPAIRABLE 90", "2026-06-18T09:00:00Z")
    library.add_history(conn, pid, "convert", "READY 100", "2026-06-18T09:01:00Z")
    h = library.get_history(conn, pid)
    assert [e["action"] for e in h] == ["convert", "doctor"]  # newest first
    library.delete_project(conn, pid)
    assert library.list_projects(conn) == []
    assert library.get_history(conn, pid) == []


# --- local/manual spools ------------------------------------------------------

def test_upsert_spool_then_list_and_get(tmp_path):
    conn = _db(tmp_path)
    library.upsert_spool(conn, host="u1.local", slot=0, material="PLA", subtype="Matte",
                         color="#FF0000", vendor="Snapmaker", starting_g=1000.0,
                         remaining_g=800.0, remaining_quality="user_confirmed",
                         remaining_as_of="2026-09-26T00:00:00Z", notes=None,
                         updated_at="2026-09-26T00:00:00Z")
    rows = library.list_spools(conn, "u1.local")
    assert len(rows) == 1 and rows[0]["material"] == "PLA" and rows[0]["remaining_g"] == 800.0
    assert library.get_spool(conn, "u1.local", 0)["color"] == "#FF0000"
    assert library.get_spool(conn, "u1.local", 1) is None


def test_upsert_spool_by_same_host_and_slot_updates_in_place(tmp_path):
    conn = _db(tmp_path)
    library.upsert_spool(conn, host="u1.local", slot=0, material="PLA", subtype=None,
                         color="#FF0000", vendor=None, starting_g=1000.0, remaining_g=800.0,
                         remaining_quality="user_confirmed", remaining_as_of="2026-09-26T00:00:00Z",
                         notes=None, updated_at="2026-09-26T00:00:00Z")
    library.upsert_spool(conn, host="u1.local", slot=0, material="PETG", subtype=None,
                         color="#00FF00", vendor=None, starting_g=1000.0, remaining_g=600.0,
                         remaining_quality="user_confirmed", remaining_as_of="2026-09-26T01:00:00Z",
                         notes=None, updated_at="2026-09-26T01:00:00Z")
    rows = library.list_spools(conn, "u1.local")
    assert len(rows) == 1
    assert rows[0]["material"] == "PETG" and rows[0]["remaining_g"] == 600.0


def test_spools_are_scoped_per_host(tmp_path):
    conn = _db(tmp_path)
    library.upsert_spool(conn, host="u1.local", slot=0, material="PLA", subtype=None,
                         color=None, vendor=None, starting_g=None, remaining_g=None,
                         remaining_quality=None, remaining_as_of=None, notes=None,
                         updated_at="2026-09-26T00:00:00Z")
    library.upsert_spool(conn, host="second-u1.local", slot=0, material="ABS", subtype=None,
                         color=None, vendor=None, starting_g=None, remaining_g=None,
                         remaining_quality=None, remaining_as_of=None, notes=None,
                         updated_at="2026-09-26T00:00:00Z")
    assert [r["material"] for r in library.list_spools(conn, "u1.local")] == ["PLA"]
    assert [r["material"] for r in library.list_spools(conn, "second-u1.local")] == ["ABS"]


def test_delete_spool_removes_only_that_slot(tmp_path):
    conn = _db(tmp_path)
    for slot in (0, 1):
        library.upsert_spool(conn, host="u1.local", slot=slot, material="PLA", subtype=None,
                             color=None, vendor=None, starting_g=None, remaining_g=None,
                             remaining_quality=None, remaining_as_of=None, notes=None,
                             updated_at="2026-09-26T00:00:00Z")
    library.delete_spool(conn, "u1.local", 0)
    rows = library.list_spools(conn, "u1.local")
    assert [r["slot"] for r in rows] == [1]


def test_apply_spool_usage_subtracts_and_marks_estimated(tmp_path):
    conn = _db(tmp_path)
    library.upsert_spool(conn, host="u1.local", slot=0, material="PLA", subtype=None,
                         color=None, vendor=None, starting_g=1000.0, remaining_g=800.0,
                         remaining_quality="user_confirmed", remaining_as_of="2026-09-26T00:00:00Z",
                         notes=None, updated_at="2026-09-26T00:00:00Z")
    updated = library.apply_spool_usage(conn, host="u1.local", slot=0, used_g=50.0,
                                        remaining_quality="derived", at="2026-09-26T02:00:00Z")
    assert updated["remaining_g"] == 750.0
    assert updated["remaining_quality"] == "derived"
    assert updated["remaining_as_of"] == "2026-09-26T02:00:00Z"


def test_apply_spool_usage_never_goes_negative(tmp_path):
    conn = _db(tmp_path)
    library.upsert_spool(conn, host="u1.local", slot=0, material="PLA", subtype=None,
                         color=None, vendor=None, starting_g=1000.0, remaining_g=30.0,
                         remaining_quality="user_confirmed", remaining_as_of="2026-09-26T00:00:00Z",
                         notes=None, updated_at="2026-09-26T00:00:00Z")
    updated = library.apply_spool_usage(conn, host="u1.local", slot=0, used_g=50.0,
                                        remaining_quality="derived", at="2026-09-26T02:00:00Z")
    assert updated["remaining_g"] == 0.0


def test_apply_spool_usage_on_a_record_with_no_record_ever_is_none(tmp_path):
    conn = _db(tmp_path)
    assert library.apply_spool_usage(conn, host="u1.local", slot=0, used_g=10.0,
                                     remaining_quality="derived", at="2026-09-26T00:00:00Z") is None


def test_apply_spool_usage_on_a_record_with_no_remaining_weight_is_none(tmp_path):
    conn = _db(tmp_path)
    library.upsert_spool(conn, host="u1.local", slot=0, material="PLA", subtype=None,
                         color=None, vendor=None, starting_g=1000.0, remaining_g=None,
                         remaining_quality=None, remaining_as_of=None, notes=None,
                         updated_at="2026-09-26T00:00:00Z")
    assert library.apply_spool_usage(conn, host="u1.local", slot=0, used_g=10.0,
                                     remaining_quality="derived", at="2026-09-26T02:00:00Z") is None
