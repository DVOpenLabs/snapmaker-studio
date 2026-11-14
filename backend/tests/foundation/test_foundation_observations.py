"""Observation freshness, observed_at stamping and decoding."""
import datetime
import json

import pytest

from snapstudio_core.foundation import observations as o
from snapstudio_core.foundation.decode import ERROR, NOTE

NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
NOW_EPOCH = NOW.timestamp()
TTL = 600


def at(seconds_ago):
    return o.to_iso(NOW_EPOCH - seconds_ago)


def make(observed_at="x", ttl=TTL, **kw):
    if observed_at == "x":
        observed_at = at(0)
    base = dict(observation_id="o1", subject={"kind": "lane", "id": "lane:1"}, field="remaining_g", value=100,
                source={"provider_instance_id": "p1", "kind": "afc", "source_version": None, "snapshot_id": None},
                observed_at=observed_at, received_at=at(0), ttl_s=ttl)
    base.update(kw)
    return o.Observation(**base)


def state(obs):
    return o.freshness(obs, NOW)


# -- ttl ------------------------------------------------------------------
@pytest.mark.parametrize("ttl", [0, -1, -0.5, float("nan"), float("inf"), float("-inf"), True, False, None, "600", [600]])
def test_bad_ttl_is_unusable_with_diagnostic(ttl):
    obs = make(ttl=ttl)
    result = state(obs)
    assert result["state"] == o.UNUSABLE
    assert result["usable_for_loadout"] is False
    assert result["age_s"] is None
    assert any(x.code == "ttl_invalid" and x.severity == ERROR for x in obs.diagnostics())


def test_valid_ttl_has_no_diagnostic():
    assert make().diagnostics() == []
    assert make(ttl=0.5).diagnostics() == []


def test_ttl_to_dict_never_emits_nan():
    for ttl in (float("nan"), float("inf"), None):
        text = json.dumps(make(ttl=ttl).to_dict(), allow_nan=False)
        assert json.loads(text)["ttl_s"] is None


# -- observed_at ----------------------------------------------------------
def test_observed_at_missing_is_unknown():
    result = state(make(observed_at=None))
    assert result["state"] == o.UNKNOWN
    assert result["usable_for_loadout"] is False and result["age_s"] is None


@pytest.mark.parametrize("junk", ["garbage", "", "2026-13-45T99:99:99Z", "yesterday", "0x10"])
def test_garbage_observed_at_is_unusable(junk):
    result = state(make(observed_at=junk))
    assert result["state"] == o.UNUSABLE and result["usable_for_loadout"] is False


@pytest.mark.parametrize("junk", [float("nan"), float("inf"), True, [1], {"a": 1}])
def test_non_finite_or_odd_observed_at_is_unusable(junk):
    assert state(make(observed_at=junk))["state"] == o.UNUSABLE


def test_epoch_float_and_int_accepted():
    assert state(make(observed_at=NOW_EPOCH - 10.5))["state"] == o.FRESH
    assert state(make(observed_at=int(NOW_EPOCH) - 10))["state"] == o.FRESH
    assert abs(state(make(observed_at=NOW_EPOCH - 10.5))["age_s"] - 10.5) < 1e-6


def test_epoch_out_of_range_is_unusable_not_a_crash():
    assert state(make(observed_at=1e30))["state"] == o.UNUSABLE


def test_datetime_object_accepted():
    assert state(make(observed_at=NOW - datetime.timedelta(seconds=5)))["state"] == o.FRESH


def test_offset_timestamps_are_converted():
    ts = (NOW - datetime.timedelta(seconds=30)).astimezone(datetime.timezone(datetime.timedelta(hours=5)))
    assert state(make(observed_at=ts.isoformat()))["age_s"] == pytest.approx(30)


# -- skew boundary --------------------------------------------------------
@pytest.mark.parametrize("ahead,expected", [(0, o.FRESH), (1, o.FRESH), (299, o.FRESH), (300, o.FRESH),
                                            (301, o.UNUSABLE), (3600, o.UNUSABLE)])
def test_future_skew_boundary(ahead, expected):
    result = state(make(observed_at=o.to_iso(NOW_EPOCH + ahead)))
    assert result["state"] == expected
    if expected == o.FRESH:
        assert result["age_s"] == 0.0 and result["usable_for_loadout"] is True
    else:
        assert result["usable_for_loadout"] is False


def test_skew_constant_matches_plan():
    assert o.SKEW_TOLERANCE_S == 300


# -- ttl/2 and ttl boundaries --------------------------------------------
@pytest.mark.parametrize("age,expected", [(0, o.FRESH), (299, o.FRESH), (300, o.FRESH), (301, o.AGEING),
                                          (600, o.AGEING), (601, o.STALE), (100000, o.STALE)])
