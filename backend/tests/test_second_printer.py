"""The same printer intelligence, run against a printer that is not a U1.

This is the architecture proof. Every check exercised here is the *same function*
the U1 uses — `moonraker.capabilities`, `printer_profiles.resolve`,
`firmware_caps.interpret`, `preflight.evaluate`, `post_slice.analyse`,
`send_check.evaluate`, `material_plan.plan`. Nothing is re-implemented for a
second machine, and there is deliberately no branch anywhere that asks which
printer it is looking at before deciding how to behave.

The machine is a VORON 2.4 250, and it was chosen because it disagrees with the
U1 about nearly everything Studio might have assumed: one extruder rather than
four, a 250 mm cube rather than the U1's plate, no object exclusion, no bed mesh,
and — the one that matters most — nothing whatsoever that reports which filament
is loaded.

**Nothing here is hardware evidence.** The Moonraker payloads are derived from the
configuration Klipper publishes for this machine (see
`fixtures/printers/PROVENANCE.md`). What these tests prove is that Studio's logic
is driven by what a printer reports; they prove nothing about a physical VORON,
and the profile's verification level says so in the product too.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from snapstudio_core import (firmware_caps, material_plan, moonraker, post_slice,
                             preflight as pf, printer_profiles, send_check)

FIXTURE = Path(__file__).parent / "fixtures" / "printers" / "voron_2_4_250_moonraker.json"


@pytest.fixture(scope="module")
def voron_payload() -> dict:
    return json.loads(FIXTURE.read_text("utf-8"))


@pytest.fixture
def voron_moonraker(monkeypatch, voron_payload):
    """Replay the derived payload through the real Moonraker client.

    The client's own parsing runs — the object-list walk that counts extruders,
    the axis-limit arithmetic that derives a bed, the `print_task_config` lookup
    that finds nothing. Only the socket is replaced.
    """
    def fake_get(host, port, path, timeout):
        if path == "/printer/objects/list":
            return {"result": {"objects": voron_payload["objects_list"]}}
        if path.startswith("/printer/objects/query?toolhead"):
            return {"result": {"status": {"toolhead": voron_payload["toolhead"]}}}
        if path.startswith("/printer/objects/query?print_task_config"):
            # Moonraker omits an object the printer does not have. It does not
            # error, and it does not return a placeholder.
            return {"result": {"status": {}}}
        if path.startswith("/printer/objects/query?"):
            status = {k: voron_payload[k] for k in
                      ("print_stats", "heater_bed", "virtual_sdcard",
                       "display_status", "gcode_move", "extruder")
                      if k in voron_payload}
            status["toolhead"] = voron_payload["toolhead"]
            return {"result": {"status": status}}
        if path == "/server/info":
            return {"result": voron_payload["server_info"]}
        raise AssertionError(f"unexpected read-only path: {path}")

    monkeypatch.setattr(moonraker, "_get", fake_get)
    return fake_get


def voron_facts() -> dict:
    """The fact bundle `service.printer_facts` would build for this machine."""
    payload = json.loads(FIXTURE.read_text("utf-8"))
    limits = payload["toolhead"]
    hi, lo = limits["axis_maximum"], limits["axis_minimum"]
    return {
        "reachable": True, "host": "printer.example", "port": 7125,
        "toolhead_count": 1,
        "bed_mm": {"x": round(hi[0] - lo[0], 1), "y": round(hi[1] - lo[1], 1),
                   "z": round(hi[2] - lo[2], 1)},
        "klipper_objects": payload["objects_list"],
        "print_state": "standby",
        "identity": {"matched": False, "printer_id": None},
    }


# --- what the Moonraker client itself reads ---------------------------------

def test_capabilities_reads_one_extruder_and_a_250_cube(voron_moonraker):
    """The same function that reports four toolheads on a U1 reports one here."""
    caps = moonraker.capabilities("printer.example")
    assert caps["toolhead_count"] == 1
    # 250 in X and Y; 252 in Z because stepper_z declares position_min -2, which
    # is quad-gantry-levelling headroom rather than printable depth.
    assert caps["bed_mm"] == {"x": 250.0, "y": 250.0, "z": 252.0}


def test_status_asks_for_the_extruders_this_printer_has(voron_moonraker):
    """A one-toolhead printer is not described with four temperature channels."""
    live = moonraker.status("printer.example", tool_count=1)
    assert len(live["toolheads"]) == 1
    assert live["print_state"] == "standby"


def test_the_printer_reports_no_loaded_filament(voron_moonraker):
    """`None` — not an empty list, which would read as "nothing is loaded"."""
    assert moonraker.loaded_filaments("printer.example") is None


# --- profile resolution -----------------------------------------------------

def test_the_profile_is_never_presented_as_hardware_verified():
    profile = printer_profiles.load("voron_2_4_250")
    assert profile["verification_level"] == printer_profiles.PROFILE_VERIFIED
    label = printer_profiles.level_label(profile["verification_level"])
    assert label == "Profile verified — hardware not tested by this project"
    # The qualifier is the label. Nothing may shorten it to a bare "verified".
    assert "hardware not tested" in label
    assert printer_profiles.load("snapmaker_u1")["verification_level"] == \
        printer_profiles.HARDWARE_VERIFIED


def test_every_profile_fact_carries_a_source():
    for profile in printer_profiles.load_all():
        assert profile.get("source_refs"), profile["printer_id"]
        assert profile.get("verification_note")


def test_resolve_uses_the_live_printer_over_the_profile():
    """The rule the whole abstraction stands on."""
    profile = printer_profiles.load("voron_2_4_250")
    facts = dict(voron_facts(), toolhead_count=2)
    out = printer_profiles.resolve(facts, profile)
    assert out["tool_count"] == 2
    assert out["sources"]["tool_count"] == "live"
    conflict = next(c for c in out["conflicts"] if c["field"] == "tool_count")
    assert conflict["live"] == 2 and conflict["profile"] == 1
    assert "Studio uses what the printer reports" in conflict["detail"]


def test_capability_absence_is_read_from_the_live_object_list():
    out = printer_profiles.resolve(voron_facts(), printer_profiles.load("voron_2_4_250"))
    assert out["capabilities"]["exclude_object"]["state"] == printer_profiles.ABSENT
    assert out["capabilities"]["exclude_object"]["source"] == "live"
    assert out["capabilities"]["quad_gantry_level"]["state"] == printer_profiles.PRESENT


def test_without_a_live_list_the_profile_can_only_say_expected():
    """A profile expectation is never reported as a capability."""
    out = printer_profiles.resolve({"reachable": False},
                                   printer_profiles.load("voron_2_4_250"))
    state = out["capabilities"]["exclude_object"]["state"]
    assert state == printer_profiles.NOT_EXPECTED
    assert state not in (printer_profiles.PRESENT, printer_profiles.ABSENT)


# --- Phase 8: material state must not be invented ---------------------------

def test_one_extruder_never_becomes_one_spool():
    """The critical architecture test.

    This printer has an extruder. That says nothing about whether filament is in
    it, and Studio must not turn a tool count into a spool count.
    """
    out = printer_profiles.resolve(voron_facts(), printer_profiles.load("voron_2_4_250"))
    material = out["material_state"]
    assert material["known"] is False
    assert material["slots"] is None
    assert "will not invent slots" in material["detail"]


def test_preflight_reports_loaded_material_as_unknown_not_as_empty():
    project = {"filament_count": {"value": 1, "confidence": "confirmed", "evidence": "t"}}
    out = pf.evaluate(project, voron_facts())
    loaded = next(c for c in out["checks"] if c["id"] == "materials.loaded")
    assert loaded["result"] == pf.UNKNOWN
    assert "does not report which filaments are loaded" in loaded["evidence"]
    # Unknown must not be counted as something to resolve.
    assert loaded not in out["needs_attention"]


def test_material_plan_with_no_printer_filament_state_is_unknown_throughout():
    job = [{"tool": 0, "used": True, "type": "PLA", "color": "#112233", "grams": 40}]
    plan = material_plan.plan(job, loaded=None, tools_used=[0])
    assert plan["printer_known"] is False
    assert plan["slots"][0]["state"] == "unknown"
    assert plan["slots"][0]["has_material"] is None


# --- Phase 7: the existing workflow, unchanged, against this machine --------

def test_preflight_compares_the_project_to_this_printers_real_numbers():
    project = {
        "filament_count": {"value": 3, "confidence": "confirmed", "evidence": "t"},
        "expects_object_exclusion": {"value": True, "confidence": "confirmed", "evidence": "t"},
    }
    out = pf.evaluate(project, voron_facts())
    by_id = {c["id"]: c for c in out["checks"]}

    tools = by_id["materials.toolheads"]
    assert tools["result"] == pf.ATTENTION
    assert "3 filament slot(s); printer reports 1 toolheads" in tools["evidence"]

    exclusion = by_id["capability.exclude_object"]
    assert exclusion["result"] == pf.ATTENTION
    assert "does not list object exclusion" in exclusion["evidence"]

    assert by_id["printer.busy"]["result"] == pf.OK
    assert by_id["nozzle.match"]["result"] == pf.UNKNOWN


def test_bed_check_uses_this_printers_bed_not_the_u1s():
    project = {"filament_count": {"value": 1, "confidence": "confirmed", "evidence": "t"}}
    # the service judges a Voron against ITS recorded printable volume, and says which area that was
    placement = {"available": True, "off_plate": [], "fixable": False, "bed_height_mm": 252.0,
                 "bed": {"min_x": 0.0, "min_y": 0.0, "max_x": 250.0, "max_y": 250.0},
                 "items": [{"object_id": "1", "bounds_mm": {"min": [10, 10, 0], "max": [20, 20, 30]}}]}
    out = pf.evaluate(project, voron_facts(), placement=placement)
    bed = next(c for c in out["checks"] if c["id"] == "bed.fit")
    assert "250 × 250 mm printable area" in bed["evidence"] and "252" in bed["evidence"]
    assert "270" not in bed["evidence"]


def test_firmware_capabilities_describe_this_machine():
    facts = voron_facts()
    out = firmware_caps.interpret(facts["klipper_objects"], facts["toolhead_count"],
                                  facts["bed_mm"])
    names = {f["name"] for f in out["features"]}
    assert "Object exclusion" not in names
    assert "Automatic bed mesh levelling" not in names
    assert "Auto bed probing" in names          # [probe] is declared
    assert not any(n.endswith("toolhead multimaterial") for n in names)
    # An unidentified printer is not given a model name it has not earned.
    assert out["summary"].startswith("This printer reports")
    assert "U1" not in out["summary"]


def test_a_job_sliced_for_this_machine_is_not_called_wrong():
    """The check that was hard-coded to the string "u1".

    A job that correctly names this machine used to be reported as sliced for the
    wrong printer, with an instruction to re-slice it in Snapmaker Orca.
    """
    facts = dict(voron_facts(),
                 identity={"matched": True, "printer_id": "voron_2_4_250",
                           "confidence": "confirmed"})
    job = {"available": True, "printer_model": "Voron 2.4", "tools_used": [0],
           "slots": [{"tool": 0, "type": "PLA"}], "nozzle_diameter_mm": [0.4],
           "bed_mm": {"x": 250.0, "y": 250.0}}
    out = post_slice.analyse(job, facts)
    machine = next(c for c in out["checks"] if c["id"] == "gcode.machine")
    assert machine["result"] == post_slice.OK
    assert "Snapmaker Orca" not in (machine.get("action") or "")


def test_a_u1_job_sent_to_this_machine_is_flagged():
    facts = dict(voron_facts(),
                 identity={"matched": True, "printer_id": "voron_2_4_250",
                           "confidence": "confirmed"})
    job = {"available": True, "printer_model": "Snapmaker U1", "tools_used": [0],
           "slots": [{"tool": 0, "type": "PLA"}]}
    out = post_slice.analyse(job, facts)
    machine = next(c for c in out["checks"] if c["id"] == "gcode.machine")
    assert machine["result"] == post_slice.ATTENTION
    assert "Snapmaker U1" in machine["evidence"]
    assert "VORON 2.4 250" in machine["consequence"]


def test_a_four_tool_job_is_blocked_on_a_one_tool_printer():
    job = {"available": True, "printer_model": "Voron 2.4",
           "tools_used": [0, 1, 2, 3],
           "slots": [{"tool": i, "type": "PLA"} for i in range(4)]}
    out = post_slice.analyse(job, voron_facts())
    tools = next(c for c in out["checks"] if c["id"] == "gcode.tools")
    assert tools["result"] == post_slice.BLOCKED
    assert "this printer reports 1 toolheads" in tools["evidence"]


def test_send_check_stays_useful_when_material_state_is_unknown():
    """Preflight without spool state is still worth reading."""
    job = {"available": True, "printer_model": "Voron 2.4", "tools_used": [0],
           "slots": [{"tool": 0, "type": "PLA", "grams": 30}],
           "nozzle_diameter_mm": [0.4], "size_bytes": 4_000_000}
    out = send_check.evaluate(job, voron_facts())
    assert out["available"] is True
    assert out["verdict"] in (send_check.UNKNOWN, send_check.WARNING)
    # No blocker may be invented from an absence.
    assert out["counts"][send_check.BLOCKER] == 0
    titles = [i["title"] for i in out["items"]]
    assert any("Nozzle" in t for t in titles)
    assert not any("empty" in t.lower() for t in titles)


def test_free_space_evidence_is_not_borrowed_from_the_u1():
    """The U1's storage finding is evidence about a U1, and travels with it."""
    job = {"available": True, "printer_model": "Voron 2.4", "tools_used": [0],
           "slots": [{"tool": 0, "type": "PLA"}], "size_bytes": 9_000_000}
    out = send_check.evaluate(job, voron_facts())
    storage = next(i for i in out["items"] if i["title"] == "Free space on the printer")
    assert "real U1" not in (storage["source"] or "")
    assert storage["kind"] == send_check.UNKNOWN
