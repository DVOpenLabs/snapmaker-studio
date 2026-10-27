"""Setup report (plan tests 7, 8, 11): distinct verdicts, honest freshness, the legacy-limitation notice.

Evidence label: fixture-tested. Topologies for the multiACE-like and AFC-like cases are hand-built
foundation objects; the accessory adapters are a separate package and are not imported here.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from snapstudio_core import setup_view
from snapstudio_core.adapters import registry
from snapstudio_core.adapters import host as _host  # noqa: F401
from snapstudio_core.adapters.base import AdapterResult
from snapstudio_core.foundation import observations as obs_mod
from snapstudio_core.foundation import topology as topo

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "adapters" / "host"
RECEIVED = "2026-10-26T12:00:00Z"
BANNED = re.compile(r"\b\d+ nozzles?\b|simultaneous|guarantee|100\s*%|coming soon|is coming|will live|coming later",
                    re.IGNORECASE)


def _parse(system: str, version: str, case: str, adapter_id: str) -> AdapterResult:
    raw = json.loads((FIXTURES / system / version / f"{case}.json").read_text(encoding="utf-8"))
    return registry.get(adapter_id).parse(raw["bundle"], received_at=RECEIVED, source_version=raw.get("source_version"))


def _stock(case: str) -> AdapterResult:
    return _parse("moonraker_stock", "moonraker-0.9", case, "host.moonraker_stock")


def _heads(n: int) -> list:
    return [topo.PhysicalToolhead(topo.head_id(i), i) for i in range(n)]


def _result(t: topo.Topology) -> AdapterResult:
    return AdapterResult("hand.built", "test", topology=t)


def _topology(*, heads=4, slots=4, lanes_per_unit=0, unit_kind=None, reach="all", complete=True,
              bindings=None) -> topo.Topology:
    units = []
    if unit_kind:
        uid = topo.unit_id(unit_kind, "u1")
        lanes = []
        for i in range(lanes_per_unit):
            r = [topo.head_id(h) for h in range(heads)] if reach == "all" else None
            lanes.append(topo.Lane(topo.lane_id(uid, i), uid, i, reachable_heads=r))
        units.append(topo.FeederUnit(uid, unit_kind, None, lanes))
    return topo.Topology(snapshot_id="snap:hand", received_at=RECEIVED, heads=_heads(heads), units=units,
                         slots=[topo.LogicalSlot(topo.slot_id(i), i) for i in range(slots)],
                         bindings=bindings or [], complete=complete)


def _eight() -> list:
    return [topo.ProjectSlotRequirement(i, "PLA", None) for i in range(8)]


# plan test 7
def test_eight_materials_give_three_distinct_verdicts_without_counting_nozzles():
    stock = _result(_topology())
    multiace = _result(_topology(lanes_per_unit=8, unit_kind="multiace", reach="all"))
    afc = _result(_topology(lanes_per_unit=8, unit_kind="afc", reach=None))
    free = topo.ResourceConstraints(exclusive_paths=[], heads_single_active=False)
    verdicts = {}
    for name, res, cons in (("stock", stock, None), ("multiace", multiace, free), ("afc", afc, None)):
        rep = setup_view.evaluate([res], requirements=_eight(), constraints=cons, now=RECEIVED)
        a = rep["entries"][0]["assignability"]
        verdicts[name] = a["verdict"]
        text = json.dumps(rep)
        assert not BANNED.search(text), (name, BANNED.search(text).group(0))
        assert not BANNED.search(a["text"])
    assert verdicts == {"stock": "cannot_match", "multiace": "can_match", "afc": "unknown"}
    assert len(set(verdicts.values())) == 3


def test_unknown_reach_gives_a_range_not_a_number():
    afc = _result(_topology(lanes_per_unit=8, unit_kind="afc", reach=None))
    a = setup_view.evaluate([afc], requirements=_eight(), now=RECEIVED)["entries"][0]["assignability"]
    assert a["assignable"] is None and a["bound"]["min"] < a["bound"]["max"]
    assert "not known" in a["text"]


def test_incomplete_head_list_is_unknown_not_cannot_match():
    for built in (_result(_topology(heads=0, slots=0, complete=False)),
                  _result(_topology(heads=2, complete=False))):
        entry = setup_view.evaluate([built], requirements=_eight()[:1], now=RECEIVED)["entries"][0]
        a = entry["assignability"]
        assert a["verdict"] == "unknown" and a["assignable"] is None and a["bound"] is None
        assert a["requested"] == 1 and "not known" in a["text"]
    octo = _parse("octoprint", "octoprint-1.9-synthetic", "version_no_api_key", "host.octoprint")
    entry = setup_view.evaluate([octo], requirements=_eight()[:1], now=RECEIVED)["entries"][0]
    assert entry["assignability"]["verdict"] == "unknown" and entry["assignability"]["bound"] is None
    complete = setup_view.evaluate([_result(_topology())], requirements=_eight()[:1], now=RECEIVED)
    assert complete["entries"][0]["assignability"]["verdict"] == "can_match"


def test_stock_default_shape_does_not_claim_a_logical_slot_count():
    result = _parse("moonraker_stock", "u1-klipper-340b4232", "upstream_default_shape", "host.moonraker_stock")
    entry = setup_view.evaluate([result], now=RECEIVED)["entries"][0]
    cap = {c["key"]: c for c in entry["capabilities"]}
    assert cap["logical_slots"]["state"] == "unknown"
    assert "4 filament entries" in cap["logical_slots"]["reason"] and "not known" in cap["logical_slots"]["reason"]
    assert "logical_slots_beyond_filament_arrays" in entry["unknowns"]
    mapping = cap["slot_mapping"]["reason"]
    assert "not shown" in mapping and "which head each slot uses" not in mapping


def test_unset_none_sentinel_is_not_a_material():
    from snapstudio_core.adapters.host import moonraker_parse as mp
    cfg = {"filament_exist": [True, True], "filament_type": ["NONE", "PLA"],
           "filament_sub_type": ["NONE", "NONE"], "filament_vendor": ["NONE", "NONE"]}
    entries = mp.loaded_filaments_from(cfg)
    assert entries[0]["material"] is None and entries[0]["vendor"] is None
    assert entries[1]["material"] == "PLA" and entries[1]["vendor"] is None


def test_no_requirements_means_no_verdict():
    rep = setup_view.evaluate([_result(_topology())], now=RECEIVED)
    assert rep["entries"][0]["assignability"] is None


# plan test 8
def test_stale_observation_is_shown_as_stale():
    res = _stock("four_heads_loaded")
    fresh = setup_view.evaluate([res], now="2026-10-26T12:00:05Z")["entries"][0]
    later = setup_view.evaluate([res], now="2026-10-27T12:00:00Z")["entries"][0]
    assert {c["key"]: c["state"] for c in fresh["capabilities"]}["material_data"] == "available"
    states = {c["key"]: c["state"] for c in later["capabilities"]}
    assert states["material_data"] == "stale" and states["physical_heads"] == "stale"
    assert all(r["state"] == obs_mod.STALE for r in later["observations"])
    assert "older than its lifetime" in next(c for c in later["capabilities"] if c["key"] == "material_data")["reason"]
    assert states["spool_identity"] == "unknown"      # unknown stays unknown, never relabelled stale


def test_historical_observation_is_shown_as_historical():
    res = _stock("four_heads_loaded")
    res.observations = [obs_mod.as_historical(o) for o in res.observations]
    entry = setup_view.evaluate([res], now="2026-10-26T12:00:05Z")["entries"][0]
    assert all(r["historical"] and r["usable_for_loadout"] is False for r in entry["observations"])
    cap = next(c for c in entry["capabilities"] if c["key"] == "material_data")
    assert cap["historical"] is True and "earlier session" in cap["reason"]


def test_states_are_the_four_documented_words():
    entries = [_stock("four_heads_loaded"), {"label": "x", "status": "unavailable", "reason": "api_key_missing",
                                             "result": None}]
    rep = setup_view.evaluate(entries, now=RECEIVED)
    seen = {c["state"] for e in rep["entries"] for c in e["capabilities"]}
    assert seen <= set(setup_view.STATES) and {"available", "unknown", "unavailable"} <= seen
    down = rep["entries"][1]
    assert down["reason"] == "api_key_missing" and "API key" in down["reason_text"] and down["counts"] is None


def test_unreadable_reply_claims_nothing():
    bad = _parse("moonraker_stock", "moonraker-0.9", "unknown_version", "host.moonraker_stock")
    entry = setup_view.evaluate([bad], now=RECEIVED)["entries"][0]
    assert {c["state"] for c in entry["capabilities"]} == {"unknown"} and entry["counts"] is None and entry["topology"] is None


def test_counts_come_from_topology_counts_and_32_slots_is_not_32_heads():
    entry = setup_view.evaluate([_stock("hypothetical_thirty_two_logical_four_heads")], now=RECEIVED)["entries"][0]
    assert entry["counts"]["physical_heads"] == 4 and entry["counts"]["logical_slots"] == 32
    nohead = setup_view.evaluate([_stock("hypothetical_thirty_two_logical_no_head_objects")], now=RECEIVED)["entries"][0]
    assert nohead["counts"]["physical_heads"] is None and nohead["counts"]["logical_slots"] == 32


def test_inputs_revision_changes_with_the_inputs():
    a = setup_view.evaluate([_stock("four_heads_loaded")], now=RECEIVED)
    b = setup_view.evaluate([_stock("four_heads_loaded")], requirements=[{"material": "PLA"}], now=RECEIVED)
    c = setup_view.evaluate([_stock("crossed_map_table")], now=RECEIVED)
    revs = {a["inputs_revision"]["revision"], b["inputs_revision"]["revision"], c["inputs_revision"]["revision"]}
    assert len(revs) == 3
    assert a["schema_version"] == "setup_report/1" and json.dumps(a)


# plan test 11
@pytest.mark.parametrize("name,t,applies", [
    ("plain four heads", _topology(), False),
    ("three heads", _topology(heads=3, slots=3), True),
    ("six heads", _topology(heads=6, slots=4), True),
    ("head count unknown", _topology(heads=0, slots=4, complete=False), True),
    ("five logical slots", _topology(heads=4, slots=5), True),
    ("thirty-two logical slots", _topology(heads=4, slots=32), True),
    ("identity bindings", _topology(bindings=[topo.SlotBinding(topo.slot_id(i), topo.head_id(i)) for i in range(4)]),
     False),
    ("crossed bindings", _topology(bindings=[topo.SlotBinding("slot:0", "head:1"), topo.SlotBinding("slot:1", "head:0")]),
     True),
])
def test_legacy_notice_applies_exactly_when_the_setup_is_not_a_plain_four_head_one(name, t, applies):
    rep = setup_view.evaluate([_result(t)], now=RECEIVED)
    notice = rep["legacy_limitation"]
    assert notice["applies"] is applies, name
    if applies:
        assert "assume four heads" in notice["text"] and "not validated for this setup" in notice["text"]
        assert notice["reasons"]
    else:
        assert notice["text"] is None and notice["reasons"] == []


def test_legacy_notice_for_a_lane_binding_and_for_nothing_read():
    uid = topo.unit_id("afc", "u1")
    lane = topo.Lane(topo.lane_id(uid, 0), uid, 0, reachable_heads=["head:0"])
    t = topo.Topology("snap:l", RECEIVED, heads=_heads(4), units=[topo.FeederUnit(uid, "afc", None, [lane])],
                      slots=[topo.LogicalSlot("slot:0", 0)], bindings=[topo.SlotBinding("slot:0", lane.id)],
                      complete=True)
    assert setup_view.evaluate([_result(t)], now=RECEIVED)["legacy_limitation"]["applies"] is True
    nothing = setup_view.evaluate([{"label": "x", "status": "unavailable", "reason": "unreachable", "result": None}])
    assert nothing["legacy_limitation"]["applies"] is True


def test_real_fixtures_drive_the_notice():
    assert setup_view.evaluate([_stock("crossed_map_table")], now=RECEIVED)["legacy_limitation"]["applies"]
    assert setup_view.evaluate([_stock("hypothetical_thirty_two_logical_four_heads")], now=RECEIVED)["legacy_limitation"]["applies"]
    assert not setup_view.evaluate([_stock("four_heads_loaded")], now=RECEIVED)["legacy_limitation"]["applies"]


def test_report_text_avoids_banned_wording_for_every_fixture_case():
    for case in ("four_heads_loaded", "crossed_map_table", "no_map_table", "hypothetical_thirty_two_logical_four_heads",
                 "disconnected", "malformed_arrays", "empty_entries"):
        text = json.dumps(setup_view.evaluate([_stock(case)], requirements=_eight(), now=RECEIVED))
        assert not BANNED.search(text), case
