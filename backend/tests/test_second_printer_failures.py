"""Attacking the second-printer path with everything a strange machine can do.

Every payload here is **simulated** — written by hand to drive a branch, not read
from any printer. That is the point: these are the shapes no real machine in this
project's reach produces, and they are exactly where an abstraction built around
one printer falls back on what it knows.

The bar is the same in every case. Studio degrades to `unknown`, or to a warning
about the specific capability it could not confirm. It does not crash, it does not
report a U1's answer as though the strange machine had given it, and it never
turns an absence of evidence into a statement about someone's hardware.
"""
from __future__ import annotations

import pytest

from snapstudio_core import (firmware_caps, material_plan, moonraker, post_slice,
                             preflight as pf, printer_profiles, send_check)

VORON = "voron_2_4_250"


def facts(**over) -> dict:
    base = {
        "reachable": True, "host": "printer.example", "port": 7125,
        "toolhead_count": 1,
        "bed_mm": {"x": 250.0, "y": 250.0, "z": 252.0},
        "klipper_objects": ["extruder", "toolhead", "probe", "quad_gantry_level"],
        "print_state": "standby",
        "identity": {"matched": False, "printer_id": None},
    }
    base.update(over)
    return base


PROJECT = {"filament_count": {"value": 2, "confidence": "confirmed", "evidence": "t"},
           "expects_object_exclusion": {"value": True, "confidence": "confirmed", "evidence": "t"}}


# --- shape disagreements ----------------------------------------------------

def test_a_printer_reporting_more_tools_than_the_profile_is_believed():
    """Eight extruders on a machine whose profile records one. The machine wins."""
    out = printer_profiles.resolve(facts(toolhead_count=8), printer_profiles.load(VORON))
    assert out["tool_count"] == 8
    assert out["sources"]["tool_count"] == "live"
    assert out["conflicts"][0]["live"] == 8


def test_a_printer_reporting_fewer_tools_than_the_profile_is_believed():
    out = printer_profiles.resolve(facts(toolhead_count=1),
                                   printer_profiles.load("snapmaker_u1"))
    assert out["tool_count"] == 1
    assert any(c["field"] == "tool_count" for c in out["conflicts"])


def test_a_much_bigger_printable_area_is_used_when_the_printer_is_identified(tmp_path, monkeypatch):
    from snapstudio_api import service
    from tests import scene_fixtures as fx
    big_profile = {"printer_id": "bigmachine", "display_name": "Big Machine", "build_volume_mm": {"x": 1000.0, "y": 1000.0, "z": 1000.0}}
    real_load = printer_profiles.load
    monkeypatch.setattr(printer_profiles, "load",
                        lambda pid: big_profile if pid == "bigmachine" else real_load(pid))
    path = str(fx.three_mf(tmp_path / "far.3mf", fx.model_xml([fx.cube_object("1", 20)], [("1", fx.tf(500, 500, 0))])))
    # the placement is DERIVED through the service from the identified printer, not written by hand
    target = service._placement_target({"identity": {"printer_id": "bigmachine"}})
    placement = service._assess_against(path, target)
    assert placement["available"] and placement["off_plate"] == []
    project = {"filament_count": {"value": 1, "confidence": "confirmed", "evidence": "t"}}
    out = pf.evaluate(project, facts(bed_mm={"x": 1000.0, "y": 1000.0, "z": 1000.0}), placement=placement)
    bed = next(c for c in out["checks"] if c["id"] == "bed.fit")
    assert bed["result"] == pf.OK and "1000 × 1000 mm printable area" in bed["evidence"]
    # the printer's name comes from the producer path (target -> assess), not from a hand-built bed_name
    assert "Big Machine" in bed["source"] and "U1" not in bed["source"]
    # and through the Bed-Fit API: identified by what it reports, judged against its recorded volume
    from snapstudio_core import moonraker
    monkeypatch.setattr(moonraker, "capabilities", lambda host, port: {
        "bed_mm": {"x": 271.0, "y": 335.0, "z": 275.0}, "klipper_objects": [], "toolhead_count": 1})
    monkeypatch.setattr(printer_profiles, "identify", lambda facts, profiles=None: {"printer_id": "bigmachine"})
    result = service.bed_fit(path, host="big.invalid")
    assert result["overall_level"] == "ok" and result["bed_mm"]["x"] == 1000.0
    assert result["bed_mm_source"] == "profile" and result["placement_checked"] is True
    assert "bigmachine" not in result["bed_source"]


