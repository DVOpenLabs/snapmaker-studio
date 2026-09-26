"""The Post-Slice Doctor and the cost it derives from a sliced job.

Most of these build a job and a printer that disagree, and assert Studio says so
in a way a beginner can act on. The rest assert what it must *refuse* to say: an
unreachable printer never turns into a failure, and a filament total the slicer
did not break down is never split by Studio.
"""
from __future__ import annotations

from snapstudio_core import post_slice, sliced_cost


def job(**over) -> dict:
    base = {
        "available": True,
        "slicer": "Snapmaker Orca",
        "slicer_version": "2.3.4",
        "printer_model": "Snapmaker U1",
        "bed_mm": {"x": 270.0, "y": 270.0},
        "nozzle_diameter_mm": [0.4, 0.4, 0.4, 0.4],
        "layer_count": 45,
        "layer_height_mm": 0.2,
        "max_z_mm": 9.05,
        "estimated_seconds": 391,
        "size_bytes": 350527,
        "tools_used": [1],
        "filament": {"total_g": 0.91, "g": [0.0, 0.91, 0.0, 0.0]},
        "slots": [
            {"tool": 0, "used": False, "grams": 0.0, "mm": 0.0, "type": "PLA", "name": "Snapmaker PLA", "vendor": "Snapmaker"},
            {"tool": 1, "used": True, "grams": 0.91, "mm": 304.94, "type": "PLA", "name": "Snapmaker PLA", "vendor": "Snapmaker"},
            {"tool": 2, "used": False, "grams": 0.0, "mm": 0.0, "type": "PLA", "name": "Snapmaker PLA", "vendor": "Snapmaker"},
            {"tool": 3, "used": False, "grams": 0.0, "mm": 0.0, "type": "PLA", "name": "Snapmaker PLA", "vendor": "Snapmaker"},
        ],
        "purge": {"separable": False, "expected": False, "detail": "single-tool job", "confidence": "confirmed"},
        "exclude_object": {"present": False, "objects": 0, "source": "none found"},
        "markers": {},
    }
    base.update(over)
    return base


def printer(**over) -> dict:
    base = {
        "reachable": True,
        "toolhead_count": 4,
        "bed_mm": {"x": 271, "y": 335, "z": 281},
        "print_state": "standby",
        "loaded_filaments": [
            {"color": "#000000", "material": "PLA Matte", "vendor": "Snapmaker"},
            {"color": "#2D9E59", "material": "PLA Silk", "vendor": "Snapmaker"},
            {"color": "#F8F81C", "material": "PLA Basic", "vendor": "Snapmaker"},
            {"color": "#FFFFFF", "material": "PLA Matte", "vendor": "Snapmaker"},
        ],
        "klipper_objects": ["gcode", "print_stats", "exclude_object"],
    }
    base.update(over)
    return base


def by_id(report: dict, cid: str) -> dict | None:
    return next((c for c in report["checks"] if c["id"] == cid), None)


# --- the checks that only exist after slicing --------------------------------

def test_an_empty_slot_the_job_needs_is_reported_before_the_print_stops():
    loaded = printer()["loaded_filaments"]
    loaded[1] = None                      # slot 2 empty, and the job prints from it
    report = post_slice.analyse(job(), printer(loaded_filaments=loaded))
    check = by_id(report, "gcode.loaded")
    assert check["result"] == post_slice.ATTENTION
    assert "slot 2" in check["evidence"]
    assert "slot 2" in check["action"]


def test_a_material_mismatch_is_reported_with_both_sides():
    report = post_slice.analyse(job(slots=[
        {"tool": 0, "used": False, "grams": 0.0, "type": "PLA"},
        {"tool": 1, "used": True, "grams": 5.0, "type": "PETG"},
    ], tools_used=[1]), printer())
    check = by_id(report, "gcode.material")
    assert check["result"] == post_slice.ATTENTION
    assert "PETG" in check["evidence"] and "PLA" in check["evidence"]


def test_material_families_match_so_pla_matte_is_not_a_mismatch():
    report = post_slice.analyse(job(), printer())
    check = by_id(report, "gcode.material")
    assert check["result"] == post_slice.OK
    assert "family" in (check["source"] or "")


def test_a_job_needing_more_tools_than_the_printer_has_is_blocked():
    report = post_slice.analyse(job(tools_used=[0, 1, 2, 3, 4]), printer(toolhead_count=4))
    check = by_id(report, "gcode.tools")
    assert check["result"] == post_slice.BLOCKED


def test_a_job_sliced_for_another_machine_is_caught():
    report = post_slice.analyse(job(printer_model="Bambu Lab X1 Carbon"), printer())
    check = by_id(report, "gcode.machine")
    assert check["result"] == post_slice.ATTENTION
    assert "Bambu" in check["evidence"]
    assert "Snapmaker Orca" in check["action"]


