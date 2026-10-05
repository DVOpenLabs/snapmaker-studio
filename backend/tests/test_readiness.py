"""Ready Now classifier: every bucket, the precedence between them, and the honesty
rules (colour-only mismatch, unchecked weight, nothing claimed without evidence).
"""
from __future__ import annotations

import copy
import datetime

import pytest

from snapstudio_core import material_plan as mp
from snapstudio_core import preflight as pf
from snapstudio_core import readiness as rd

NOW = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
PROJECT = {"path": "C:/models/thing.3mf", "name": "thing.3mf"}


def _tier(value, confidence="confirmed"):
    return {"value": value, "confidence": confidence, "evidence": "test"}


def traits(slots=(("PLA", "#FF0000"),), *, foreign=False, sliced=False, grams=None,
           readable=True, nozzle="0.4"):
    """Graded traits as project_traits.extract would return them. ``grams`` maps tool -> g
    and is carried the way a slicer prediction is (filament ids count from 1)."""
    slot_list = [{"tool": i, "type": t, "color": c, "name": None}
                 for i, (t, c) in enumerate(slots)]
    out = {
        "readable": readable,
        "foreign_printer": _tier(foreign),
        "is_u1_project": _tier(not foreign),
        "target_printer": _tier("Bambu Lab X1C" if foreign else "Snapmaker U1"),
        "is_sliced": _tier(sliced),
        "filament_count": _tier(len(slot_list)),
        "filament_slots": _tier(slot_list),
        "nozzle_diameters": _tier([nozzle]),
        "nozzle_diameters_by_toolhead": _tier([nozzle] * 4),
        "expects_object_exclusion": _tier(False),
        "plate_predictions": [],
    }
    if grams is not None:
        out["plate_predictions"] = [{"filaments": [
            {"id": str(tool + 1), "type": "PLA", "color": "#000000", "used_g": g}
            for tool, g in grams.items()]}]
    return out


def spool(material="PLA", color="#FF0000", remaining=None, quality="untracked",
          confirmed_by="printer", as_of=None):
    return {"material": material, "color": color, "remaining_g": remaining,
            "remaining_quality": quality, "remaining_as_of": as_of,
            "confirmed_by": confirmed_by}


def printer(loaded=None, *, reachable=True, state="standby"):
    if not reachable:
        return {"reachable": False, "error": "no answer"}
    return {"reachable": True, "host": "printer.invalid", "port": 7125, "toolhead_count": 4,
            "bed_mm": {"x": 270, "y": 270, "z": 270}, "nozzle_diameters": [0.4] * 4,
            "nozzle_confirmed_by": "printer", "print_state": state, "klipper_objects": [],
            "loaded_filaments": loaded}


def classify(t, p, *, placement=None, file_state="ok", run_preflight=True):
    placement = placement or {"available": True, "off_plate": []}
    pre = pf.evaluate(t, p, placement) if (run_preflight and p.get("reachable")) else None
    return rd.classify_project(PROJECT, t, p, pre, file_state)


# --- every bucket ---------------------------------------------------------------

def test_ready_now_when_everything_matches_and_amount_is_checked():
    t = traits(grams={0: 20.0})
    r = classify(t, printer([spool(remaining=100.0, quality="tracked",
                                   as_of=NOW)]))
    assert r["bucket"] == rd.READY_NOW
    assert r["amount_checked"] is True
    assert r["colour_notes"] == []
    assert r["file_state"] == "ok"
    assert r["slots"][0]["state"] in ("ready", "maybe_not_enough")


def test_every_bucket_and_required_fields():
    cases = {
        rd.NEEDS_PREPARATION: classify(traits(foreign=True), printer([spool()])),
        rd.NEEDS_ATTENTION: classify(traits(), printer([spool()], state="printing")),
        rd.CANT_DETERMINE: classify(traits(), printer(reachable=False)),
        rd.ONE_CHANGE_AWAY: classify(traits(), printer([spool("PETG")])),
        rd.READY_NOW: classify(traits(), printer([spool()])),
    }
    for bucket, r in cases.items():
        assert r["bucket"] == bucket
        assert set(r) == {"path", "name", "bucket", "top_reason", "top_action", "confidence",
                          "evidence", "unknowns", "colour_notes", "amount_checked", "slots",
                          "file_state"}
        assert r["confidence"] in ("confirmed", "likely", "informational", "unknown")
        assert r["top_reason"]


def test_foreign_project_is_needs_preparation_with_no_printer_at_all():
    r = classify(traits(foreign=True), printer(reachable=False))
    assert r["bucket"] == rd.NEEDS_PREPARATION
    assert r["top_action"] == "Prepare a U1 copy first"


