"""Project ↔ printer preflight.

The point of this module is the join, and the risk of a join is that it invents
one side. These tests are weighted towards the cases where Studio must say
"unknown" — a printer that did not answer, a firmware that does not publish the
nozzle, a machine that does not report what is loaded — because turning any of
those into a pass or a failure is the failure mode that would make the feature
worse than not having it.
"""
from __future__ import annotations

import pytest

from snapstudio_core import preflight as pf


def traits(**values):
    return {k: {"value": v, "confidence": "confirmed", "evidence": f"test:{k}"}
            for k, v in values.items()}


def printer(**values):
    base = {"reachable": True, "host": "u1.local", "port": 7125,
            "toolhead_count": 4, "bed_mm": {"x": 270, "y": 270, "z": 270},
            "klipper_objects": ["exclude_object", "extruder", "bed_mesh"],
            "print_state": "standby"}
    base.update(values)
    return base


def placement(off=0, fixable=True, available=True):
    return {"available": available, "fixable": fixable,
            "off_plate": [{"object_id": str(i)} for i in range(off)]}


def by_id(result, check_id):
    return next((c for c in result["checks"] if c["id"] == check_id), None)


# --- the printer half -------------------------------------------------------

def test_unreachable_printer_makes_printer_checks_unknown_not_failed():
    out = pf.evaluate(traits(filament_count=4), {"reachable": False, "error": "timed out"})
    assert out["printer_reachable"] is False
    assert by_id(out, "printer.reachable")["result"] == pf.UNKNOWN
    assert by_id(out, "materials.toolheads")["result"] == pf.UNKNOWN
    assert by_id(out, "bed.fit")["result"] == pf.UNKNOWN
    # Nothing about a missing printer may read as a verdict on the printer.
    assert all(c["result"] != pf.BLOCKED for c in out["checks"])


def test_unreachable_printer_offers_the_advanced_mode_fix():
    out = pf.evaluate(traits(), {"reachable": False, "hint": "turn on Advanced Mode"})
    assert "Advanced Mode" in by_id(out, "printer.reachable")["action"]


def test_reachable_printer_passes_and_cites_its_source():
    out = pf.evaluate(traits(), printer())
    check = by_id(out, "printer.reachable")
    assert check["result"] == pf.OK
    assert "u1.local" in check["evidence"]
    assert check["source"]


# --- toolheads vs materials -------------------------------------------------

def test_materials_fit_the_toolheads():
    out = pf.evaluate(traits(filament_count=4), printer(toolhead_count=4))
    assert by_id(out, "materials.toolheads")["result"] == pf.OK


def test_more_materials_than_toolheads_needs_attention():
    out = pf.evaluate(traits(filament_count=6), printer(toolhead_count=4))
    check = by_id(out, "materials.toolheads")
    assert check["result"] == pf.ATTENTION
    assert "6" in check["evidence"] and "4" in check["evidence"]
    assert check["action"]


def test_a_printer_that_did_not_report_toolheads_is_unknown():
    out = pf.evaluate(traits(filament_count=4), printer(toolhead_count=None))
    assert by_id(out, "materials.toolheads")["result"] == pf.UNKNOWN


def test_a_project_with_no_filaments_is_not_an_attention_item():
    out = pf.evaluate(traits(filament_count=0), printer())
    assert by_id(out, "materials.toolheads")["result"] == pf.OK


# --- the nozzle, which is usually unknowable --------------------------------

def test_nozzle_is_unknown_when_the_firmware_does_not_report_one():
    """Stock U1 firmware publishes no nozzle diameter. Studio must say so."""
    out = pf.evaluate(traits(nozzle_diameters=["0.4"]), printer())
    check = by_id(out, "nozzle.match")
    assert check["result"] == pf.UNKNOWN
    assert check["confidence"] == pf.CONFIRMED     # certain that it cannot be known
    assert "0.4 mm" in check["action"]


def test_nozzle_matches_when_the_printer_does_report_one():
    out = pf.evaluate(traits(nozzle_diameters=["0.4"]),
                      printer(nozzle_diameters=["0.4", "0.4"]))
    assert by_id(out, "nozzle.match")["result"] == pf.OK


