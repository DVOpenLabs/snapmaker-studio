"""Trying to make Studio believe the wrong thing about what is on the spools.

Two sources can describe the same slot: the printer, which is looking at it, and
an optional tracker like Spoolman, which knows things the printer cannot — a spool
identity, and how much is left on it. That second source is where the strongest
sentence Studio says comes from: *87 g needed, 43 g left, it will run out.*

A sentence that strong has to be built out of something better than a number in a
database. These tests are the ways that number can be wrong — missing, negative,
in the wrong units, from the wrong slot, describing a spool that has since been
swapped — and what Studio is allowed to say in each case.

The rules being defended:

* the printer is authoritative about what is physically loaded;
* a provider may add what the printer cannot know, and never overrides it;
* a disagreement is reported as a disagreement, not silently resolved;
* nothing is ever invented, and a figure that cannot be true is not a figure.
"""
from __future__ import annotations

import socket
import urllib.error

import pytest

from snapstudio_core import material_plan, material_providers as providers, send_check


def _hours_ago(hours: float) -> str:
    import datetime

    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=hours)).isoformat()

#: A spool something has actually been printing from. Both fields matter: a real
#: Spoolman always computes a `remaining_weight`, so it is `used_weight` together
#: with `last_used` that distinguishes bookkeeping somebody is keeping from a
#: figure that is simply the spool's declared size.
SPOOL = {
    "id": 7, "remaining_weight": 431.5, "archived": False,
    "last_used": "2026-08-20T10:00:00Z", "used_weight": 568.5,
    "filament": {"material": "PLA Silk", "color_hex": "2D9E59", "name": "Green",
                 "weight": 1000, "vendor": {"name": "Snapmaker"}},
}


def spoolman_returning(monkeypatch, payload):
    monkeypatch.setattr(providers, "_get_json", lambda url, timeout=4.0: payload)


def printer_state(**slot):
    return {"schema_version": providers.SCHEMA_VERSION, "source": providers.STOCK,
            "available": True, "remaining_known": False,
            "slots": [providers._slot(0, **slot)]}


def tracker_state(**slot):
    slot.setdefault("source", providers.SPOOLMAN)
    return {"schema_version": providers.SCHEMA_VERSION, "source": providers.SPOOLMAN,
            "available": True, "remaining_known": True,
            "slots": [providers._slot(0, **slot)]}


# --- two sources that disagree -------------------------------------------------

def test_a_material_disagreement_is_reported_not_resolved_silently():
    """The printer says PLA is in slot 1 and the tracker says PETG. One of them is
    about to be wrong about what comes out of the nozzle, and the user is the only
    one who can look."""
    combined = providers.combine(printer_state(material="PLA"),
                                 tracker_state(material="PETG", spool_id=7, remaining_g=400))
    slot = combined["slots"][0]
    assert slot["material"] == "PLA"                     # the machine is looking at it
    assert slot["confidence"] == providers.UNKNOWN
    assert any("PETG" in note for note in slot["conflicts"])
    assert slot["disagreed"]["material"]["spoolman"] == "PETG"


def test_a_colour_disagreement_is_reported_too():
    combined = providers.combine(printer_state(material="PLA", color="#000000"),
                                 tracker_state(material="PLA", color="#FFFFFF", spool_id=7))
    slot = combined["slots"][0]
    assert slot["color"] == "#000000"
    assert slot["disagreed"]["colour"]["spoolman"] == "#FFFFFF"


def test_a_tracker_that_thinks_a_printer_confirmed_empty_slot_is_loaded_does_not_fill_it():
    """H1 fix (Opus review of 7848824): the printer here has LOOKED and
    confirmed the slot empty (confirmed_by=BY_PRINTER) — a tracker's claim
    that a spool is loaded must never flip that back to present, only be
    recorded as a disagreement. Fixed after this test's own fixture was
    caught not actually setting confirmed_by, so it silently exercised the
    old, overridable path and passed for the wrong reason."""
    combined = providers.combine(printer_state(present=False, confirmed_by=providers.BY_PRINTER),
                                 tracker_state(material="PLA", spool_id=7, remaining_g=400))
    slot = combined["slots"][0]
    assert slot["present"] is False
    assert slot["conflicts"]