def test_foreign_beats_a_busy_printer():
    r = classify(traits(foreign=True), printer([spool()], state="printing"))
    assert r["bucket"] == rd.NEEDS_PREPARATION


# --- precedence -----------------------------------------------------------------

def test_bucket_order_is_the_documented_precedence():
    assert rd.BUCKETS == ("needs_preparation", "needs_attention", "cant_determine",
                          "one_change_away", "ready_now")


def test_attention_beats_one_change_away():
    r = classify(traits(), printer([spool("PETG")], state="printing"))
    assert r["bucket"] == rd.NEEDS_ATTENTION


def test_attention_beats_cant_determine_for_unknown_weight():
    t = traits(grams={0: 20.0})
    r = classify(t, printer([spool(remaining=None)], state="paused"))
    assert r["bucket"] == rd.NEEDS_ATTENTION


def test_cant_determine_beats_one_change_away():
    # slot 1 is a wrong material (a change), slot 2 states no material (unknown)
    t = traits(slots=(("PLA", "#FF0000"), (None, "#00FF00")))
    r = classify(t, printer([spool("PETG"), spool("PETG")]))
    assert r["bucket"] == rd.CANT_DETERMINE


def test_one_change_away_beats_ready_now():
    t = traits(slots=(("PLA", "#FF0000"), ("PETG", "#00FF00")))
    r = classify(t, printer([spool("PLA"), None]))
    assert r["bucket"] == rd.ONE_CHANGE_AWAY


# --- colour-only exception --------------------------------------------------------

def test_colour_only_mismatch_stays_ready_with_a_prominent_note():
    r = classify(traits(), printer([spool("PLA", "#0000FF")]))
    assert r["bucket"] == rd.READY_NOW
    assert r["top_reason"] == "Prints now, but the loaded colour differs from the project."
    assert len(r["colour_notes"]) == 1
    assert r["slots"][0]["state"] == "different_colour"
    assert r["confidence"] != "confirmed"          # never calls the colour correct


def test_colour_within_noticeable_distance_is_no_note():
    r = classify(traits(), printer([spool("PLA", "#F80000")]))
    assert mp.colour_distance("#FF0000", "#F80000") < mp.NOTICEABLE
    assert r["colour_notes"] == []


def test_wrong_material_family_is_one_change_away_even_when_colour_matches():
    r = classify(traits(), printer([spool("PETG", "#FF0000")]))
    assert r["bucket"] == rd.ONE_CHANGE_AWAY
    assert "PLA" in r["top_action"]


def test_empty_printer_is_one_change_away():
    r = classify(traits(), printer([None, None, None, None]))
    assert r["bucket"] == rd.ONE_CHANGE_AWAY
    assert r["slots"][0]["state"] == "empty"


def test_material_subtype_matches_by_family():
    r = classify(traits(slots=(("PLA", "#FF0000"),)), printer([spool("PLA Matte")]))
    assert r["bucket"] == rd.READY_NOW


# --- unknown weight, both ways ------------------------------------------------------

def test_grams_known_remaining_unknown_is_cant_determine():
    r = classify(traits(grams={0: 20.0}), printer([spool(remaining=None)]))
    assert r["bucket"] == rd.CANT_DETERMINE
    assert r["amount_checked"] is False
    assert r["slots"][0]["amount"] == "unknown_remaining"


def test_no_reliable_grams_is_ready_but_says_amount_not_checked():
    r = classify(traits(), printer([spool(remaining=500.0, quality="tracked")]))
    assert r["bucket"] == rd.READY_NOW
    assert r["amount_checked"] is False
    assert rd.AMOUNT_NOT_CHECKED in r["evidence"]
    assert r["confidence"] != "confirmed"


def test_trusted_insufficient_weight_needs_attention():
    t = traits(grams={0: 200.0})
    r = classify(t, printer([spool(remaining=20.0, quality="tracked",
                                   as_of=NOW)]))
    assert r["bucket"] == rd.NEEDS_ATTENTION
    assert r["slots"][0]["state"] == "not_enough"


def test_untracked_remaining_weight_is_not_a_checked_amount():
    t = traits(grams={0: 20.0})
    r = classify(t, printer([spool(remaining=500.0, quality="unknown")]))
    assert r["bucket"] == rd.READY_NOW
    assert r["amount_checked"] is False
    assert rd.AMOUNT_UNTRUSTED in r["evidence"]
    assert r["confidence"] == "likely"


def test_stale_tracked_weight_is_not_a_checked_amount():
    t = traits(grams={0: 20.0})
    r = classify(t, printer([spool(remaining=500.0, quality="tracked",
                                   as_of="2020-01-01T00:00:00Z")]))
    assert r["amount_checked"] is False
    assert rd.AMOUNT_UNTRUSTED in r["evidence"]