def test_age_boundaries(age, expected):
    assert state(make(observed_at=at(age)))["state"] == expected


def test_fractional_boundaries():
    assert state(make(observed_at=NOW_EPOCH - 300.001))["state"] == o.AGEING
    assert state(make(observed_at=NOW_EPOCH - 600.001))["state"] == o.STALE


def test_usable_for_loadout_rules():
    assert state(make(observed_at=at(10)))["usable_for_loadout"] is True
    assert state(make(observed_at=at(400)))["usable_for_loadout"] is False
    assert state(make(observed_at=at(400), ageing_ok=True))["usable_for_loadout"] is True
    assert state(make(observed_at=at(700), ageing_ok=True))["usable_for_loadout"] is False


def test_naive_string_treated_as_utc_or_unusable_but_never_raises():
    result = state(make(observed_at="2026-01-01T11:59:50"))
    assert result["state"] in (o.FRESH, o.UNUSABLE)


def test_now_argument_forms():
    obs = make(observed_at=at(0))
    assert o.freshness(obs, NOW_EPOCH)["state"] == o.FRESH
    assert o.freshness(obs, NOW.isoformat())["state"] == o.FRESH
    with pytest.raises(ValueError):
        o.freshness(obs, "not a time")
    assert o.freshness(make(observed_at=None))["state"] == o.UNKNOWN  # default now


# -- historical -----------------------------------------------------------
def test_historical_never_usable_even_at_age_zero():
    obs = make(observed_at=at(0), historical=True)
    result = state(obs)
    assert result["state"] == o.FRESH
    assert result["usable_for_loadout"] is False
    assert "earlier session" in result["reason"]


def test_historical_never_usable_even_with_ageing_ok():
    assert state(make(observed_at=at(400), historical=True, ageing_ok=True))["usable_for_loadout"] is False


def test_as_historical_copies_and_marks():
    obs = make(observed_at=at(0))
    hist = o.as_historical(obs)
    assert hist.historical is True and obs.historical is False
    assert hist.subject == obs.subject and hist.subject is not obs.subject
    assert state(hist)["usable_for_loadout"] is False
    assert state(obs)["usable_for_loadout"] is True


# -- clocks are separate -------------------------------------------------
def test_received_at_does_not_affect_freshness():
    old = make(observed_at=at(1000), received_at=at(0))
    assert state(old)["state"] == o.STALE
    assert old.received_at != old.observed_at


def test_unreadable_received_at_is_a_warning_not_unusable():
    obs = make(received_at="garbage")
    assert any(x.code == "received_at_unreadable" for x in obs.diagnostics())
    assert state(obs)["state"] == o.FRESH


def test_unknown_source_kind_is_flagged():
    assert any(x.code == "source_kind_unknown" for x in make(source_kind="telepathy").diagnostics())


# -- tracker: live_query vs cached_record ---------------------------------
def observe(tracker, received, kind, **kw):
    args = dict(observation_id="o", subject={"kind": "spool", "id": "s1"}, field="remaining_g", value=100,
                source={"provider_instance_id": "p"}, source_kind=kind, received_at=received, ttl_s=TTL)
    args.update(kw)
    return tracker.observe(**args)


def test_live_query_observed_at_is_receipt_time_each_read():
    tracker = o.ObservedAtTracker()
    first, diags = observe(tracker, NOW_EPOCH, "live_query")
    second, _ = observe(tracker, NOW_EPOCH + 30, "live_query")
    assert first.observed_at == o.to_iso(NOW_EPOCH)
    assert second.observed_at == o.to_iso(NOW_EPOCH + 30)
    assert second.received_at == second.observed_at
    assert any(x.code == "observed_at_is_receipt_time" and x.severity == NOTE for x in diags)
    assert first.source_kind == "live_query"


def test_cached_record_repoll_three_times_keeps_first_observed_at():
    tracker = o.ObservedAtTracker()
    seen = [observe(tracker, NOW_EPOCH + 60 * i, "cached_record")[0] for i in range(3)]
    assert {x.observed_at for x in seen} == {o.to_iso(NOW_EPOCH)}
    received = [x.received_at for x in seen]
    assert received == sorted(received) and len(set(received)) == 3
    assert all(x.source_kind == "cached_record" for x in seen)


def test_cached_record_ages_while_repolled():
    tracker = o.ObservedAtTracker()
    for i in range(3):
        obs, _ = observe(tracker, NOW_EPOCH + 400 * i, "cached_record")
    assert o.freshness(obs, NOW_EPOCH + 800)["state"] == o.STALE


