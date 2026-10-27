"""Real accessory adapter parsing feeding the real topology-aware core. Nothing at the boundary is mocked.

Evidence label: fixture-tested. The payloads are hand-written to the published upstream shapes (see the
PROVENANCE.md files next to them); none is a capture from a device, and no hardware was used.
"""
import copy
import json
from pathlib import Path

import pytest

from snapstudio_core import firmware_caps, preflight
from snapstudio_core.adapters.accessory.afc import ADAPTER as AFC
from snapstudio_core.adapters.accessory.bmcu import ADAPTER as BMCU
from snapstudio_core.adapters.accessory.multiace import ADAPTER as MULTIACE
from snapstudio_core.adapters.accessory.sidecar import ADAPTER as SIDECAR
from snapstudio_core.foundation.topology import Topology, counts

FIXTURES = Path(__file__).parents[1] / "fixtures" / "adapters" / "accessory"
RECEIVED = "2026-10-26T12:01:00Z"
SYSTEMS = {"multiace": (MULTIACE, "1"), "afc": (AFC, "1"), "bmcu": (BMCU, "1"), "sidecar": (SIDECAR, "beta-preview")}
OBJECTS = ["extruder", "extruder1", "extruder2", "extruder3"]
BANNED = ("simultaneous", "guaranteed", "100%")
FAILURES = ("auth_401", "auth_403", "malformed")


def payload(system, case):
    version = SYSTEMS[system][1]
    return json.loads((FIXTURES / system / version / f"{case}.json").read_text(encoding="utf-8"))


def parse(system, body):
    adapter, version = SYSTEMS[system]
    return adapter.parse(body, received_at=RECEIVED, source_version=version)


def printer_for(result):
    """What a caller hands to the core: the host's own head count plus the adapter's topology, if any."""
    printer = {"reachable": True, "toolhead_count": 4}
    if result.topology is not None:
        printer["topology"] = result.topology.to_dict()
    return printer


def materials(n):
    return {"filament_count": {"value": n}}


def fit(system, case, n):
    result = parse(system, payload(system, case))
    return result, preflight._toolheads_vs_filaments(materials(n), printer_for(result))


def no_overclaim(out):
    text = str(out).lower()
    assert not any(word in text for word in BANNED)
    assert "8 physical toolheads" not in text and "8 toolheads" not in text


# --- multiACE: the one adapter whose published payload names every physical head --------------------

def test_multiace_four_heads_four_lanes_serves_four_materials_and_not_eight():
    result, ok = fit("multiace", "normal", 4)
    assert counts(result.topology)["physical_heads"] == 4 and counts(result.topology)["complete"]
    assert ok["result"] == preflight.OK
    assert "4 physical toolheads" in ok["evidence"] and "4 feeder lane" in ok["evidence"]
    _, too_many = fit("multiace", "normal", 8)
    assert too_many["result"] == preflight.ATTENTION
    assert "4 physical toolheads" in too_many["evidence"]
    for out in (ok, too_many):
        no_overclaim(out)


def test_multiace_normal_mode_reports_no_lanes_so_each_material_needs_its_own_head():
    result, ok = fit("multiace", "normal_mode", 4)
    assert counts(result.topology)["lanes"] == 0 and counts(result.topology)["complete"]
    assert ok["result"] == preflight.OK and "its own physical toolhead" in ok["evidence"]
    _, too_many = fit("multiace", "normal_mode", 8)
    assert too_many["result"] == preflight.ATTENTION and "no feeder lanes" in too_many["evidence"]


@pytest.mark.parametrize("case", ["docs_409_manual", "disconnected"])
def test_multiace_without_a_head_list_is_unknown_for_any_project(case):
    for n in (1, 2, 8):
        result, out = fit("multiace", case, n)
        assert not counts(result.topology)["complete"] and counts(result.topology)["physical_heads"] is None
        assert out["result"] == preflight.UNKNOWN, (case, n)
        assert "unknown number of physical toolheads" in out["evidence"]


def test_multiace_manual_head_payloads_keep_reach_per_head():
    reach = {}
    for case in ("code_manual_heads", "docs_example", "head_mode", "derived_omitted"):
        result, out = fit("multiace", case, 2)
        assert counts(result.topology)["complete"], case
        assert out["result"] in (preflight.OK, preflight.ATTENTION), case
        no_overclaim(out)
        reach[case] = {(u.id, ln.index): ln.reachable_heads for u in result.topology.units for ln in u.lanes}
    # head mode sends ace0 to head 2 and ace1 to head 3; a swapped mapping would fail here
    assert reach["head_mode"][("unit:multiace:ace0", 0)] == ["head:2"]
    assert reach["head_mode"][("unit:multiace:ace1", 2)] == ["head:3"]
    # the hand-fed head 2 is taken out of the ACE's reach
    assert reach["code_manual_heads"][("unit:other:manual", 2)] == ["head:2"]
    assert reach["code_manual_heads"][("unit:multiace:ace0", 1)] == ["head:1"]


