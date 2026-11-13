"""SpoolRef identity, aliases and field-by-field reconcile."""
import datetime
import json

import pytest

from snapstudio_core.foundation import materials as m
from snapstudio_core.foundation import observations as o

NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
EPOCH = NOW.timestamp()


def ob(oid, age=0, ttl=600, **kw):
    observed = kw.pop("observed_at", o.to_iso(EPOCH - age))
    return o.Observation(observation_id=oid, subject={"kind": "spool", "id": "s"}, field="x", value=None,
                         source={"provider_instance_id": "p"}, observed_at=observed,
                         received_at=o.to_iso(EPOCH), ttl_s=ttl, **kw)


def fact(field, value, prov, oid):
    return m.MaterialFact(field, value, prov, oid)


def rec(*pairs):
    return {x.observation_id: x for x in pairs}


# -- SpoolRef / alias -----------------------------------------------------
def test_two_providers_spool_42_stay_distinct():
    a, b = m.SpoolRef("spoolman-1", "42"), m.SpoolRef("afc-1", "42")
    assert a != b
    assert not m.same_spool(a, b)
    assert len({a, b}) == 2


def test_same_provider_same_id_equal_and_int_ids_coerced():
    assert m.SpoolRef("p", 42) == m.SpoolRef("p", "42")
    assert m.same_spool(m.SpoolRef("p", 42), m.SpoolRef("p", "42"))


@pytest.mark.parametrize("p,s", [("", "1"), ("p", ""), ("p", "  "), (None, "1"), ("p", None), ("p", True), ("p", 1.5),
                                 (True, "1")])
def test_spoolref_rejects_empty_or_odd_ids(p, s):
    with pytest.raises(ValueError):
        m.SpoolRef(p, s)


def test_alias_merges_declared_spools_only():
    a, b, c = m.SpoolRef("p1", "42"), m.SpoolRef("p2", "42"), m.SpoolRef("p3", "42")
    alias = m.SpoolAlias((a, b), evidence="user matched by label", declared_by="user")
    assert m.same_spool(a, b, [alias]) and m.same_spool(b, a, [alias])
    assert not m.same_spool(a, c, [alias])
    assert not m.same_spool(a, b)


def test_alias_is_transitive_across_declarations():
    a, b, c = m.SpoolRef("p1", "1"), m.SpoolRef("p2", "2"), m.SpoolRef("p3", "3")
    aliases = [m.SpoolAlias((a, b), "e", "user"), m.SpoolAlias((b, c), "e", "user")]
    assert m.same_spool(a, c, aliases)


def test_alias_needs_two_refs():
    with pytest.raises(ValueError):
        m.SpoolAlias((m.SpoolRef("p", "1"),), "e", "u")
    with pytest.raises(ValueError):
        m.SpoolAlias(("p:1", "q:1"), "e", "u")


def test_same_colour_different_spools_stay_distinct():
    a, b = m.SpoolRef("p1", "1"), m.SpoolRef("p1", "2")
    red = fact("colour", "#ff0000", "provider", "o1")
    assert red.value == "#ff0000"
    assert not m.same_spool(a, b)
    ra = m.reconcile([m.MaterialFact("spool", a, "provider", "o1"), red], rec(ob("o1")), NOW)
    rb = m.reconcile([m.MaterialFact("spool", b, "provider", "o1"), red], rec(ob("o1")), NOW)
    assert ra.spool != rb.spool


def test_alias_dict_round_trip_through_json():
    alias = m.SpoolAlias((m.SpoolRef("p1", "1"), m.SpoolRef("p2", "9")), "e", "user")
    data = json.loads(json.dumps(alias.to_dict()))
    assert data["refs"][1] == {"provider_instance_id": "p2", "provider_spool_id": "9"}


# -- facts ---------------------------------------------------------------
def test_fact_validates_vocabulary():
    with pytest.raises(ValueError):
        m.MaterialFact("flavour", "x", "user", "o")
    with pytest.raises(ValueError):
        m.MaterialFact("colour", "x", "trust-me", "o")


def test_remaining_quantity_guards():
    assert m.RemainingQuantity(None).grams is None
    assert m.RemainingQuantity(0).grams == 0
    for bad in (-1, float("nan"), float("inf"), True, "5"):
        with pytest.raises(ValueError):
            m.RemainingQuantity(bad)


# -- reconcile -----------------------------------------------------------
def test_fresh_user_fact_beats_stale_rfid_fact_and_conflict_retained():
    rfid = fact("colour", "#ff0000", "rfid", "o_rfid")
    user = fact("colour", "#00ff00", "user", "o_user")
    view = m.reconcile([rfid, user], rec(ob("o_rfid", age=5000), ob("o_user", age=10)), NOW)
    entry = view.fields["colour"]
    assert entry["value"] == "#00ff00" and entry["provenance"] == "user"
    assert entry["freshness"]["state"] == o.FRESH
    assert len(view.conflicts) == 1
    c = view.conflicts[0]
    assert c["field"] == "colour" and c["a"] == user and c["b"] == rfid