def test_cached_record_changed_value_or_revision_restarts_observed_at():
    tracker = o.ObservedAtTracker()
    a, _ = observe(tracker, NOW_EPOCH, "cached_record")
    b, _ = observe(tracker, NOW_EPOCH + 10, "cached_record", value=90)
    c, _ = observe(tracker, NOW_EPOCH + 20, "cached_record", revision="r2")
    assert a.observed_at == o.to_iso(NOW_EPOCH)
    assert b.observed_at == o.to_iso(NOW_EPOCH + 10)
    assert c.observed_at == o.to_iso(NOW_EPOCH + 20)


def test_cached_record_keyed_by_subject_and_field():
    tracker = o.ObservedAtTracker()
    observe(tracker, NOW_EPOCH, "cached_record")
    other, _ = observe(tracker, NOW_EPOCH + 5, "cached_record", subject={"kind": "spool", "id": "s2"})
    assert other.observed_at == o.to_iso(NOW_EPOCH + 5)


def test_provider_timestamp_wins_for_both_kinds():
    tracker = o.ObservedAtTracker()
    for kind in ("live_query", "cached_record"):
        obs, diags = observe(tracker, NOW_EPOCH + 100, kind, provider_time=NOW_EPOCH - 50)
        assert obs.observed_at == o.to_iso(NOW_EPOCH - 50)
        assert not any(x.code == "observed_at_is_receipt_time" for x in diags)


def test_live_query_does_not_pollute_cached_memory():
    tracker = o.ObservedAtTracker()
    observe(tracker, NOW_EPOCH, "live_query")
    cached, _ = observe(tracker, NOW_EPOCH + 50, "cached_record")
    assert cached.observed_at == o.to_iso(NOW_EPOCH + 50)


def test_tracker_unknown_kind_is_programming_error_and_bad_ttl_reported():
    tracker = o.ObservedAtTracker()
    with pytest.raises(ValueError):
        observe(tracker, NOW_EPOCH, "magic")
    obs, diags = observe(tracker, NOW_EPOCH, "live_query", ttl_s=0)
    assert any(x.code == "ttl_invalid" for x in diags)
    assert o.freshness(obs, NOW_EPOCH)["state"] == o.UNUSABLE


def test_tracker_memory_is_bounded():
    tracker = o.ObservedAtTracker(max_entries=3)
    for i in range(10):
        observe(tracker, NOW_EPOCH + i, "cached_record", value=i)
    assert len(tracker._first) <= 3


def test_evicted_cached_record_repoll_is_not_renewed():
    tracker = o.ObservedAtTracker(max_entries=2)
    first, _ = observe(tracker, NOW_EPOCH, "cached_record", value=0)
    for i in (1, 2, 3):                                             # value 0 is evicted
        observe(tracker, NOW_EPOCH + i, "cached_record", value=i)
    later = NOW_EPOCH + 100
    again, diags = observe(tracker, later, "cached_record", value=0)
    assert any(x.code == "observed_at_lost_after_eviction" for x in diags)
    assert again.observed_at is None
    assert o.freshness(again, later)["state"] == o.UNKNOWN          # not FRESH
    assert first.observed_at is not None


def test_overflowed_eviction_memory_preserves_old_keys_and_accepts_changed_values():
    tracker = o.ObservedAtTracker(max_entries=1)
    for i in range(8):                                              # exact digest cache (4 x max) overflows into the filter
        observe(tracker, NOW_EPOCH + i, "cached_record", value=i)
    old, old_diags = observe(tracker, NOW_EPOCH + 50, "cached_record", value=0)
    assert old.observed_at is None
    assert any(x.code == "observed_at_lost_after_eviction" for x in old_diags)
    changed, changed_diags = observe(tracker, NOW_EPOCH + 51, "cached_record", value=100)
    assert changed.observed_at == o.to_iso(NOW_EPOCH + 51)
    assert any(x.code == "observed_at_is_receipt_time" for x in changed_diags)
    same, same_diags = observe(tracker, NOW_EPOCH + 52, "cached_record", value=100)
    assert same.observed_at == changed.observed_at
    assert not any(x.code == "observed_at_lost_after_eviction" for x in same_diags)