def test_a_tracker_with_no_record_of_a_loaded_spool_changes_nothing():
    combined = providers.combine(printer_state(material="PLA", color="#000000"),
                                 {"source": providers.SPOOLMAN, "available": True, "slots": []})
    slot = combined["slots"][0]
    assert slot["material"] == "PLA"
    assert not slot.get("conflicts")


def test_the_printer_alone_is_a_complete_answer():
    """Every provider is optional. A stock U1 with nothing else installed is not a
    degraded setup."""
    combined = providers.combine(printer_state(material="PLA", color="#000000"))
    assert combined["available"] is True
    assert combined["remaining_known"] is False


# --- a provider that is not there or not well ----------------------------------

def test_a_provider_that_is_unreachable_is_reported_not_fatal(monkeypatch):
    def refuse(url, timeout=4.0):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(providers, "_get_json", refuse)
    state = providers.spoolman("http://spoolman.local:7912")
    assert state["available"] is False
    assert "did not answer" in state["error"]


def test_a_provider_that_times_out_is_reported_not_fatal(monkeypatch):
    def stall(url, timeout=4.0):
        raise socket.timeout("timed out")
    monkeypatch.setattr(providers, "_get_json", stall)
    state = providers.spoolman("http://spoolman.local:7912")
    assert state["available"] is False
    assert state["error"]


def test_a_provider_that_answers_with_nonsense_is_refused(monkeypatch):
    spoolman_returning(monkeypatch, {"unexpected": "shape"})
    assert providers.spoolman("http://spoolman.local:7912")["available"] is False


def test_an_entry_that_is_not_a_spool_is_skipped(monkeypatch):
    spoolman_returning(monkeypatch, [SPOOL, "not a spool", None])
    state = providers.spoolman("http://spoolman.local:7912")
    assert len(state["spools"]) == 1


# --- weights that cannot be true ------------------------------------------------

@pytest.mark.parametrize("weight", [-12.0, -0.1])
def test_a_negative_remaining_weight_is_not_a_weight(monkeypatch, weight):
    spoolman_returning(monkeypatch, [dict(SPOOL, remaining_weight=weight)])
    spool = providers.spoolman("http://spoolman.local:7912")["spools"][0]
    assert spool["remaining_g"] is None
    assert any("negative" in note for note in spool["notes"])


def test_an_impossible_remaining_weight_is_not_a_weight(monkeypatch):
    spoolman_returning(monkeypatch, [dict(SPOOL, remaining_weight=99_000)])
    spool = providers.spoolman("http://spoolman.local:7912")["spools"][0]
    assert spool["remaining_g"] is None
    assert any("units" in note for note in spool["notes"])


def test_more_left_than_the_spool_holds_is_not_a_weight(monkeypatch):
    """The one units mistake that can be caught: a spool that holds 1 kg cannot
    have 4 kg left on it."""
    spoolman_returning(monkeypatch, [dict(SPOOL, remaining_weight=4000)])
    spool = providers.spoolman("http://spoolman.local:7912")["spools"][0]
    assert spool["remaining_g"] is None
    assert any("more left" in note for note in spool["notes"])


def test_an_empty_spool_is_zero_not_unknown(monkeypatch):
    spoolman_returning(monkeypatch, [dict(SPOOL, remaining_weight=0)])
    spool = providers.spoolman("http://spoolman.local:7912")["spools"][0]
    assert spool["remaining_g"] == 0.0
    assert spool["remaining_quality"] == providers.TRACKED


def test_a_weight_written_as_text_is_still_read(monkeypatch):
    spoolman_returning(monkeypatch, [dict(SPOOL, remaining_weight="431.5")])
    assert providers.spoolman("http://s")["spools"][0]["remaining_g"] == 431.5