def test_nozzle_mismatch_is_flagged_with_both_values():
    out = pf.evaluate(traits(nozzle_diameters=["0.2"]), printer(nozzle_diameters=["0.4"]))
    check = by_id(out, "nozzle.match")
    assert check["result"] == pf.ATTENTION
    assert "0.2 mm" in check["evidence"] and "0.4 mm" in check["evidence"]


def test_a_project_without_a_nozzle_size_is_unknown_not_ok():
    out = pf.evaluate(traits(nozzle_diameters=[]), printer())
    assert by_id(out, "nozzle.match")["result"] == pf.UNKNOWN


def test_nozzle_reported_by_printer_says_so_in_the_source():
    """/machine/system_info answering is real firmware evidence — say so, not
    a generic 'printer configuration'."""
    out = pf.evaluate(traits(nozzle_diameters=["0.4"]),
                      printer(nozzle_diameters=["0.4"], nozzle_confirmed_by="printer"))
    check = by_id(out, "nozzle.match")
    assert check["result"] == pf.OK
    assert check["source"] == "printer firmware"


def test_nozzle_confirmed_by_user_is_never_reported_as_printer_evidence():
    """A user-confirmed nozzle must be distinguishable from a live firmware
    read — the mandate is explicit that these are different evidence tiers."""
    out = pf.evaluate(traits(nozzle_diameters=["0.4"]),
                      printer(nozzle_diameters=["0.4"], nozzle_confirmed_by="user"))
    check = by_id(out, "nozzle.match")
    assert check["result"] == pf.OK
    assert check["source"] == "user confirmed"
    assert "printer" not in check["source"]


def test_nozzle_mismatch_still_flagged_when_only_user_confirmed():
    """A user-confirmed nozzle that doesn't match the project is just as real
    and actionable a warning as a printer-reported mismatch."""
    out = pf.evaluate(traits(nozzle_diameters=["0.2"]),
                      printer(nozzle_diameters=["0.4"], nozzle_confirmed_by="user"))
    check = by_id(out, "nozzle.match")
    assert check["result"] == pf.ATTENTION
    assert check["source"] == "user confirmed"
    assert check["confidence"] == pf.CONFIRMED


# --- the bed ----------------------------------------------------------------

def test_bed_uses_the_printers_real_dimensions_in_its_evidence():
    out = pf.evaluate(traits(), printer(bed_mm={"x": 270, "y": 270, "z": 270}),
                      placement=placement(off=0))
    check = by_id(out, "bed.fit")
    assert check["result"] == pf.OK
    assert "270" in check["evidence"]


def test_objects_off_the_real_bed_need_attention_and_point_at_the_fix():
    out = pf.evaluate(traits(), printer(), placement=placement(off=2, fixable=True))
    check = by_id(out, "bed.fit")
    assert check["result"] == pf.ATTENTION
    assert "placement fix" in check["action"] or "placement" in check["action"]


def test_unfixable_placement_points_at_arrange_instead():
    out = pf.evaluate(traits(), printer(), placement=placement(off=1, fixable=False))
    assert "Arrange" in by_id(out, "bed.fit")["action"]


def test_bed_is_unknown_when_placement_could_not_be_read():
    out = pf.evaluate(traits(), printer(), placement=placement(available=False))
    assert by_id(out, "bed.fit")["result"] == pf.UNKNOWN


# --- object exclusion -------------------------------------------------------

def test_object_exclusion_is_only_raised_when_the_project_depends_on_it():
    quiet = pf.evaluate(traits(expects_object_exclusion=False),
                        printer(klipper_objects=["extruder"]))
    assert by_id(quiet, "capability.exclude_object") is None


def test_object_exclusion_present_is_reported_when_the_project_expects_it():
    out = pf.evaluate(traits(expects_object_exclusion=True), printer())
    assert by_id(out, "capability.exclude_object")["result"] == pf.OK


def test_object_exclusion_absent_is_attention_not_blocked():
    out = pf.evaluate(traits(expects_object_exclusion=True),
                      printer(klipper_objects=["extruder", "bed_mesh"]))
    check = by_id(out, "capability.exclude_object")
    assert check["result"] == pf.ATTENTION
    assert "firmware feature" in check["action"]


def test_object_exclusion_is_unknown_when_the_object_list_is_missing():
    out = pf.evaluate(traits(expects_object_exclusion=True),
                      printer(klipper_objects=[]))
    assert by_id(out, "capability.exclude_object")["result"] == pf.UNKNOWN