def test_filter_false_positive_on_a_changed_value_clears_when_generations_rotate():
    tracker = o.ObservedAtTracker(max_entries=2)
    for gen in tracker._gens:                                       # worst case: every bit set, every key collides
        gen[:] = b"\xff" * len(gen)
    collided, diags = observe(tracker, NOW_EPOCH, "cached_record", value="never-seen")
    assert collided.observed_at is None                             # conservative while the collision stands
    assert any(x.code == "observed_at_lost_after_eviction" for x in diags)
    for i in range(2 * tracker._max * 4):                           # two rotations drop both polluted generations
        tracker._remember_evicted(tracker._digest(f"filler-{i}"))
    fresh, fresh_diags = observe(tracker, NOW_EPOCH + 5, "cached_record", value="never-seen")
    assert fresh.observed_at == o.to_iso(NOW_EPOCH + 5)
    assert not any(x.code == "observed_at_lost_after_eviction" for x in fresh_diags)


def test_sustained_churn_still_lets_a_new_changed_value_be_fresh():
    tracker = o.ObservedAtTracker(max_entries=2)
    for i in range(2000):                                           # far past the old, never-rotating saturation
        observe(tracker, NOW_EPOCH + i, "cached_record", value=i)
    new, diags = observe(tracker, NOW_EPOCH + 3000, "cached_record", value="brand-new")
    assert new.observed_at == o.to_iso(NOW_EPOCH + 3000)
    assert o.freshness(new, NOW_EPOCH + 3000)["state"] == o.FRESH
    assert not any(x.code == "observed_at_lost_after_eviction" for x in diags)


def test_unchanged_forgotten_key_stays_unknown_within_retention():
    tracker = o.ObservedAtTracker(max_entries=2)
    observe(tracker, NOW_EPOCH, "cached_record", value="kept")
    for i in range(1, 11):                                          # past the exact cache, into the filter
        observe(tracker, NOW_EPOCH + i, "cached_record", value=f"other-{i}")
    again, diags = observe(tracker, NOW_EPOCH + 100, "cached_record", value="kept")
    assert again.observed_at is None
    assert any(x.code == "observed_at_lost_after_eviction" for x in diags)


def test_tracker_handles_unserialisable_values():
    tracker = o.ObservedAtTracker()
    a, _ = observe(tracker, NOW_EPOCH, "cached_record", value={1, 2})
    b, _ = observe(tracker, NOW_EPOCH + 9, "cached_record", value={1, 2})
    assert a.observed_at == b.observed_at


# -- time helpers ---------------------------------------------------------
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "1", None, 1e30])
def test_to_iso_rejects_bad_epochs(bad):
    with pytest.raises(ValueError):
        o.to_iso(bad)


def test_to_iso_round_trip():
    assert o.to_iso(0) == "1970-01-01T00:00:00Z"
    assert o.parse_time(o.to_iso(1234.5)).timestamp() == pytest.approx(1234.5)


def test_parse_time_never_raises():
    for bad in (None, True, float("nan"), "junk", [], {}, 1e30, object()):
        assert o.parse_time(bad) is None


# -- decoding -------------------------------------------------------------
def good_doc(**over):
    doc = {"schema_version": o.SCHEMA_VERSION, "observation_id": "o1", "subject": {"kind": "lane", "id": "lane:1"},
           "field": "remaining_g", "value": 12, "source": {"provider_instance_id": "p1", "kind": "afc"},
           "source_kind": "cached_record", "observed_at": "2026-01-01T11:59:00Z",
           "received_at": "2026-01-01T11:59:30Z", "ttl_s": 300}
    doc.update(over)
    return doc


def test_round_trip():
    dec = o.Observation.from_dict(good_doc())
    assert dec.valid_for_evaluation
    again = o.Observation.from_dict(dec.value.to_dict())
    assert again.value.to_dict() == dec.value.to_dict()
    assert dec.value.source_kind == "cached_record"
    assert o.freshness(dec.value, NOW)["age_s"] == 60


def test_decode_epoch_times_normalised_to_iso():
    dec = o.Observation.from_dict(good_doc(observed_at=NOW_EPOCH - 5, received_at=NOW_EPOCH))
    assert dec.value.observed_at == o.to_iso(NOW_EPOCH - 5)


@pytest.mark.parametrize("patch,field", [
    ({"ttl_s": 0}, "ttl_s"), ({"ttl_s": -1}, "ttl_s"), ({"ttl_s": True}, "ttl_s"), ({"ttl_s": "5"}, "ttl_s"),
    ({"ttl_s": None}, "ttl_s"),
    ({"subject": {"kind": "planet", "id": "x"}}, "subject.kind"),
    ({"subject": []}, "subject"),
    ({"source": {"provider_instance_id": "", "kind": "afc"}}, "source.provider_instance_id"),
    ({"observed_at": True}, "observed_at"),
    ({"observed_at": ["x"]}, "observed_at"),
    ({"received_at": None}, "received_at"),
    ({"source_kind": "psychic"}, "source_kind"),
])
def test_decode_rejects_bad_documents(patch, field):
    dec = o.Observation.from_dict(good_doc(**patch))
    assert dec.value is None and dec.valid_for_evaluation is False
    assert any(x.field == field for x in dec.diagnostics), dec.diagnostics