def test_a_spool_with_an_identity_but_no_quantity_is_still_useful(monkeypatch):
    payload = [{"id": 7, "filament": {"material": "PLA", "color_hex": "2D9E59"}}]
    spoolman_returning(monkeypatch, payload)
    state = providers.spoolman("http://s", slot_map={"0": 7})
    slot = state["slots"][0]
    assert slot["material"] == "PLA"
    assert slot["remaining_g"] is None
    assert slot["remaining_quality"] == providers.UNTRACKED
    assert state["remaining_known"] is False


def test_a_remaining_weight_worked_out_from_what_was_used_says_so(monkeypatch):
    payload = [{"id": 7, "used_weight": 250,
                "filament": {"material": "PLA", "weight": 1000, "color_hex": "2D9E59"}}]
    spoolman_returning(monkeypatch, payload)
    spool = providers.spoolman("http://s")["spools"][0]
    assert spool["remaining_g"] == 750.0
    assert spool["remaining_quality"] == providers.DERIVED


def test_a_malformed_colour_is_no_colour_rather_than_a_wrong_one(monkeypatch):
    spoolman_returning(monkeypatch, [dict(SPOOL, filament=dict(SPOOL["filament"],
                                                               color_hex="not-a-colour"))])
    assert providers.spoolman("http://s")["spools"][0]["color"] is None


# --- which slot is which --------------------------------------------------------

def test_a_slot_map_that_cannot_be_zero_based_is_read_as_one_based(monkeypatch):
    """A person looking at a U1 counts slots 1-4; the G-code counts them 0-3.
    Reading a 1-4 map as though it were 0-3 would describe every slot as the one
    next to it, with complete confidence."""
    spoolman_returning(monkeypatch, [dict(SPOOL, id=n) for n in (1, 2, 3, 4)])
    state = providers.spoolman("http://s", slot_map={"1": 1, "2": 2, "3": 3, "4": 4})
    assert state["slot_base"] == 1
    assert [s["slot"] for s in state["slots"]] == [0, 1, 2, 3]


def test_a_zero_based_slot_map_is_left_alone(monkeypatch):
    spoolman_returning(monkeypatch, [dict(SPOOL, id=n) for n in (1, 2, 3, 4)])
    state = providers.spoolman("http://s", slot_map={"0": 1, "1": 2, "2": 3, "3": 4})
    assert state["slot_base"] == 0
    assert [s["slot"] for s in state["slots"]] == [0, 1, 2, 3]


def test_the_caller_can_say_which_way_it_numbered_the_slots(monkeypatch):
    spoolman_returning(monkeypatch, [SPOOL])
    state = providers.spoolman("http://s", slot_map={"1": 7}, slot_base=1)
    assert state["slots"][0]["slot"] == 0


def test_a_slot_map_pointing_at_a_spool_that_is_gone_says_so(monkeypatch):
    spoolman_returning(monkeypatch, [SPOOL])
    state = providers.spoolman("http://s", slot_map={"0": 999})
    slot = state["slots"][0]
    assert slot["present"] is False
    assert any("999" in note for note in slot["notes"])


def test_an_archived_spool_is_flagged(monkeypatch):
    spoolman_returning(monkeypatch, [dict(SPOOL, archived=True)])
    state = providers.spoolman("http://s", slot_map={"0": 7})
    assert any("archived" in note for note in state["slots"][0]["notes"])


def test_a_nonsense_slot_key_is_ignored_not_guessed(monkeypatch):
    spoolman_returning(monkeypatch, [SPOOL])
    state = providers.spoolman("http://s", slot_map={"left one": 7, "-2": 7})
    assert state["slots"] == []


# --- what Studio is then allowed to say -----------------------------------------

def job_needing(grams, *, loaded_grams=None, quality=providers.TRACKED, as_of=None):
    facts = {"available": True,
             "slots": [{"tool": 0, "used": True, "grams": grams, "type": "PLA",
                        "color": "#2D9E59"}],
             "tools_used": [0]}
    loaded = [{"material": "PLA", "color": "#2D9E59", "remaining_g": loaded_grams,
               "remaining_quality": quality, "remaining_as_of": as_of}]
    return facts, {"reachable": True, "loaded_filaments": loaded}