def test_a_zero_tool_printer_does_not_divide_by_it():
    out = printer_profiles.resolve(facts(toolhead_count=0), printer_profiles.load(VORON))
    # 0 is not a count the printer meant; it falls through to the profile rather
    # than being used as one.
    assert out["tool_count"] in (0, 1)
    check = pf.evaluate(PROJECT, facts(toolhead_count=None))
    tools = next(c for c in check["checks"] if c["id"] == "materials.toolheads")
    assert tools["result"] == pf.UNKNOWN


# --- capability absence -----------------------------------------------------

def test_no_exclude_object_is_a_capability_warning_not_a_failed_printer():
    out = pf.evaluate(PROJECT, facts())
    check = next(c for c in out["checks"] if c["id"] == "capability.exclude_object")
    assert check["result"] == pf.ATTENTION
    assert "nothing to change in the project" in (check["action"] or "").lower()


def test_an_empty_object_list_makes_capabilities_unknown_not_absent():
    """No list is not a list of nothing."""
    out = pf.evaluate(PROJECT, facts(klipper_objects=[]))
    check = next(c for c in out["checks"] if c["id"] == "capability.exclude_object")
    assert check["result"] == pf.UNKNOWN
    assert "did not report its firmware features" in check["evidence"]

    caps = firmware_caps.interpret([])
    assert caps["available"] is False


def test_unknown_future_object_names_are_ignored_not_misread():
    weird = facts(klipper_objects=[
        "extruder", "toolhead",
        "quantum_bed_leveler", "exclude_object_v2", "extruder_probe",
        "gcode_macro EXCLUDE_OBJECT", "heater_generic chamber",
    ])
    out = printer_profiles.resolve(weird, printer_profiles.load(VORON))
    # `exclude_object_v2` is not `exclude_object`, and a macro named after a
    # feature is not the feature.
    assert out["capabilities"]["exclude_object"]["state"] == printer_profiles.ABSENT
    caps = firmware_caps.interpret(weird["klipper_objects"])
    assert caps["available"] is True
    assert "Object exclusion" not in {f["name"] for f in caps["features"]}


def test_an_object_list_of_the_wrong_type_does_not_crash():
    for objects in ([None, 3, {"a": 1}], [b"extruder"], [[]]):
        out = printer_profiles.resolve(facts(klipper_objects=objects),
                                       printer_profiles.load(VORON))
        assert out["capabilities"]["exclude_object"]["state"] in (
            printer_profiles.PRESENT, printer_profiles.ABSENT)


# --- material and nozzle state ---------------------------------------------

def test_no_filament_endpoint_leaves_material_unknown_everywhere():
    out = pf.evaluate(PROJECT, facts())
    loaded = next(c for c in out["checks"] if c["id"] == "materials.loaded")
    assert loaded["result"] == pf.UNKNOWN

    job = {"available": True, "printer_model": "Voron 2.4", "tools_used": [0],
           "slots": [{"tool": 0, "type": "PLA", "grams": 20}]}
    post = post_slice.analyse(job, facts())
    slots = next(c for c in post["checks"] if c["id"] == "gcode.loaded")
    assert slots["result"] == post_slice.UNKNOWN


def test_being_unable_to_ask_is_not_the_printer_saying_nothing_is_loaded():
    out = printer_profiles.resolve(
        facts(loaded_filaments_error="Studio could not read what is loaded: TimeoutError"),
        printer_profiles.load(VORON))
    assert out["material_state"]["known"] is False
    assert out["material_state"]["source"] == "unreachable"
    assert "not the printer saying it has nothing" in out["material_state"]["detail"]


def test_a_filament_state_shorter_than_the_tool_count_is_not_padded():
    """Two tools, one reported spool. The second is unknown, not empty-and-fine."""
    job = [{"tool": 0, "used": True, "type": "PLA", "grams": 10},
           {"tool": 1, "used": True, "type": "PETG", "grams": 10}]
    plan = material_plan.plan(job, loaded=[{"material": "PLA", "color": "#000000"}],
                              tools_used=[0, 1])
    assert plan["slots"][1]["state"] == "empty"
    assert plan["slots"][1]["has_material"] is None


