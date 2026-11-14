"""P5 assemblies: PLAN_V43 section 6 P5 tests 1-10, common C3/C7 and guard G1/G2-style checks.

Fixture-tested: every input here is synthetic (see tests/fixtures/assemblies/PROVENANCE.md).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from pathlib import Path

import pytest

from snapstudio_api import ext_routes, routes_assemblies
from snapstudio_core import paths
from snapstudio_core.assemblies import evaluate as ev
from snapstudio_core.assemblies import store
from snapstudio_core.assemblies.model import (AssemblyInputError, read_assembly, usage_from_gcode_facts,
                                              usage_from_slot_usage)
from snapstudio_core.foundation.store import RevisionConflict

HERE = Path(__file__).parent
FIXTURES = HERE.parent / "fixtures" / "assemblies"
NOW = 1_800_000_000.0

ROAD = {"provider_instance_id": "synthetic", "provider_spool_id": "road-1"}
WATER = {"provider_instance_id": "synthetic", "provider_spool_id": "water-1"}


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def six_tile() -> dict:
    return fixture("six_tile.json")


def reading(spool, grams, age=10, ttl=600, **extra):
    return {"spool": spool, "remaining_g": grams, "observed_at": NOW - age, "ttl_s": ttl, **extra}


def run(doc, supply, lookup=None):
    asm = read_assembly(doc)
    return ev.evaluate(asm, ev.read_supply(supply, NOW), now=NOW, lookup=lookup)


def spool_row(report, spool):
    return next(s for s in report["spools"] if s["spool"] == spool)


# -- 1. six tiles share roles across plates ---------------------------------------
def test_1_six_tiles_share_road_and_water_roles_across_plates():
    report = run(six_tile(), [reading(ROAD, 500), reading(WATER, 500)])
    assert len(report["tiles"]) == 6
    roles = {r["role"]: r for r in report["roles"]}
    assert set(roles) == {"road", "water"}
    for role in roles.values():
        assert len(role["tiles"]) == 6
        assert role["plates"] == ["1", "2", "3"]
        assert role["shared_across_plates"] is True
    # The same role sits on different slots on different plates; the spool is still counted once.
    assert spool_row(report, ROAD)["need_known_g"] == 240.0
    assert spool_row(report, WATER)["need_known_g"] == 150.0


# -- 2. cumulative grams, 1-based and 0-based sources, never double counted --------
def test_2_slot_usage_is_one_based_and_gcode_tools_are_zero_based_and_both_land_on_the_same_slot():
    from_project = usage_from_slot_usage(fixture("slot_usage_tile.json"))
    from_gcode = usage_from_gcode_facts(fixture("gcode_facts_tile.json"))
    assert from_project == from_gcode == {"slot:0": 12.5, "slot:1": None, "slot:2": 4.0}


def test_2_one_spool_behind_two_roles_or_two_slots_is_counted_once():
    doc = six_tile()
    doc["bindings"]["water"] = dict(ROAD)            # both roles on one physical spool
    report = run(doc, [reading(ROAD, 1000)])
    assert len(report["spools"]) == 1
    assert report["spools"][0]["need_known_g"] == 390.0
    assert sorted(report["spools"][0]["roles"]) == ["road", "water"]
    per_tile = {t["tile_id"]: t["grams"] for t in report["spools"][0]["tiles"]}
    assert per_tile == {f"t{i}": 65.0 for i in range(1, 7)}


def test_2_an_alias_merges_two_providers_spools_and_no_alias_keeps_them_apart():
    doc = six_tile()
    doc["bindings"]["water"] = {"provider_instance_id": "other", "provider_spool_id": "road-1"}
    assert len(run(doc, [])["spools"]) == 2
    doc["aliases"] = [{"refs": [ROAD, doc["bindings"]["water"]], "evidence": "user label", "declared_by": "user"}]
    merged = run(doc, [reading(ROAD, 1000)])
    assert len(merged["spools"]) == 1 and merged["spools"][0]["need_known_g"] == 390.0


def test_2_slot_usage_and_gcode_facts_feed_a_tile_through_the_document():
    doc = six_tile()
    doc["tiles"][0].pop("usage")
    doc["tiles"][0]["slot_usage"] = fixture("slot_usage_tile.json")
    doc["tiles"][1].pop("usage")
    doc["tiles"][1]["gcode_facts"] = fixture("gcode_facts_tile.json")
    asm = read_assembly(doc)
    assert asm.tiles[0].usage == asm.tiles[1].usage
    assert (asm.tiles[0].usage_source, asm.tiles[1].usage_source) == ("slot_usage", "gcode_facts")
    doc["tiles"][0]["usage"] = {"slot:0": 1}
    with pytest.raises(AssemblyInputError):
        read_assembly(doc)                          # two gram sources on one tile


# -- 3. a job without grams stays unknown ------------------------------------------
def test_3_a_tile_without_grams_stays_unknown_and_is_not_counted_as_zero():
    doc = six_tile()
    doc["tiles"][4].pop("usage")
    doc["tiles"][5]["usage"] = {"slot:0": 40, "slot:1": None}
    report = run(doc, [reading(ROAD, 1000), reading(WATER, 1000)])
    t5, t6 = report["tiles"][4], report["tiles"][5]
    assert t5["need_complete"] is False and t5["unknown_slots"] == ["slot:0", "slot:1"]
    assert t6["unknown_slots"] == ["slot:1"] and t6["need_known_g"] == 40.0
    assert report["verdict"] == "unknown"
    assert spool_row(report, ROAD)["unknown_tiles"] == ["t5"]
    assert spool_row(report, ROAD)["verdict"] == "unknown"


def test_3_an_unreadable_gcode_file_states_nothing():
    assert usage_from_gcode_facts({"available": False, "error": "that file does not exist"}) == {}
    with pytest.raises(AssemblyInputError):
        usage_from_gcode_facts({"available": True, "slots": [{"tool": -1, "grams": 3}]})


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), "12", True, 1e12])
def test_3_unusable_gram_figures_are_refused_not_coerced(bad):
    doc = six_tile()
    doc["tiles"][0]["usage"]["slot:0"] = bad
    with pytest.raises(AssemblyInputError):
        read_assembly(doc)


# -- 4. missing part listed; deleted library project is "missing" ------------------
def test_4_a_part_with_no_tile_is_listed_as_missing():
    report = run(six_tile(), [])
    assert [p["part_id"] for p in report["parts"]["missing"]] == ["pier"]
    doc = six_tile()
    doc["tiles"][0]["part_id"] = "ghost"
    report = run(doc, [])
    assert "quay" in [p["part_id"] for p in report["parts"]["missing"]]
    assert report["parts"]["unlisted_tiles"] == ["t1"]


def test_4_library_cross_reference_by_project_id_and_sha256():
    sha = "1" * 64
    ok = run(six_tile(), [], lookup=lambda pid: {"sha256": sha})["tiles"][0]["library"]["status"]
    gone = run(six_tile(), [], lookup=lambda pid: None)["tiles"][0]["library"]["status"]
    changed = run(six_tile(), [], lookup=lambda pid: {"sha256": "2" * 64})["tiles"][0]["library"]["status"]
    unread = run(six_tile(), [], lookup=lambda pid: {"sha256": None})["tiles"][0]["library"]["status"]
    unchecked = run(six_tile(), [])["tiles"][0]["library"]["status"]
    assert (ok, gone, changed, unread, unchecked) == ("linked", "missing", "changed", "unverified", "unverified")
    assert run(six_tile(), [])["tiles"][1]["library"]["status"] == "unlinked"


def test_4_a_deleted_library_project_reads_missing_through_the_route(tmp_path):
    real = tmp_path / "model.3mf"
    real.write_bytes(b"synthetic bytes")
    digest = hashlib.sha256(b"synthetic bytes").hexdigest()
    db = Path(paths.data_dir()) / "library.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT, source_path TEXT)")
    conn.execute("INSERT INTO projects VALUES (11, 'x', ?)", (str(real),))
    conn.commit()
    conn.close()
    doc = six_tile()
    doc["tiles"][0]["library"]["sha256"] = digest
    status, body = routes_assemblies.evaluate({"assembly": doc})
    assert status == 200 and body["report"]["tiles"][0]["library"]["status"] == "linked"
    real.write_bytes(b"changed")
    assert routes_assemblies.evaluate({"assembly": doc})[1]["report"]["tiles"][0]["library"]["status"] == "changed"
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM projects")
    conn.commit()
    conn.close()
    assert routes_assemblies.evaluate({"assembly": doc})[1]["report"]["tiles"][0]["library"]["status"] == "missing"
    assert real.read_bytes() == b"changed"            # the model file itself is never touched


def test_4_no_library_database_is_never_created_by_an_evaluation():
    routes_assemblies.evaluate({"assembly": six_tile()})
    assert not (Path(paths.data_dir()) / "library.db").exists()


# -- 5. seam scale -------------------------------------------------------------------
def test_5_seam_scale_mismatch_is_flagged_and_unknown_scale_stays_unknown():
    assert run(six_tile(), [])["seam_scale"]["status"] == "consistent"
    doc = six_tile()
    doc["tiles"][2]["scale"] = 95
    assert run(doc, [])["seam_scale"]["status"] == "mismatch"
    doc = six_tile()
    doc["tiles"][2]["scale"] = None
    result = run(doc, [])["seam_scale"]
    assert result["status"] == "unknown" and result["unknown"] == ["t3"]
    doc["tiles"][3]["scale"] = 120
    assert run(doc, [])["seam_scale"]["status"] == "mismatch"


# -- 6. attribution manifest retained ---------------------------------------------------
def test_6_attribution_is_retained_through_evaluate_save_and_load():
    doc = six_tile()
    report = run(doc, [])
    assert report["attribution"] == doc["attribution"]
    assert report["tiles"][0]["attribution"] == {"author": "Example Maker"}
    saved = store.save(doc)
    loaded = store.get(saved["id"])["assembly"]
    assert loaded["attribution"] == doc["attribution"]
    assert loaded["tiles"][0]["attribution"] == {"author": "Example Maker"}


# -- 7. shortage / unknown / stale ---------------------------------------------------------
def test_7_a_shared_spool_smaller_than_the_cumulative_need_is_a_shortage_naming_spool_and_tiles():
    report = run(six_tile(), [reading(ROAD, 150), reading(WATER, 500)])
    road = spool_row(report, ROAD)
    assert report["verdict"] == "shortage"
    assert road["verdict"] == "shortage" and road["spool"] == ROAD
    assert road["starving_tiles"] == ["t4", "t5", "t6"]
    assert road["shortfall_g"] == 90.0
    assert spool_row(report, WATER)["verdict"] == "enough"


def test_7_enough_when_supply_covers_every_tile():
    report = run(six_tile(), [reading(ROAD, 240), reading(WATER, 150)])
    assert report["verdict"] == "enough"
    assert all(s["verdict"] == "enough" for s in report["spools"])


def test_7_missing_or_null_supply_is_unknown_not_enough_and_not_shortage():
    report = run(six_tile(), [reading(WATER, 500)])
    assert spool_row(report, ROAD)["verdict"] == "unknown" and report["verdict"] == "unknown"
    report = run(six_tile(), [reading(ROAD, None), reading(WATER, 500)])
    assert spool_row(report, ROAD)["verdict"] == "unknown"
    report = run(six_tile(), [reading(ROAD, 500, ttl=0), reading(WATER, 500)])
    assert spool_row(report, ROAD)["verdict"] == "unknown"
    no_time = {"spool": ROAD, "remaining_g": 10, "ttl_s": 600}
    assert spool_row(run(six_tile(), [no_time, reading(WATER, 500)]), ROAD)["verdict"] == "unknown"


def test_7_stale_supply_is_stale_even_when_the_figure_is_small_or_large():
    for grams in (10, 5000):
        report = run(six_tile(), [reading(ROAD, grams, age=5000, ttl=600), reading(WATER, 500)])
        row = spool_row(report, ROAD)
        assert row["verdict"] == "stale" and row["starving_tiles"] == []
        assert report["verdict"] == "stale"


def test_7_a_restored_reading_and_an_ageing_reading_are_not_loadout_evidence():
    historical = run(six_tile(), [reading(ROAD, 5000, historical=True), reading(WATER, 500)])
    assert spool_row(historical, ROAD)["verdict"] == "stale"
    ageing = run(six_tile(), [reading(ROAD, 5000, age=400, ttl=600), reading(WATER, 500)])
    assert spool_row(ageing, ROAD)["verdict"] == "stale"
    allowed = run(six_tile(), [reading(ROAD, 5000, age=400, ttl=600, ageing_ok=True), reading(WATER, 500)])
    assert spool_row(allowed, ROAD)["verdict"] == "enough"


def test_7_conflicting_readings_for_one_spool_are_not_averaged_or_picked():
    report = run(six_tile(), [reading(ROAD, 500), reading(ROAD, 100), reading(WATER, 500)])
    assert spool_row(report, ROAD)["verdict"] == "unknown"


def test_7_a_known_overrun_is_a_shortage_even_when_other_tiles_state_no_grams():
    doc = six_tile()
    doc["tiles"][5].pop("usage")
    report = run(doc, [reading(ROAD, 100), reading(WATER, 500)])
    road = spool_row(report, ROAD)
    assert road["verdict"] == "shortage" and road["unknown_tiles"] == ["t6"]
    assert "lower bound" in road["reason"]


# -- 8. foundation-aware, legacy sufficiency never used -------------------------------------------
def _source_files():
    root = Path(ev.__file__).parent
    return [*root.glob("*.py"), Path(routes_assemblies.__file__)]


def test_8_material_plan_sufficiency_is_never_referenced():
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        assert "_sufficiency" not in text, path
        assert not re.search(r"\bmaterial_plan\b\s*(import|\.)|import\s+material_plan|from\s+\.+\s*material_plan", text), path
        assert not re.search(r"\bproject_materials\b|\breadiness\b", text), path


def test_8_supply_goes_through_observation_freshness(monkeypatch):
    seen = []
    real = ev.obs_mod.freshness
    monkeypatch.setattr(ev.obs_mod, "freshness", lambda o, now=None: (seen.append(o.observation_id), real(o, now))[1])
    run(six_tile(), [reading(ROAD, 500), reading(WATER, 500)])
    assert sorted(seen) == ["supply:0", "supply:1"]


# -- 9. unresolved slot-to-spool binding ---------------------------------------------------------------
def test_9_a_role_without_a_binding_leaves_physical_consumption_unknown():
    doc = six_tile()
    del doc["bindings"]["water"]
    report = run(doc, [reading(ROAD, 5000), reading(WATER, 5000)])
    assert report["verdict"] == "unknown"
    assert {u["reason"] for u in report["unresolved"]} == {"no_binding"}
    assert len(report["unresolved"]) == 6
    assert [s["spool"] for s in report["spools"]] == [ROAD]


def test_9_a_slot_with_grams_and_no_role_or_two_roles_is_unresolved():
    doc = six_tile()
    doc["tiles"][0]["usage"]["slot:3"] = 10
    doc["tiles"][1]["roles"]["extra"] = "slot:0"
    report = run(doc, [reading(ROAD, 5000), reading(WATER, 5000)])
    reasons = {(u["tile_id"], u["slot"]): u["reason"] for u in report["unresolved"]}
    assert reasons == {("t1", "slot:3"): "no_role", ("t2", "slot:0"): "ambiguous_role"}
    assert report["verdict"] == "unknown"


def test_9_a_known_zero_on_an_unresolved_slot_does_not_block():
    doc = six_tile()
    doc["tiles"][0]["usage"]["slot:3"] = 0
    report = run(doc, [reading(ROAD, 5000), reading(WATER, 5000)])
    assert report["unresolved"] == [] and report["verdict"] == "enough"


# -- 10. assemblies.db through the store, cross-reference without a foreign key -----------------------------
def test_10_assemblies_db_lives_in_the_foundation_store_and_has_no_foreign_key():
    saved = store.save(six_tile())
    db = Path(paths.data_dir()) / "store" / "assemblies.db"
    assert db.is_file() and saved["revision"] == 1
    conn = sqlite3.connect(db)
    try:
        for table in ("assemblies", "tile_refs"):
            assert conn.execute(f"PRAGMA foreign_key_list({table})").fetchall() == []
        assert conn.execute("SELECT library_project_id, library_sha256 FROM tile_refs").fetchall() == [(11, "1" * 64)]
        assert conn.execute("PRAGMA user_version").fetchone()[0] == store.VERSION
    finally:
        conn.close()
    assert [a["assembly_id"] for a in store.assemblies_for_project(11)] == [saved["id"]]
    assert store.assemblies_for_project(11, "2" * 64) == []
    assert store.assemblies_for_project(12) == []


def test_10_update_needs_the_revision_it_was_read_at_and_a_stale_one_changes_nothing():
    first = store.save(six_tile())
    doc = six_tile()
    doc["name"] = "Renamed"
    second = store.save(doc, first["id"], first["revision"])
    assert second["revision"] == 2
    with pytest.raises(RevisionConflict):
        store.save(six_tile(), first["id"], first["revision"])
    with pytest.raises(RevisionConflict):
        store.save(six_tile(), first["id"], None)
    assert store.get(first["id"])["assembly"]["name"] == "Renamed"
    with pytest.raises(store.NotFound):
        store.save(six_tile(), 999, 1)


def test_10_deleting_a_saved_assembly_removes_its_refs_only():
    saved = store.save(six_tile())
    assert store.delete(saved["id"]) is True and store.delete(saved["id"]) is False
    assert store.list_saved() == [] and store.assemblies_for_project(11) == []


def test_10_a_newer_database_is_refused_untouched():
    store.save(six_tile())
    db = Path(paths.data_dir()) / "store" / "assemblies.db"
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {store.VERSION + 1}")
    conn.close()
    from snapstudio_core.foundation.store import StoreVersionError
    with pytest.raises(StoreVersionError):
        store.list_saved()
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM assemblies").fetchone()[0] == 1
    conn.close()


# -- routes: shapes through the seam -----------------------------------------------------------------------
class _Handler:
    def __init__(self):
        self.sent = []

    def _send(self, code, obj):
        self.sent.append((code, obj))


def call(path, data):
    handler = _Handler()
    assert ext_routes.dispatch(handler, path, data) is True
    return handler.sent[-1]


def test_routes_are_registered_under_the_assemblies_prefix():
    for path in ("evaluate", "save", "list", "get", "delete"):
        assert f"/assemblies/{path}" in ext_routes.ROUTES


def test_route_evaluate_returns_an_advisory_report():
    status, body = call("/assemblies/evaluate", {"assembly": six_tile(), "now": NOW,
                                                 "supply": [reading(ROAD, 150), reading(WATER, 500)]})
    assert status == 200
    assert body["report"]["verdict"] == "shortage"
    assert body["report"]["advisory"].startswith("Advisory only")


@pytest.mark.parametrize("data", [
    {}, {"assembly": []}, {"assembly": {"name": ""}}, {"assembly": {"name": "x", "tiles": "no"}},
    {"assembly": {"name": "x"}, "supply": "no"}, {"assembly": {"name": "x"}, "now": "soon"},
    {"assembly": {"name": "x"}, "supply": [{"spool": {"provider_instance_id": "p"}, "remaining_g": 1}]},
    {"assembly": {"name": "x", "schema_version": "assembly/9"}},
])
def test_route_evaluate_refuses_bad_input_with_400(data):
    status, body = call("/assemblies/evaluate", data)
    assert status == 400 and body["error"] == "invalid" and "Traceback" not in body["message"]


def test_route_save_get_list_delete_round_trip_and_error_shapes():
    status, saved = call("/assemblies/save", {"assembly": six_tile()})
    assert status == 200 and saved["revision"] == 1
    assert call("/assemblies/list", {})[1]["assemblies"][0]["tiles"] == 6
    assert call("/assemblies/get", {"id": saved["id"]})[1]["assembly"]["name"] == six_tile()["name"]
    status, body = call("/assemblies/save", {"assembly": six_tile(), "id": saved["id"], "expected_revision": 7})
    assert status == 422 and body["error"] == "refusal"
    assert call("/assemblies/get", {"id": 999})[0] == 400
    assert call("/assemblies/get", {"id": "1"})[0] == 400
    assert call("/assemblies/delete", {"id": saved["id"]})[1] == {"deleted": True}


def test_route_responses_never_echo_a_credential_like_header_value():
    doc = six_tile()
    doc["attribution"].append({"item": "x", "author": "SENTINEL-KEY-9f3a"})
    status, body = call("/assemblies/evaluate", {"assembly": {**doc, "tiles": "bad"}})
    assert "SENTINEL-KEY-9f3a" not in json.dumps(body)


# -- guards: source greps over the package -----------------------------------------------------------------------
def test_g1_the_package_has_no_network_or_printer_control_references():
    banned = ("urlopen", "requests", "http.client", "socket", "moonraker", "netguard", "pause", "resume", "cancel")
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        for word in banned:
            assert not re.search(rf"\b{re.escape(word)}\b", text), (path.name, word)


def test_g3_the_package_never_counts_heads_from_slot_or_nozzle_counts():
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        assert "slot_count" not in text and "len(nozzles)" not in text, path


def test_c7_no_overclaiming_words_in_package_files():
    banned = ["simul" + "taneous", "guaran" + "teed", "100" + "%"]
    files = _source_files() + list(FIXTURES.glob("*")) + [HERE.parents[2] / "docs" / "internal" / "ASSEMBLIES.md"]
    for path in files:
        if path.is_file():
            text = path.read_text(encoding="utf-8").lower()
            for word in banned:
                assert word not in text, (path.name, word)


def test_c3_the_fixture_directory_has_provenance():
    text = (FIXTURES / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "synthetic" in text and "documentation-derived" in text


def test_the_document_round_trips_unchanged_and_bounds_hold():
    doc = six_tile()
    once = read_assembly(doc).to_dict()
    assert read_assembly(once).to_dict() == once
    big = copy.deepcopy(doc)
    big["tiles"] = [{"tile_id": f"x{i}", "name": "n"} for i in range(65)]
    with pytest.raises(AssemblyInputError):
        read_assembly(big)
    dup = copy.deepcopy(doc)
    dup["tiles"][1]["tile_id"] = "t1"
    with pytest.raises(AssemblyInputError):
        read_assembly(dup)