def test_user_confirmed_fresh_weight_is_a_checked_amount():
    t = traits(grams={0: 20.0})
    r = classify(t, printer([spool(remaining=500.0, quality="user_confirmed", as_of=NOW)]))
    assert r["amount_checked"] is True


def test_exclude_object_is_a_note_never_attention():
    t = traits()
    t["expects_object_exclusion"] = _tier(True)
    p = printer([spool()])
    p["klipper_objects"] = ["extruder"]
    pre = pf.evaluate(t, p, {"available": True, "off_plate": []})
    assert any(c["id"] == "capability.exclude_object" and c["result"] == pf.ATTENTION
               for c in pre["checks"])
    r = rd.classify_project(PROJECT, t, p, pre)
    assert r["bucket"] == rd.READY_NOW
    assert any("object" in u.lower() for u in r["unknowns"])
    assert r["confidence"] == "likely"


def test_untrusted_short_weight_is_a_caution_not_a_block():
    t = traits(grams={0: 200.0})
    r = classify(t, printer([spool(remaining=20.0, quality="unknown")]))
    assert r["bucket"] == rd.READY_NOW
    assert r["unknowns"] and r["confidence"] == "likely"


def test_heaviest_plate_is_the_requirement():
    t = traits(grams={0: 20.0})
    t["plate_predictions"].append({"filaments": [{"id": "1", "used_g": 90.0}]})
    assert rd.required_slots(t)[0]["grams"] == 90.0


def test_slot_no_plate_uses_is_not_asked_for():
    t = traits(slots=(("PLA", "#FF0000"), ("PETG", "#00FF00")), grams={0: 10.0})
    slots = rd.required_slots(t)
    assert [s["used"] for s in slots] == [True, False]
    r = classify(t, printer([spool(remaining=100.0, quality="tracked",
                                   as_of=NOW)]))
    assert r["bucket"] == rd.READY_NOW
    assert r["slots"][1]["state"] == "unused"


# --- printer and file states --------------------------------------------------------

def test_busy_printer_needs_attention():
    for state in ("printing", "paused"):
        r = classify(traits(), printer([spool()], state=state))
        assert r["bucket"] == rd.NEEDS_ATTENTION
        assert "busy" in r["top_reason"].lower()


def test_bed_overflow_needs_attention():
    r = classify(traits(), printer([spool()]),
                 placement={"available": True, "off_plate": [{"name": "x"}]})
    assert r["bucket"] == rd.NEEDS_ATTENTION


def test_unreachable_printer_is_cant_determine_never_ready():
    r = classify(traits(), printer(reachable=False))
    assert r["bucket"] == rd.CANT_DETERMINE
    assert r["confidence"] == "unknown"


def test_printer_that_reports_nothing_loaded_is_cant_determine():
    r = classify(traits(), printer(None))
    assert r["bucket"] == rd.CANT_DETERMINE


@pytest.mark.parametrize("state", ["missing", "unreadable"])
def test_missing_or_unreadable_file_is_cant_determine(state):
    r = rd.classify_project(PROJECT, None, printer([spool()]), None, state)
    assert r["bucket"] == rd.CANT_DETERMINE
    assert r["file_state"] == state


def test_no_stated_materials_is_cant_determine():
    r = classify(traits(slots=()), printer([spool()]))
    assert r["bucket"] == rd.CANT_DETERMINE


def test_no_evidence_no_claim_when_preflight_was_not_run():
    r = rd.classify_project(PROJECT, traits(), printer([spool()]), None, "ok")
    assert r["bucket"] == rd.CANT_DETERMINE


def test_provider_assumed_spool_is_ready_but_not_confirmed():
    r = classify(traits(), printer([spool(confirmed_by="provider")]))
    assert r["bucket"] == rd.READY_NOW
    assert r["confidence"] == "likely"


# --- set-wise matching -----------------------------------------------------------------

def test_setwise_ignores_slot_order():
    t = traits(slots=(("PLA", "#FF0000"), ("PETG", "#00FF00")))
    loaded = [spool("PETG", "#00FF00"), spool("PLA", "#FF0000")]   # reversed vs the project
    r = classify(t, printer(loaded))
    assert r["bucket"] == rd.READY_NOW
    assert [s["printer_slot"] for s in r["slots"]] == [1, 0]
    assert r["colour_notes"] == []


def test_setwise_two_slots_one_spool_leaves_one_empty():
    t = traits(slots=(("PLA", "#FF0000"), ("PLA", "#FF0000")))
    entries = rd.match_slots_setwise(rd.required_slots(t), [spool()])
    assert sorted(e["state"] for e in entries) == ["empty", "ready"]