def test_decode_missing_value_key_but_null_value_allowed():
    doc = good_doc()
    del doc["value"]
    assert o.Observation.from_dict(doc).value is None
    assert o.Observation.from_dict(good_doc(value=None)).valid_for_evaluation


def test_decode_missing_observed_at_is_unknown_not_invalid():
    doc = good_doc()
    del doc["observed_at"]
    dec = o.Observation.from_dict(doc)
    assert dec.valid_for_evaluation
    assert o.freshness(dec.value, NOW)["state"] == o.UNKNOWN


def test_decode_unreadable_observed_at_kept_and_unusable():
    dec = o.Observation.from_dict(good_doc(observed_at="garbage"))
    assert dec.valid_for_evaluation
    assert o.freshness(dec.value, NOW)["state"] == o.UNUSABLE


def test_decode_unknown_version_opaque():
    dec = o.Observation.from_dict(good_doc(schema_version="observation/2"))
    assert dec.value is None and dec.raw["field"] == "remaining_g"


# -- history uncertainty after the tracker has really lost history -----------
def _churn_past_both_generations(tracker):
    t = NOW_EPOCH
    for i in range(1, 80):                                          # exact cache, then both filter generations
        observe(tracker, t + i, "cached_record", value=f"churn-{i}")
    return t + 80


def test_before_any_loss_a_first_sighting_is_loadout_eligible():
    tracker = o.ObservedAtTracker(max_entries=1)
    obs, diags = observe(tracker, NOW_EPOCH, "cached_record", value="early")
    assert o.freshness(obs, NOW_EPOCH)["usable_for_loadout"] is True
    assert not any(x.code == "observed_at_history_uncertain" for x in diags)


def test_unchanged_record_after_history_loss_is_not_loadout_eligible_until_reobserved():
    tracker = o.ObservedAtTracker(max_entries=1)
    observe(tracker, NOW_EPOCH, "cached_record", value="kept")      # seen before any loss, then forgotten
    t = _churn_past_both_generations(tracker)
    again, diags = observe(tracker, t, "cached_record", value="kept")
    assert again.observed_at == o.to_iso(t)                         # receipt time kept for diagnostics
    assert again.history_uncertain is True
    assert any(x.code == "observed_at_history_uncertain" for x in diags)
    verdict = o.freshness(again, t)
    assert verdict["state"] == o.FRESH and verdict["usable_for_loadout"] is False
    assert again.to_dict()["history_uncertain"] is True
    assert o.Observation.from_dict(good_doc(history_uncertain=True)).value.history_uncertain is True
    assert o.Observation.from_dict(good_doc()).value.history_uncertain is False
    for step in (5, 10, 15):                                        # re-polling is not new evidence: sticky
        again2, diags2 = observe(tracker, t + step, "cached_record", value="kept")
        assert again2.observed_at == o.to_iso(t)
        assert again2.history_uncertain is True
        assert any(x.code == "observed_at_history_uncertain" for x in diags2)
        verdict2 = o.freshness(again2, t + step)
        assert verdict2["usable_for_loadout"] is False
        assert verdict2["reason"] == "History is uncertain; no new source evidence yet."
    stamped, _ = observe(tracker, t + 20, "cached_record", value="kept", provider_time=t + 19)
    assert stamped.history_uncertain is False
    assert o.freshness(stamped, t + 20)["usable_for_loadout"] is True


def test_provider_time_record_stays_eligible_after_history_loss():
    tracker = o.ObservedAtTracker(max_entries=1)
    t = _churn_past_both_generations(tracker)
    obs, diags = observe(tracker, t, "cached_record", value="stamped", provider_time=t - 10)
    assert obs.history_uncertain is False
    assert not any(x.code == "observed_at_history_uncertain" for x in diags)
    assert o.freshness(obs, t)["usable_for_loadout"] is True


def test_changed_value_after_history_loss_is_fresh_to_display_but_not_loadout_eligible():
    tracker = o.ObservedAtTracker(max_entries=1)
    t = _churn_past_both_generations(tracker)
    changed, _ = observe(tracker, t, "cached_record", value="brand-new")
    verdict = o.freshness(changed, t)
    assert verdict["state"] == o.FRESH and verdict["usable_for_loadout"] is False
    assert o.as_historical(changed).history_uncertain is True