def test_fresh_rfid_beats_fresh_user_only_on_tie():
    rfid = fact("brand", "A", "rfid", "o1")
    user = fact("brand", "B", "user", "o2")
    tie = m.reconcile([user, rfid], rec(ob("o1", age=30), ob("o2", age=30)), NOW)
    assert tie.fields["brand"]["provenance"] == "rfid"
    newer_user = m.reconcile([user, rfid], rec(ob("o1", age=30), ob("o2", age=10)), NOW)
    assert newer_user.fields["brand"]["provenance"] == "user"


@pytest.mark.parametrize("order", [0, 1])
def test_equal_timestamps_resolved_by_rank_regardless_of_input_order(order):
    facts = [fact("material", "PLA", "provider", "a"), fact("material", "PETG", "user", "b"),
             fact("material", "ABS", "derived", "c")]
    if order:
        facts.reverse()
    view = m.reconcile(facts, rec(ob("a", 20), ob("b", 20), ob("c", 20)), NOW)
    assert view.fields["material"]["value"] == "PETG"
    assert {c["b"].value for c in view.conflicts} == {"PLA", "ABS"}


def test_rank_order():
    assert m.RANK["rfid"] > m.RANK["user"] > m.RANK["provider"] > m.RANK["project"] > m.RANK["derived"] > m.RANK["unknown"]


def test_equal_values_do_not_conflict_and_compare_case_insensitively():
    view = m.reconcile([fact("material", "PLA", "rfid", "a"), fact("material", " pla ", "user", "b")],
                       rec(ob("a", 1), ob("b", 1)), NOW)
    assert view.conflicts == []


def test_provenance_never_promoted():
    view = m.reconcile([fact("colour", "#fff", "derived", "a")], rec(ob("a", 1)), NOW)
    assert view.fields["colour"]["provenance"] == "derived"
    mixed = m.reconcile([fact("colour", "#fff", "derived", "a"), fact("colour", "#fff", "rfid", "b")],
                        rec(ob("a", 1), ob("b", 100)), NOW)
    assert mixed.fields["colour"]["provenance"] == "derived"   # the newer fact wins; no rfid borrowed


def test_weight_only_provider_does_not_inherit_identity_fields():
    full = [fact("material", "PLA", "rfid", "r1"), fact("brand", "Acme", "rfid", "r2"),
            fact("spool", m.SpoolRef("afc", "7"), "rfid", "r3")]
    weight = [fact("remaining_g", 310.0, "provider", "w1")]
    view = m.reconcile(weight, rec(ob("w1", 5)), NOW)
    assert set(view.fields) == {"remaining_g"}
    assert view.spool is None
    both = m.reconcile(full + weight, rec(ob("r1", 5), ob("r2", 5), ob("r3", 5), ob("w1", 5)), NOW)
    assert both.fields["remaining_g"]["provenance"] == "provider"
    assert both.fields["remaining_g"]["observation_id"] == "w1"


def test_fields_reconciled_independently():
    view = m.reconcile([fact("colour", "#111", "rfid", "a"), fact("colour", "#222", "user", "b"),
                        fact("material", "PLA", "rfid", "a"), fact("material", "PETG", "user", "c")],
                       rec(ob("a", 10), ob("b", 20), ob("c", 400)), NOW)
    assert view.fields["colour"]["provenance"] == "rfid"      # newer
    assert view.fields["material"]["provenance"] == "rfid"    # c is ageing, a fresh


def test_fresh_beats_ageing_tier_equal_then_age_decides():
    view = m.reconcile([fact("td", 1.0, "user", "a"), fact("td", 2.0, "rfid", "b")],
                       rec(ob("a", 500), ob("b", 100)), NOW)
    assert view.fields["td"]["value"] == 2.0


def test_fresh_or_ageing_beats_stale_even_with_higher_rank():
    view = m.reconcile([fact("td", 1.0, "rfid", "a"), fact("td", 2.0, "derived", "b")],
                       rec(ob("a", 5000), ob("b", 400)), NOW)
    assert view.fields["td"]["value"] == 2.0 and view.fields["td"]["freshness"]["state"] == o.AGEING


def test_unknown_observed_at_loses_to_known_time_stale():
    unknown = ob("a", observed_at=None)
    known_stale = ob("b", age=9999)
    view = m.reconcile([fact("brand", "X", "rfid", "a"), fact("brand", "Y", "derived", "b")],
                       rec(unknown, known_stale), NOW)
    assert view.fields["brand"]["value"] == "Y"
    assert view.fields["brand"]["freshness"]["state"] == o.STALE


def test_two_unknown_times_fall_back_to_rank():
    view = m.reconcile([fact("brand", "X", "derived", "a"), fact("brand", "Y", "user", "b")],
                       rec(ob("a", observed_at=None), ob("b", observed_at=None)), NOW)
    assert view.fields["brand"]["value"] == "Y"
    assert view.fields["brand"]["freshness"]["state"] == o.UNKNOWN