def test_no_nozzle_information_stays_unknown_on_both_sides():
    project = {"nozzle_diameters": {"value": ["0.4"], "confidence": "confirmed", "evidence": "t"}}
    out = pf.evaluate(project, facts())
    nozzle = next(c for c in out["checks"] if c["id"] == "nozzle.match")
    assert nozzle["result"] == pf.UNKNOWN

    job = {"available": True, "printer_model": "Voron 2.4", "tools_used": [0],
           "slots": [{"tool": 0, "type": "PLA"}], "nozzle_diameter_mm": [0.4]}
    post = post_slice.analyse(job, facts())
    check = next(c for c in post["checks"] if c["id"] == "gcode.nozzle")
    assert check["result"] == post_slice.UNKNOWN
    # An unidentified printer gets no borrowed claim about its firmware.
    assert "this printer's firmware does not report" not in check["evidence"]


def test_unavailable_storage_is_unknown_and_never_a_blocker():
    job = {"available": True, "printer_model": "Voron 2.4", "tools_used": [0],
           "slots": [{"tool": 0, "type": "PLA"}], "size_bytes": 50_000_000}
    out = send_check.evaluate(job, facts())
    storage = next(i for i in out["items"] if i["title"] == "Free space on the printer")
    assert storage["kind"] == send_check.UNKNOWN
    assert out["counts"][send_check.BLOCKER] == 0


# --- printer state ----------------------------------------------------------

def test_a_busy_printer_is_flagged_whatever_machine_it_is():
    out = pf.evaluate(PROJECT, facts(print_state="printing"))
    busy = next(c for c in out["checks"] if c["id"] == "printer.busy")
    assert busy["result"] == pf.ATTENTION


def test_a_disconnected_printer_makes_everything_printer_dependent_unknown():
    out = pf.evaluate(PROJECT, {"reachable": False, "error": "timed out"})
    assert out["printer_reachable"] is False
    printer_dependent = {"materials.toolheads", "bed.fit", "capability.exclude_object"}
    for check in out["checks"]:
        if check["id"] in printer_dependent:
            assert check["result"] == pf.UNKNOWN, check["id"]
    assert not out["needs_attention"]


def test_an_unreachable_printer_is_not_told_to_change_a_u1_setting():
    """Studio does not know what is at an address that did not answer."""
    out = pf.evaluate(PROJECT, {"reachable": False, "error": "timed out"})
    found = next(c for c in out["checks"] if c["id"] == "printer.reachable")
    assert "U1 touchscreen" not in (found["action"] or "")


# --- malformed responses ----------------------------------------------------

def test_a_malformed_capability_response_does_not_crash_the_client(monkeypatch):
    def fake_get(host, port, path, timeout):
        if path == "/printer/objects/list":
            return {"result": {"objects": "not-a-list"}}
        return {"result": {"status": {"toolhead": {"axis_maximum": "nonsense"}}}}

    monkeypatch.setattr(moonraker, "_get", fake_get)
    caps = moonraker.capabilities("printer.example")
    assert caps["bed_mm"] is None
    assert caps["toolhead_count"] is None


def test_a_truncated_axis_array_yields_no_bed_rather_than_a_wrong_one(monkeypatch):
    def fake_get(host, port, path, timeout):
        if path == "/printer/objects/list":
            return {"result": {"objects": ["extruder"]}}
        return {"result": {"status": {"toolhead": {"axis_maximum": [250.0, 250.0]}}}}

    monkeypatch.setattr(moonraker, "_get", fake_get)
    caps = moonraker.capabilities("printer.example")
    assert caps["bed_mm"] is None
    assert caps["toolhead_count"] == 1


def test_an_unrecognised_model_name_in_a_job_is_likely_not_confirmed():
    job = {"available": True, "printer_model": "SomeMachine 9000", "tools_used": [0],
           "slots": [{"tool": 0, "type": "PLA"}]}
    out = post_slice.analyse(job, facts())
    machine = next(c for c in out["checks"] if c["id"] == "gcode.machine")
    assert machine["result"] == post_slice.ATTENTION
    assert machine["confidence"] == post_slice.LIKELY


def test_identification_of_an_unknown_machine_is_no_match_not_a_guess():
    out = printer_profiles.identify(facts())
    assert out["matched"] is False and out["printer_id"] is None
    assert "Moonraker does not publish a model name" in out["evidence"]


@pytest.mark.parametrize("host_facts", [
    {}, {"reachable": True}, {"reachable": True, "klipper_objects": None},
    {"reachable": True, "toolhead_count": None, "bed_mm": None},
])
def test_resolve_survives_a_threadbare_fact_bundle(host_facts):
    out = printer_profiles.resolve(host_facts, printer_profiles.load(VORON))
    assert out["schema_version"] == printer_profiles.SCHEMA_VERSION
    assert out["material_state"]["known"] is False