def test_multiace_dangling_head_reference_is_unknown_in_the_core():
    # In multi mode slot N feeds head N, so a slot 7 on a four-head machine points at a head that is not listed.
    body = payload("multiace", "normal")
    body["body"]["live_slots"].append({"ace": 0, "slot": 7, "material": "PLA", "color": "#ffffff"})
    result = parse("multiace", body)
    dangling = [ln for u in result.topology.units for ln in u.lanes if "head:7" in (ln.reachable_heads or [])]
    assert dangling, "the adapter reports what the payload says; the core must not trust it"
    out = preflight._toolheads_vs_filaments(materials(2), printer_for(result))
    assert out["result"] == preflight.UNKNOWN and "lane_unknown_head" in out["evidence"]
    caps = firmware_caps.interpret(OBJECTS, 4, None, topology=result.topology.to_dict())
    assert not any(f["name"].endswith("toolhead multimaterial") for f in caps["features"])


def test_multiace_partial_nozzle_map_is_not_a_head_inventory():
    partial = payload("multiace", "normal")
    partial["body"]["head_ctx"]["head_nozzles"] = {"0": 0.2, "1": 0.4}       # heads 2 and 3 unreadable
    result = parse("multiace", partial)
    assert not counts(result.topology)["complete"] and counts(result.topology)["physical_heads"] is None
    out = preflight._toolheads_vs_filaments(materials(2), printer_for(result))
    assert out["result"] == preflight.UNKNOWN and "2 physical toolheads" not in out["evidence"]
    caps = firmware_caps.interpret(OBJECTS, 4, None, topology=result.topology.to_dict())
    assert [f["name"] for f in caps["features"]] == ["Multimaterial topology (head count unknown)"]


def test_multiace_contradictory_mapping_never_reads_as_a_fit():
    base = payload("multiace", "normal")
    empty_heads = copy.deepcopy(base)
    empty_heads["body"]["head_ctx"]["head_nozzles"] = {}
    result = parse("multiace", empty_heads)
    assert counts(result.topology)["physical_heads"] is None and not counts(result.topology)["complete"]
    assert preflight._toolheads_vs_filaments(materials(2), printer_for(result))["result"] == preflight.UNKNOWN

    bogus_mode = copy.deepcopy(base)
    bogus_mode["body"]["head_ctx"]["mode"] = "bogus"
    result = parse("multiace", bogus_mode)
    assert result.topology is None and result.unknowns == ["all"]


# --- AFC, BMCU, Sidecar publish no physical head list, so the core must say unknown ---------------------

@pytest.mark.parametrize("system,case", [
    ("afc", "status_colon"), ("afc", "result_envelope"), ("afc", "two_units"), ("afc", "td_empty_string"),
    ("bmcu", "plan_ok"), ("bmcu", "route_config"), ("bmcu", "plan_unrouted_channel"),
    ("sidecar", "gcode_processed"), ("sidecar", "gcode_request"), ("sidecar", "loadcell_ok"),
])
def test_systems_without_a_head_list_are_unknown_and_never_counted_from_lanes(system, case):
    result, out = fit(system, case, 2)
    c = counts(result.topology)
    assert c["physical_heads"] is None and not c["complete"]
    assert out["result"] == preflight.UNKNOWN
    assert "unknown number of physical toolheads" in out["evidence"]
    assert f"{c['lanes']} physical" not in out["evidence"] and f"{c['logical_slots']} physical" not in out["evidence"]
    no_overclaim(out)
    caps = firmware_caps.interpret(OBJECTS, 4, None, topology=result.topology.to_dict())
    names = [feature["name"] for feature in caps["features"]]
    assert "Multimaterial topology (head count unknown)" in names
    assert not any(name.endswith("toolhead multimaterial") for name in names)


# --- firmware capability text from a real adapter result ----------------------------------------------------

def test_firmware_caps_reads_the_multiace_topology():
    result = parse("multiace", payload("multiace", "normal"))
    caps = firmware_caps.interpret(OBJECTS, 4, None, topology=result.topology.to_dict())
    feature = next(f for f in caps["features"] if f["name"].endswith("multimaterial"))
    assert feature["name"] == "4-toolhead multimaterial"
    assert feature["detail"].startswith("4 physical toolheads; 4 feeder lanes reported by ")
    assert "prints up to" not in feature["detail"]


# --- failures: no topology reaches the core, so the host's own count applies ----------------------------------

@pytest.mark.parametrize("system", sorted(SYSTEMS))
@pytest.mark.parametrize("case", FAILURES)
def test_failed_adapter_hands_the_core_no_topology(system, case):
    result = parse(system, payload(system, case))
    assert result.topology is None and result.unknowns == ["all"] and result.errors
    printer = printer_for(result)
    assert "topology" not in printer
    legacy = preflight._toolheads_vs_filaments(materials(8), {"reachable": True, "toolhead_count": 4})
    assert preflight._toolheads_vs_filaments(materials(8), printer) == legacy


@pytest.mark.parametrize("system", sorted(SYSTEMS))
def test_unknown_source_version_is_not_parsed_on_a_guess(system):
    adapter, _ = SYSTEMS[system]
    result = adapter.parse(payload(system, "unknown_source_version"), received_at=RECEIVED, source_version="99")
    assert result.topology is None and result.unknowns == ["all"]


# --- the dict handed to the core is exactly the adapter's document ----------------------------------------------

@pytest.mark.parametrize("system,case", [("multiace", "normal"), ("afc", "two_units"), ("bmcu", "plan_ok"),
                                         ("sidecar", "gcode_processed")])
def test_topology_survives_the_dict_boundary_unchanged(system, case):
    result = parse(system, payload(system, case))
    decoded = Topology.from_dict(result.topology.to_dict())
    assert decoded.value is not None
    assert counts(decoded.value) == counts(result.topology)
    assert decoded.value.to_dict() == result.topology.to_dict()
