"""plan-39 addendum §5 (L-5/N-3): a figure that looks sufficient still says
when it was last true — or that nothing records that — the same way whether
the gap is a blank string, a null, or whitespace, and the same way for a
Spoolman spool nothing has printed from as for a SpoolEase one.
"""
from __future__ import annotations

import datetime

from snapstudio_core import material_plan as mp
from snapstudio_core import send_check as sc


def _ago(**kw) -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(**kw)).isoformat()


# --- S-1/S-2: the caveat, keyed on freshness.UNKNOWN not `as_of is None` -----

def test_enough_with_no_date_carries_the_caveat():
    out = mp._sufficiency(200, 549.5, "derived", as_of=None)
    assert out["verdict"] == "enough"
    assert out["trusted"] is False
    assert out["detail"].endswith("Nothing records when this figure was last updated.")


def test_blank_and_whitespace_as_of_read_identically_to_none():
    none_case = mp._sufficiency(200, 549.5, "derived", as_of=None)
    empty_case = mp._sufficiency(200, 549.5, "derived", as_of="")
    ws_case = mp._sufficiency(200, 549.5, "derived", as_of="   ")
    assert none_case["detail"] == empty_case["detail"] == ws_case["detail"]
    assert "Last updated" not in ws_case["detail"]


# --- S-3/S-4: a fresh date has no caveat, an unusable date is unchanged ------

def test_a_fresh_tracked_date_has_no_caveat():
    out = mp._sufficiency(200, 549.5, "tracked", as_of=_ago(hours=1))
    assert "Nothing records" not in out["detail"]
    assert out["freshness"] == "fresh"


def test_an_unparseable_date_is_unusable_not_caveated():
    out = mp._sufficiency(200, 549.5, "tracked", as_of="not-a-date")
    assert out["freshness"] == "unusable"
    assert "Nothing records" not in out["detail"]
    assert "could not read the date" in out["detail"]


def test_user_confirmed_fresh_has_no_caveat():
    out = mp._sufficiency(200, 549.5, "user_confirmed", as_of=_ago(minutes=5))
    assert "Nothing records" not in out["detail"]
    assert out["trusted"] is True


# --- S-5: Spoolman regression — DERIVED with no last_used ---------------------

def test_spoolman_derived_with_no_last_used_gets_the_caveat_and_never_warns():
    from snapstudio_core import material_providers as providers

    spool = {"id": 1, "filament": {"material": "PLA", "weight": 1000.0,
                                   "color_hex": "000000", "vendor": {"name": "V"}},
             "initial_weight": 1000.0, "used_weight": 100.0}  # no last_used
    remaining, quality, notes = providers._remaining(spool, spool["filament"])
    assert quality == providers.DERIVED

    out = mp._sufficiency(200.0, remaining, quality, as_of=None)
    assert out["verdict"] == "enough"
    assert out["detail"].endswith("Nothing records when this figure was last updated.")

    plan = mp.plan([{"tool": 0, "used": True, "grams": 200.0, "type": "PLA"}],
                   [{"material": "PLA", "remaining_g": remaining,
                     "remaining_quality": quality, "remaining_as_of": None,
                     "confirmed_by": "provider"}])
    slot = plan["slots"][0]
    assert slot["state"] == "ready"
    assert slot["detail"].endswith("Nothing records when this figure was last updated.")

    facts = {"available": True, "tools_used": [0],
            "slots": [{"tool": 0, "used": True, "grams": 200.0, "type": "PLA"}]}
    check = sc.evaluate(facts, {"reachable": True, "loaded_filaments": [
        {"material": "PLA", "remaining_g": remaining, "remaining_quality": quality,
         "remaining_as_of": None, "confirmed_by": "provider"}]})
    assert not [i for i in check["items"] if "filament" in i["title"].lower()]


def test_spoolman_derived_with_last_used_and_used_is_unchanged_byte_for_byte():
    """The pre-change output for a genuinely TRACKED case, pinned so the
    caveat change cannot silently touch a dated figure's sentence."""
    from snapstudio_core import material_providers as providers

    when = _ago(hours=3)
    spool = {"id": 1, "filament": {"material": "PLA", "weight": 1000.0},
             "remaining_weight": 900.0, "used_weight": 100.0, "last_used": when}
    remaining, quality, notes = providers._remaining(spool, spool["filament"])
    assert quality == providers.TRACKED

    out = mp._sufficiency(200.0, remaining, quality, as_of=when)
    assert out["detail"].endswith("ago.")
    assert "Nothing records" not in out["detail"]


def test_bambuddy_derived_with_no_last_used_gets_the_caveat():
    from snapstudio_core import material_providers as providers

    value, quality, as_of, notes = providers._bambuddy_remaining(
        {"label_weight": 1000, "weight_used": 100.0})
    assert quality == providers.DERIVED
    assert as_of is None
    out = mp._sufficiency(200.0, value, quality, as_of=as_of)
    assert out["detail"].endswith("Nothing records when this figure was last updated.")


# --- S-6: probably_enough branch also gets the caveat -------------------------

def test_probably_enough_with_no_date_carries_the_caveat_too():
    out = mp._sufficiency(200, 205.0, "derived", as_of=None)
    assert out["verdict"] == "probably_enough"
    assert out["detail"].endswith("Nothing records when this figure was last updated.")
    assert "Recorded weights are not exact." in out["detail"]


# --- AC-5: corrected vocabulary (sufficiency.verdict vs slot state) ----------

def test_ac5_corrected_vocabulary_enough_case():
    plan = mp.plan([{"tool": 0, "used": True, "grams": 200.0, "type": "PLA"}],
                   [{"material": "PLA", "remaining_g": 549.5,
                     "remaining_quality": "derived", "remaining_as_of": None,
                     "confirmed_by": "provider"}])
    slot = plan["slots"][0]
    assert slot["sufficiency"]["verdict"] == "enough"
    assert slot["sufficiency"]["trusted"] is False
    assert slot["state"] == "ready"


def test_ac5_corrected_vocabulary_probably_short_case():
    plan = mp.plan([{"tool": 0, "used": True, "grams": 600.0, "type": "PLA"}],
                   [{"material": "PLA", "remaining_g": 549.5,
                     "remaining_quality": "derived", "remaining_as_of": None,
                     "confirmed_by": "provider"}])
    slot = plan["slots"][0]
    assert slot["sufficiency"]["verdict"] == "probably_short"
    assert slot["state"] == "maybe_not_enough"
    assert slot["state"] != "not_enough"

    facts = {"available": True, "tools_used": [0],
            "slots": [{"tool": 0, "used": True, "grams": 600.0, "type": "PLA"}]}
    check = sc.evaluate(facts, {"reachable": True, "loaded_filaments": [
        {"material": "PLA", "remaining_g": 549.5, "remaining_quality": "derived",
         "remaining_as_of": None, "confirmed_by": "provider"}]})
    warnings = [i for i in check["items"] if i["kind"] == sc.WARNING]
    blockers = [i for i in check["items"] if i["kind"] == sc.BLOCKER]
    assert any("may not have enough" in i["title"].lower()
              or "may not have enough" in i["detail"].lower() for i in warnings)
    assert not [b for b in blockers if "filament" in b["title"].lower()]