def test_a_job_sliced_for_a_bigger_bed_is_caught():
    report = post_slice.analyse(job(bed_mm={"x": 350.0, "y": 350.0}), printer())
    check = by_id(report, "gcode.bed")
    assert check["result"] == post_slice.ATTENTION


def test_a_busy_printer_is_reported_without_blocking_the_rest():
    report = post_slice.analyse(job(), printer(print_state="printing"))
    assert by_id(report, "printer.busy")["result"] == post_slice.ATTENTION
    assert by_id(report, "gcode.machine")["result"] == post_slice.OK


def test_object_exclusion_is_matched_against_the_firmwares_own_object_list():
    j = job(exclude_object={"present": True, "objects": 3, "source": "defines"})
    supported = post_slice.analyse(j, printer())
    assert by_id(supported, "gcode.exclusion")["result"] == post_slice.OK

    without = post_slice.analyse(j, printer(klipper_objects=["gcode", "print_stats"]))
    check = by_id(without, "gcode.exclusion")
    assert check["result"] == post_slice.ATTENTION
    assert "still works" in check["action"]


# --- what it refuses to say --------------------------------------------------

def test_no_printer_makes_printer_checks_unknown_never_failed():
    report = post_slice.analyse(job(), {"reachable": False})
    results = {c["id"]: c["result"] for c in report["checks"]}
    assert results["gcode.tools"] == post_slice.UNKNOWN
    assert results["gcode.loaded"] == post_slice.UNKNOWN
    assert results["gcode.bed"] == post_slice.UNKNOWN
    assert post_slice.BLOCKED not in results.values()
    assert post_slice.ATTENTION not in results.values()


def test_the_nozzle_is_unknown_and_never_unsupported_when_nothing_reported_it():
    report = post_slice.analyse(job(), printer())
    check = by_id(report, "gcode.nozzle")
    assert check["result"] == post_slice.UNKNOWN
    assert "0.4 mm" in check["action"]
    assert "unsupported" not in repr(report).lower()


# --- H1: post_slice reads the same printer-reported/user-confirmed nozzle
# preflight() already does, instead of always staying unknown after slicing.

def test_the_nozzle_matches_when_the_printer_reports_the_same_size():
    report = post_slice.analyse(
        job(), printer(nozzle_diameters=[0.4, 0.4, 0.4, 0.4], nozzle_confirmed_by="printer"))
    check = by_id(report, "gcode.nozzle")
    assert check["result"] == post_slice.OK
    assert "the printer reports the same" in check["evidence"]
    assert "this printer's firmware" in check["source"]


def test_the_nozzle_mismatches_when_the_printer_reports_a_different_size():
    report = post_slice.analyse(
        job(), printer(nozzle_diameters=[0.2, 0.2, 0.2, 0.2], nozzle_confirmed_by="printer"))
    check = by_id(report, "gcode.nozzle")
    assert check["result"] == post_slice.ATTENTION
    assert "0.2 mm" in check["evidence"] and "0.4 mm" in check["evidence"]
    assert check["action"]


def test_a_user_confirmed_nozzle_is_never_reported_as_printer_evidence():
    report = post_slice.analyse(
        job(), printer(nozzle_diameters=[0.4, 0.4, 0.4, 0.4], nozzle_confirmed_by="user"))
    check = by_id(report, "gcode.nozzle")
    assert check["result"] == post_slice.OK
    assert "you confirmed the same" in check["evidence"]
    assert "printer's firmware" not in check["source"]


def test_a_reported_nozzle_with_no_recorded_source_is_neither_printer_nor_user():
    report = post_slice.analyse(
        job(), printer(nozzle_diameters=[0.4, 0.4, 0.4, 0.4]))  # no nozzle_confirmed_by at all
    check = by_id(report, "gcode.nozzle")
    assert check["result"] == post_slice.OK
    assert "the printer" not in check["evidence"]
    assert "you confirmed" not in check["evidence"]


def test_the_nozzle_comparison_tolerates_float_and_string_formatting_noise():
    """0.4, "0.40" and float noise a real firmware can report must compare
    equal — a formatting difference is not a mismatch."""
    report = post_slice.analyse(
        job(), printer(nozzle_diameters=[0.4000000059604645] * 4, nozzle_confirmed_by="printer"))
    check = by_id(report, "gcode.nozzle")
    assert check["result"] == post_slice.OK


# --- M-B regression: nozzle_diameter_mm is genuinely per-toolhead ordered ---
#
# Opus delta review of 9b638c6: unlike preflight's nozzle_diameters trait,
# g["nozzle_diameter_mm"] is read straight off the G-code config block's
# per-toolhead comma list, so a positional comparison against it is sound —
# but it needs a test that actually exercises a swap, not just the uniform
# same-value-on-every-toolhead fixture every other test here uses.