def test_a_tracked_shortfall_blocks_the_send():
    """The strongest sentence Studio says, and what it takes to earn it."""
    facts, printer = job_needing(87.0, loaded_grams=43.0, as_of=_hours_ago(2))
    result = send_check.evaluate(facts, printer)
    blockers = [i for i in result["items"] if i["kind"] == send_check.BLOCKER]
    assert any("Not enough filament" in i["title"] for i in blockers)


def test_a_shortfall_on_an_unlabelled_figure_only_warns():
    """The same numbers, from a source that will not say where they came from."""
    facts, printer = job_needing(87.0, loaded_grams=43.0, quality="unknown")
    result = send_check.evaluate(facts, printer)
    assert not [i for i in result["items"] if i["kind"] == send_check.BLOCKER]
    assert any("may not have enough" in i["title"] for i in result["items"])


def test_a_shortfall_within_the_drift_of_the_tracking_only_warns():
    """Two grams short on a bookkeeping figure is not a fact about a print."""
    facts, printer = job_needing(87.0, loaded_grams=85.0, as_of=_hours_ago(2))
    result = send_check.evaluate(facts, printer)
    assert not [i for i in result["items"] if i["kind"] == send_check.BLOCKER]


def test_nothing_tracking_the_spool_is_unknown_not_enough():
    facts, printer = job_needing(87.0, loaded_grams=None)
    plan = material_plan.from_facts(facts, printer)
    assert plan["slots"][0]["sufficiency"]["verdict"] == "unknown"
    assert plan["slots"][0]["state"] == "ready"          # nothing wrong is known
    result = send_check.evaluate(facts, printer)
    assert not [i for i in result["items"] if i["kind"] == send_check.BLOCKER]


def test_a_derived_weight_warns_rather_than_blocks_and_says_it_is_derived():
    """A derived weight is arithmetic, not a record of consumption.

    This used to block a send. Spoolman always answers with a remaining weight,
    computing it from the spool's declared size minus what has been recorded
    used — so a spool registered five minutes ago and never printed from reports
    a full kilogram, and a spool whose usage nothing has updated reports whatever
    it reported last time. Refusing to send on that is stopping someone over
    bookkeeping rather than over filament.
    """
    facts, printer = job_needing(87.0, loaded_grams=12.0, quality=providers.DERIVED,
                                 as_of=_hours_ago(1))
    plan = material_plan.from_facts(facts, printer)
    sufficiency = plan["slots"][0]["sufficiency"]
    assert sufficiency["verdict"] == "probably_short"
    assert sufficiency["trusted"] is False
    assert "worked out" in sufficiency["source"]

    result = send_check.evaluate(facts, printer)
    assert not [i for i in result["items"] if i["kind"] == send_check.BLOCKER]


def test_a_tracked_but_stale_weight_warns_rather_than_blocks():
    """Bookkeeping nobody has touched in a fortnight is not grounds for a refusal."""
    facts, printer = job_needing(87.0, loaded_grams=43.0, as_of=_hours_ago(24 * 14))
    plan = material_plan.from_facts(facts, printer)
    sufficiency = plan["slots"][0]["sufficiency"]
    assert sufficiency["verdict"] == "probably_short"
    assert sufficiency["freshness"] == "stale"
    assert not [i for i in send_check.evaluate(facts, printer)["items"]
                if i["kind"] == send_check.BLOCKER]


def test_an_undated_weight_never_blocks_however_it_is_labelled():
    """Without a date there is no way to know the figure is still true."""
    facts, printer = job_needing(87.0, loaded_grams=43.0, as_of=None)
    sufficiency = material_plan.from_facts(facts, printer)["slots"][0]["sufficiency"]
    assert sufficiency["verdict"] == "probably_short"
    assert sufficiency["freshness"] == "unknown"


def test_a_job_that_does_not_state_its_weight_is_never_short():
    facts, printer = job_needing(None, loaded_grams=43.0)
    plan = material_plan.from_facts(facts, printer)
    assert plan["slots"][0]["sufficiency"]["verdict"] == "unknown"