# --- loaded materials -------------------------------------------------------

def test_loaded_materials_unknown_when_the_firmware_does_not_report_them():
    out = pf.evaluate(traits(filament_count=4), printer())   # no loaded_filaments key
    check = by_id(out, "materials.loaded")
    assert check["result"] == pf.UNKNOWN
    assert "does not report" in check["evidence"]


def test_fewer_loaded_than_needed_is_attention():
    out = pf.evaluate(traits(filament_count=4),
                      printer(loaded_filaments=[{"color": "#f00"}, None, None, None]))
    assert by_id(out, "materials.loaded")["result"] == pf.ATTENTION


def test_enough_loaded_is_ok():
    loaded = [{"color": "#f00"}, {"color": "#0f0"}, {"color": "#00f"}, {"color": "#fff"}]
    out = pf.evaluate(traits(filament_count=4), printer(loaded_filaments=loaded))
    assert by_id(out, "materials.loaded")["result"] == pf.OK


# --- printer state ----------------------------------------------------------

@pytest.mark.parametrize("state", ["printing", "paused"])
def test_a_busy_printer_is_flagged(state):
    out = pf.evaluate(traits(), printer(print_state=state))
    assert by_id(out, "printer.busy")["result"] == pf.ATTENTION


def test_an_idle_printer_is_fine():
    out = pf.evaluate(traits(), printer(print_state="standby"))
    assert by_id(out, "printer.busy")["result"] == pf.OK


# --- shape and wording ------------------------------------------------------

def test_every_check_carries_the_full_explanation_shape():
    out = pf.evaluate(traits(filament_count=6, nozzle_diameters=["0.2"],
                             expects_object_exclusion=True, is_sliced=True),
                      printer(), placement=placement(off=1))
    assert out["checks"]
    for check in out["checks"]:
        assert check["id"] and check["title"]
        assert check["result"] in (pf.OK, pf.ATTENTION, pf.UNKNOWN, pf.BLOCKED)
        assert check["confidence"] in (pf.CONFIRMED, pf.LIKELY, pf.INFORMATIONAL)
        assert check["consequence"], f"{check['id']} has no consequence"
        if check["result"] != pf.OK:
            assert check["action"], f"{check['id']} needs an action"


def test_problems_are_ordered_before_unknowns_and_passes():
    out = pf.evaluate(traits(filament_count=6, nozzle_diameters=["0.2"]), printer())
    results = [c["result"] for c in out["checks"]]
    assert results == sorted(results, key=lambda r: pf._ORDER[r])


def test_summary_counts_problems_and_unknowns_separately():
    out = pf.evaluate(traits(filament_count=6, nozzle_diameters=["0.4"]), printer())
    assert "resolve" in out["summary"]
    assert "cannot check" in out["summary"]


def test_a_clean_project_says_so_without_hedging():
    out = pf.evaluate(traits(filament_count=2, nozzle_diameters=["0.4"], is_sliced=False),
                      printer(nozzle_diameters=["0.4"],
                              loaded_filaments=[{"color": "#f00"}, {"color": "#0f0"}]),
                      placement=placement(off=0))
    assert out["counts"][pf.ATTENTION] == 0
    assert out["counts"][pf.UNKNOWN] == 0
    assert "Nothing to resolve" in out["summary"]


def test_no_check_ever_promises_a_successful_print():
    out = pf.evaluate(traits(filament_count=2), printer(), placement=placement(off=0))
    blob = " ".join(
        str(v) for c in out["checks"] for v in c.values() if isinstance(v, str)
    ).lower() + out["summary"].lower() + out["disclaimer"].lower()
    for phrase in ("will print", "guaranteed", "ready to print", "100%"):
        assert phrase not in blob


def test_never_reports_not_detected_as_not_supported():
    """The hard rule, asserted directly on the wording of every unknown."""
    out = pf.evaluate(traits(filament_count=4, nozzle_diameters=["0.4"],
                             expects_object_exclusion=True),
                      {"reachable": True, "host": "u1.local", "port": 7125,
                       "klipper_objects": []})
    for check in out["unknowns"]:
        text = f"{check['title']} {check['consequence']} {check['evidence']}".lower()
        assert "not supported" not in text
        assert "unsupported" not in text