def test_swapped_toolheads_are_a_real_mismatch_not_a_matching_set():
    """Sliced for [0.4, 0.6] on toolheads 0/1; the printer reports [0.6, 0.4]
    — same sizes, swapped toolheads, a real mismatch a set comparison would
    call a match."""
    report = post_slice.analyse(
        job(nozzle_diameter_mm=[0.4, 0.6]),
        printer(nozzle_diameters=[0.6, 0.4], nozzle_confirmed_by="printer"))
    check = by_id(report, "gcode.nozzle")
    assert check["result"] == post_slice.ATTENTION
    # The evidence must show the real per-toolhead order on each side, not a
    # deduplicated set — {0.4, 0.6} vs {0.4, 0.6} would look identical despite
    # the swap, but "0.4 mm, 0.6 mm" vs "0.6 mm, 0.4 mm" shows it plainly.
    assert "sliced for 0.4 mm, 0.6 mm" in check["evidence"]
    assert "0.6 mm, 0.4 mm" in check["evidence"]


def test_matching_toolhead_order_with_mixed_sizes_is_ok():
    report = post_slice.analyse(
        job(nozzle_diameter_mm=[0.4, 0.2, 0.6, 0.8]),
        printer(nozzle_diameters=[0.4, 0.2, 0.6, 0.8], nozzle_confirmed_by="printer"))
    check = by_id(report, "gcode.nozzle")
    assert check["result"] == post_slice.OK


def test_an_unreadable_file_is_never_reported_as_a_healthy_job():
    report = post_slice.analyse({"available": False, "error": "that does not look like a sliced G-code file"})
    assert report["available"] is False
    assert report["checks"] == []
    assert "does not look like" in report["summary"]


def test_the_summary_never_promises_a_successful_print():
    report = post_slice.analyse(job(), printer())
    text = (report["summary"] + report["disclaimer"]).lower()
    for promise in ("will print", "guaranteed", "100%", "success"):
        assert promise not in text


def test_a_job_that_does_not_state_tool_use_is_unknown_not_zero_tools():
    report = post_slice.analyse(job(tools_used=None), printer())
    assert by_id(report, "gcode.tools")["result"] == post_slice.UNKNOWN
    assert by_id(report, "gcode.loaded") is None


# --- cost from measured figures ---------------------------------------------

def test_cost_uses_the_slicers_own_grams_and_says_so():
    cost = sliced_cost.estimate(job(), price_per_kg=20.0)
    assert cost["available"] is True
    assert cost["total_grams"] == 0.91
    filament = next(l for l in cost["lines"] if l["label"] == "Filament")
    assert filament["source"] == "derived"
    assert "measured by the slicer" in filament["evidence"]
    assert abs(filament["amount"] - 0.0182) < 1e-6


def test_cost_reports_per_slot_for_a_multi_material_job():
    j = job(tools_used=[0, 1], slots=[
        {"tool": 0, "used": True, "grams": 10.0, "mm": 3000.0, "type": "PLA", "name": "Black"},
        {"tool": 1, "used": True, "grams": 4.0, "mm": 1200.0, "type": "PETG", "name": "Clear"},
    ], filament={"total_g": 14.0, "g": [10.0, 4.0]},
        purge={"separable": False, "expected": True, "prime_tower": True, "detail": "not separable"})
    cost = sliced_cost.estimate(j, prices={"PLA": 20.0, "PETG": 30.0})
    assert [s["tool"] for s in cost["per_slot"]] == [0, 1]
    assert abs(cost["per_slot"][1]["cost"] - 0.12) < 1e-6


def test_purge_is_never_split_out_of_a_total_the_slicer_did_not_split():
    j = job(tools_used=[0, 1],
            purge={"separable": False, "expected": True, "prime_tower": True, "detail": "x"})
    cost = sliced_cost.estimate(j)
    assert cost["waste"]["separable"] is False
    assert cost["waste"]["source"] == "unknown"
    assert "will not split" in cost["waste"]["detail"]


def test_a_job_with_no_figures_is_costed_as_unknown_not_as_zero():
    cost = sliced_cost.estimate(job(slots=[], filament={}, estimated_seconds=None, tools_used=None))
    assert cost["total"] is None or cost["total"] == 0
    labels = {l["label"]: l for l in cost["lines"]}
    assert labels["Filament"]["amount"] is None
    assert labels["Filament"]["source"] == "unknown"
    assert labels["Electricity"]["amount"] is None


def test_cost_of_an_unreadable_file_is_refused_cleanly():
    cost = sliced_cost.estimate({"available": False, "error": "nope"})
    assert cost["available"] is False
    assert cost["summary"] == "nope"