def test_unusable_observation_discarded_with_diagnostic():
    bad_ttl = ob("a", ttl=0)
    future = ob("b", observed_at=o.to_iso(EPOCH + 4000))
    view = m.reconcile([fact("colour", "#1", "rfid", "a"), fact("colour", "#2", "rfid", "b"),
                        fact("colour", "#3", "derived", "c")], rec(bad_ttl, future, ob("c", 50)), NOW)
    assert view.fields["colour"]["value"] == "#3"
    assert [d.code for d in view.diagnostics].count("fact_discarded_unusable") == 2
    only_bad = m.reconcile([fact("colour", "#1", "rfid", "a")], rec(bad_ttl), NOW)
    assert "colour" not in only_bad.fields


def test_fact_without_observation_is_unknown_not_fresh():
    view = m.reconcile([fact("colour", "#1", "user", "ghost")], {}, NOW)
    entry = view.fields["colour"]
    assert entry["freshness"]["state"] == o.UNKNOWN
    assert entry["freshness"]["usable_for_loadout"] is False


def test_historical_fact_never_usable_for_loadout_in_view():
    view = m.reconcile([fact("remaining_g", 200, "provider", "a")], rec(ob("a", 0, historical=True)), NOW)
    assert view.fields["remaining_g"]["freshness"]["usable_for_loadout"] is False


def test_view_spool_taken_from_winning_spool_fact():
    ref = m.SpoolRef("sm", "3")
    view = m.reconcile([fact("spool", ref, "user", "a")], rec(ob("a", 1)), NOW)
    assert view.spool == ref


def test_conflicting_spool_refs_are_retained_not_merged():
    a, b = m.SpoolRef("p1", "42"), m.SpoolRef("p2", "42")
    view = m.reconcile([fact("spool", a, "rfid", "x"), fact("spool", b, "user", "y")],
                       rec(ob("x", 10), ob("y", 10)), NOW)
    assert view.spool == a and len(view.conflicts) == 1


def test_empty_input():
    view = m.reconcile([], {}, NOW)
    assert view.fields == {} and view.conflicts == [] and view.spool is None


def test_reconcile_is_deterministic_for_total_ties():
    facts = [fact("brand", "A", "user", "x"), fact("brand", "B", "user", "y")]
    obs = rec(ob("x", 10), ob("y", 10))
    a = m.reconcile(facts, obs, NOW).fields["brand"]["observation_id"]
    b = m.reconcile(list(reversed(facts)), obs, NOW).fields["brand"]["observation_id"]
    assert a == b


# -- serialisation / decode ----------------------------------------------
def test_view_round_trip():
    ref = m.SpoolRef("sm", "3")
    view = m.reconcile([fact("spool", ref, "user", "a"), fact("colour", "#1", "rfid", "b"),
                        fact("colour", "#2", "user", "c")], rec(ob("a", 1), ob("b", 400), ob("c", 20)), NOW)
    data = json.loads(json.dumps(view.to_dict()))
    dec = m.MaterialView.from_dict(data)
    assert dec.valid_for_evaluation, dec.diagnostics
    assert dec.value.spool == ref
    assert dec.value.to_dict()["fields"] == data["fields"]
    assert len(dec.value.conflicts) == 1


@pytest.mark.parametrize("mutate", [
    lambda d: d["fields"]["colour"].pop("value"),
    lambda d: d["fields"]["colour"].update(provenance="trust-me"),
    lambda d: d["fields"]["colour"].pop("freshness"),
    lambda d: d["fields"].update(flavour={"value": 1}),
    lambda d: d.update(fields=[1]),
    lambda d: d.update(schema_version="material_view/9"),
])
def test_view_decode_rejects_damage_without_raising(mutate):
    view = m.reconcile([fact("colour", "#1", "user", "a")], rec(ob("a", 1)), NOW)
    data = json.loads(json.dumps(view.to_dict()))
    mutate(data)
    dec = m.MaterialView.from_dict(data)
    assert dec.value is None and dec.valid_for_evaluation is False and dec.diagnostics


def test_view_decode_non_object():
    assert m.MaterialView.from_dict("[]").value is None


def test_lane_occupancy_round_trip_and_decode():
    lane = m.LaneOccupancy("lane:1", m.SpoolRef("p", "2"), "loaded", "o1")
    assert lane.to_dict()["spool"] == {"provider_instance_id": "p", "provider_spool_id": "2"}
    r = m.Reader({"lane_id": "lane:1", "state": "empty"})
    assert m.LaneOccupancy._read(r) == m.LaneOccupancy("lane:1", None, "empty", None)
    bad = m.Reader({"lane_id": "lane:1", "state": "full"})
    assert m.LaneOccupancy._read(bad) is None and bad.diagnostics