def test_setwise_tightest_constraint_goes_first():
    # the lone PETG spool is the only fit for slot 2; slot 1 (PLA) must not need it
    t = traits(slots=(("PLA", "#FF0000"), ("PETG", "#00FF00")))
    loaded = [spool("PLA", "#FF0000"), spool("PETG", "#00FF00")]
    entries = rd.match_slots_setwise(rd.required_slots(t), loaded)
    assert [e["printer_slot"] for e in entries] == [0, 1]


def test_setwise_prefers_the_nearest_colour_among_same_family():
    t = traits(slots=(("PLA", "#FF0000"),))
    loaded = [spool("PLA", "#0000FF"), spool("PLA", "#FA0000")]
    entries = rd.match_slots_setwise(rd.required_slots(t), loaded)
    assert entries[0]["printer_slot"] == 1


def test_setwise_prefers_enough_weight_between_equal_colours():
    t = traits(slots=(("PLA", "#FF0000"),), grams={0: 200.0})
    short = spool("PLA", "#FF0000", remaining=10.0, quality="tracked",
                  as_of=NOW)
    full = spool("PLA", "#FF0000", remaining=900.0, quality="tracked",
                 as_of=NOW)
    entries = rd.match_slots_setwise(rd.required_slots(t), [short, full])
    assert entries[0]["printer_slot"] == 1


def test_setwise_loaded_spool_with_no_material_is_unknown_not_a_change():
    t = traits(slots=(("PLA", "#FF0000"),))
    entries = rd.match_slots_setwise(rd.required_slots(t), [spool(material=None)])
    assert entries[0]["state"] == "unknown"


def test_setwise_does_not_mutate_its_inputs():
    t = traits(slots=(("PLA", "#FF0000"), ("PETG", "#00FF00")), grams={0: 5.0})
    loaded = [spool("PETG", "#00FF00"), spool("PLA", "#FF0000")]
    before = copy.deepcopy((t, loaded))
    rd.match_slots_setwise(rd.required_slots(t), loaded)
    assert (t, loaded) == before


# --- determinism -------------------------------------------------------------------------

def test_output_is_deterministic():
    t = traits(slots=(("PLA", "#FF0000"), ("PETG", "#00FF00")), grams={0: 5.0})
    p = printer([spool("PETG", "#00FF00", remaining=50.0), spool("PLA", "#0000FF")])
    assert classify(t, p) == classify(copy.deepcopy(t), copy.deepcopy(p))


def test_summarise_counts_every_bucket():
    counts = rd.summarise([{"bucket": rd.READY_NOW}, {"bucket": rd.READY_NOW}])
    assert counts[rd.READY_NOW] == 2 and counts[rd.NEEDS_ATTENTION] == 0
    assert set(counts) == set(rd.BUCKETS)


def test_unreadable_file_gives_the_safe_reason_not_a_garbled_sentence():
    t = {"readable": False, "notes": ["This 3MF is too large for Studio to open safely."]}
    r = rd.classify_project(PROJECT, t, printer([spool()]), None, "unreadable")
    assert r["top_reason"] == "This 3MF is too large for Studio to open safely."
    assert "could not be read:" not in r["top_reason"]


def test_unreadable_file_without_a_note_says_so_plainly():
    r = rd.classify_project(PROJECT, None, printer([spool()]), None, "unreadable")
    assert r["top_reason"] == "Studio could not read this file."


def test_missing_file_reason():
    r = rd.classify_project(PROJECT, None, printer([spool()]), None, "missing")
    assert r["top_reason"] == "The project file could not be found."


def test_unanswerable_printer_check_is_not_ready_now():
    # Placement unavailable: bed fit cannot be checked, so Studio must not say ready.
    t = traits(grams={0: 20.0})
    r = classify(t, printer([spool(remaining=100.0, quality="tracked", as_of=NOW)]),
                 placement={"available": False, "off_plate": []})
    assert r["bucket"] != rd.READY_NOW


def test_unknown_nozzle_is_not_ready_now():
    t = traits(grams={0: 20.0})
    t["nozzle_diameters"] = _tier(None, "unknown")
    t["nozzle_diameters_by_toolhead"] = _tier(None, "unknown")
    r = classify(t, printer([spool(remaining=100.0, quality="tracked", as_of=NOW)]))
    assert r["bucket"] != rd.READY_NOW


def test_colour_note_does_not_hide_a_possible_shortage():
    t = traits(grams={0: 200.0})
    r = classify(t, printer([spool(color="#0000FF", remaining=195.0, quality="tracked", as_of=NOW)]))
    assert r["bucket"] == rd.READY_NOW
    assert r["colour_notes"]
    assert any("short" in u.lower() for u in r["unknowns"])
    assert r["top_reason"] != rd.COLOUR_NOTE
