"""Behaviour of the accessory parsers on upstream-shaped fixtures (fixture-tested, not hardware-verified)."""
import json
from pathlib import Path

import pytest

from snapstudio_core.adapters.accessory.afc import ADAPTER as AFC
from snapstudio_core.adapters.accessory.bmcu import ADAPTER as BMCU
from snapstudio_core.adapters.accessory.multiace import ADAPTER as MULTIACE
from snapstudio_core.adapters.accessory.sidecar import ADAPTER as SIDECAR
from snapstudio_core.foundation.materials import SpoolRef
from snapstudio_core.foundation.topology import (
    ProjectSlotRequirement, ResourceConstraints, assignability, counts,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "adapters" / "accessory"
RECEIVED = "2026-10-26T12:01:00Z"
SYSTEMS = {"multiace": (MULTIACE, "1"), "afc": (AFC, "1"), "bmcu": (BMCU, "1"), "sidecar": (SIDECAR, "beta-preview")}
ALL = [(a, s, v) for s, (a, v) in SYSTEMS.items()]


def load(system, case):
    return json.loads((FIXTURES / system / SYSTEMS[system][1] / f"{case}.json").read_text(encoding="utf-8"))


def run(system, case):
    adapter, version = SYSTEMS[system]
    return adapter.parse(load(system, case), received_at=RECEIVED, source_version=version)


def codes(items):
    return [d.code for d in items]


def lanes_by(result):
    return {(u.id, ln.index): ln for u in result.topology.units for ln in u.lanes}


# -- (e) unknown version / malformed ------------------------------------------------------------
@pytest.mark.parametrize("adapter,system,version", ALL)
def test_accessory_unknown_source_version_is_all_unknown(adapter, system, version):
    result = adapter.parse(load(system, "unknown_source_version"), received_at=RECEIVED, source_version="99")
    assert result.topology is None and not result.observations and not result.material_facts
    assert result.unknowns == ["all"]
    assert "unknown_source_version" in codes(result.errors)


@pytest.mark.parametrize("adapter,system,version", ALL)
def test_accessory_malformed_json_text_is_all_unknown(adapter, system, version):
    result = adapter.parse('{"body":', received_at=RECEIVED, source_version=version)
    assert result.topology is None and result.unknowns == ["all"] and result.errors


@pytest.mark.parametrize("adapter,system,version", ALL)
def test_accessory_malformed_fixture_returns_error_without_topology(adapter, system, version):
    result = run(system, "malformed")
    assert result.topology is None and result.unknowns == ["all"] and result.errors


# -- (g) auth failures --------------------------------------------------------------------------
@pytest.mark.parametrize("adapter,system,version", ALL)
@pytest.mark.parametrize("case", ["auth_401", "auth_403"])
def test_accessory_auth_failure_is_unavailable_and_keeps_nothing(adapter, system, version, case):
    result = run(system, case)
    assert "unavailable" in codes(result.errors)
    rendered = json.dumps(result.to_dict()).lower()
    assert "discard-me" not in rendered and "retry" not in rendered
    assert result.topology is None and result.unknowns == ["all"]


# -- (a) multiACE ---------------------------------------------------------------------------------
def test_accessory_multiace_docs_409_means_heads_unknown_not_four():
    result = run("multiace", "docs_409_manual")
    assert result.ok and result.topology.heads == [] and result.topology.complete is False
    assert {"heads", "lanes", "manual_heads"} <= set(result.unknowns)
    assert "assignment_unavailable_manual_head" in codes(result.diagnostics)
    assert counts(result.topology)["physical_heads"] is None and not result.observations


def test_accessory_multiace_head_nozzles_fill_heads_and_wire_indices_are_not_shifted():
    result = run("multiace", "normal")
    assert [(h.index, h.nozzle_mm) for h in result.topology.heads] == [(0, 0.2), (1, 0.4), (2, 0.6), (3, 0.8)]
    assert result.topology.complete is True
    lanes = lanes_by(result)
    assert lanes[("unit:multiace:ace0", 1)].state == "loaded"
    assert lanes[("unit:multiace:ace0", 1)].reachable_heads == ["head:1"]
    assert lanes[("unit:multiace:ace1", 0)].reachable_heads == ["head:0"]
    assert lanes[("unit:multiace:ace0", 3)].state == "empty"
    assert "index_base_source" in codes(result.diagnostics)
    assert "nozzle_type:high_flow" in result.topology.heads[2].evidence


def test_accessory_multiace_missing_nozzle_types_stay_unknown():
    result = run("multiace", "docs_example")
    assert "nozzle_types_unknown" in codes(result.diagnostics)
    assert all(not h.evidence for h in result.topology.heads)


def test_accessory_multiace_code_manual_heads_are_pinned_not_reachable_from_ace_slots():
    result = run("multiace", "code_manual_heads")
    lanes = lanes_by(result)
    manual = lanes[("unit:other:manual", 2)]
    assert manual.state == "uncertain" and manual.reachable_heads == ["head:2"]
    payload = load("multiace", "code_manual_heads")
    payload["body"]["live_slots"].append({"ace": 1, "slot": 2, "material": "PLA", "color": "#111111"})
    again = MULTIACE.parse(payload, received_at=RECEIVED, source_version="1")
    assert lanes_by(again)[("unit:multiace:ace1", 2)].reachable_heads == []


def test_accessory_multiace_head_mode_uses_head_ace_direction():
    lanes = lanes_by(run("multiace", "head_mode"))
    assert lanes[("unit:multiace:ace0", 0)].reachable_heads == ["head:2"]
    assert lanes[("unit:multiace:ace1", 2)].reachable_heads == ["head:3"]
    assert lanes[("unit:stock:feeder", 0)].state == "loaded"


def test_accessory_multiace_normal_mode_has_no_lanes():
    result = run("multiace", "normal_mode")
    assert result.topology.lanes() == [] and "lanes" in result.unknowns
    assert "multiace_not_driving_feed" in codes(result.diagnostics)


def test_accessory_multiace_omitted_slots_are_not_reported_empty():
    result = run("multiace", "derived_omitted")
    assert [(ln.index, ln.state) for ln in result.topology.lanes()] == [(0, "loaded")]


def test_accessory_multiace_disconnected_is_unknown_never_empty():
    result = run("multiace", "disconnected")
    assert result.topology.heads == [] and "heads" in result.unknowns
    assert all(ln.state != "empty" for ln in result.topology.lanes())


def test_accessory_multiace_head_count_never_comes_from_slot_count():
    payload = load("multiace", "disconnected")
    payload["body"]["live_slots"] = [{"ace": a, "slot": s, "material": "PLA", "color": "#000000"}
                                     for a in (0, 1) for s in range(4)]
    result = MULTIACE.parse(payload, received_at=RECEIVED, source_version="1")
    assert len(result.topology.lanes()) == 8 and result.topology.heads == []
    assert counts(result.topology)["physical_heads"] is None


def test_accessory_multiace_identity_facts_are_provider_provenance_with_ttl():
    result = run("multiace", "normal")
    assert {f.provenance for f in result.material_facts} == {"provider"}
    assert {f.field for f in result.material_facts} == {"material", "colour"}
    assert all(o.ttl_s == MULTIACE.info.ttl_s for o in result.observations)


# -- (b) AFC --------------------------------------------------------------------------------------
@pytest.mark.parametrize("case", ["status_colon", "status_plain", "result_envelope"])
def test_accessory_afc_accepts_wrapper_forms(case):
    result = run("afc", case)
    assert result.ok
    assert [(ln.index, ln.state) for ln in result.topology.lanes()] == [(0, "loaded"), (1, "empty")]


def test_accessory_afc_lane_head_comes_from_extruder_name_and_unknown_otherwise():
    lanes = lanes_by(run("afc", "status_colon"))
    assert lanes[("unit:afc:Turtle_1", 0)].reachable_heads == ["head:0"]
    assert lanes[("unit:afc:Turtle_1", 1)].reachable_heads == ["head:1"]
    two = lanes_by(run("afc", "two_units"))
    assert two[("unit:afc:Turtle_2", 0)].reachable_heads is None


def test_accessory_afc_heads_are_not_complete_and_nozzles_unknown():
    topology = run("afc", "status_colon").topology
    assert [(h.index, h.nozzle_mm) for h in topology.heads] == [(0, None), (1, None)]
    assert topology.complete is False and counts(topology)["physical_heads"] is None


def test_accessory_afc_weight_td_spool_are_provider_facts_with_ttl():
    result = run("afc", "status_colon")
    facts = {(f.field, str(f.value) if f.field == "spool" else f.value): f for f in result.material_facts}
    assert ("remaining_g", 612.5) in facts and ("td", 0.98) in facts
    assert any(isinstance(f.value, SpoolRef) and f.value.provider_spool_id == "42" for f in result.material_facts)
    assert {f.provenance for f in result.material_facts} == {"provider"}
    assert all(o.ttl_s == AFC.info.ttl_s for o in result.observations)
    assert "afc_runout_lane_declared" in codes(result.diagnostics)


def test_accessory_afc_empty_td_string_and_unconnected_lane_stay_unknown():
    assert not [f for f in run("afc", "td_empty_string").material_facts if f.field == "td"]
    lane = run("afc", "lane_not_connected").topology.lanes()[0]
    assert lane.state == "unknown"
    assert all(ln.state == "unknown" for ln in run("afc", "disconnected").topology.lanes())


# -- (c) BMCU -------------------------------------------------------------------------------------
def test_accessory_bmcu_routes_states_and_bindings_from_published_text():
    result = run("bmcu", "plan_ok")
    lanes = lanes_by(result)
    assert lanes[("unit:bmcu:bmcu0", 0)].reachable_heads == ["head:0"] and lanes[("unit:bmcu:bmcu0", 0)].state == "loaded"
    assert lanes[("unit:bmcu:bmcu0", 1)].reachable_heads == ["head:1"] and lanes[("unit:bmcu:bmcu0", 1)].state == "unknown"
    assert lanes[("unit:bmcu:bmcu0", 2)].reachable_heads == []
    assert [(b.slot_id, b.target) for b in result.topology.bindings] == [("slot:5", "lane:unit:bmcu:bmcu0:1")]
    assert {"shared_path_group", "native_u1_source", "index_base_source"} <= set(codes(result.diagnostics))
    assert "plan_not_committed" not in codes(result.diagnostics)
    assert {(f.field, f.value, f.provenance) for f in result.material_facts} == {
        ("material", "PLA", "project"), ("colour", "#ff0000", "project")}


def test_accessory_bmcu_channel_without_route_is_unknown_reach():
    lane = lanes_by(run("bmcu", "plan_unrouted_channel"))[("unit:bmcu:bmcu0", 1)]
    assert lane.reachable_heads is None and lane.state == "unknown"


def test_accessory_bmcu_required_tool_without_source_is_reported():
    result = run("bmcu", "plan_unmapped_required")
    assert "required_tool_unmapped" in codes(result.diagnostics) and "source:T5" in result.unknowns


def test_accessory_bmcu_unsupported_plan_schema_is_an_error():
    result = run("bmcu", "plan_schema2")
    assert "unsupported_plan_schema" in codes(result.errors) and result.topology is None


def test_accessory_bmcu_unresolved_slicer_placeholders_are_not_facts():
    result = run("bmcu", "plan_placeholder")
    assert result.material_facts == [] and "plan_placeholder_unresolved" in codes(result.diagnostics)


def test_accessory_bmcu_transport_status_gives_online_only_and_channels_unknown():
    result = run("bmcu", "transport_status_ok")
    assert [(o.field, o.value) for o in result.observations] == [("online", True)]
    assert result.observations[0].observed_at != RECEIVED
    assert {"channels", "routes"} <= set(result.unknowns)
    assert "device_status_shape_not_published" in codes(result.diagnostics)


def test_accessory_bmcu_offline_device_reports_error_note_and_no_empty_lane():
    result = run("bmcu", "disconnected")
    assert result.observations[0].value is False and "panel_reported_error" in codes(result.diagnostics)
    assert result.topology.lanes() == []


# -- (d) Sidecar ----------------------------------------------------------------------------------
def test_accessory_sidecar_maps_t_only_when_marker_present():
    result = run("sidecar", "gcode_processed")
    lanes = lanes_by(result)
    assert lanes[("unit:sidecar:head0", 0)].reachable_heads == ["head:0"]
    first_aux = lanes[("unit:sidecar:head1", 0)]
    assert first_aux.reachable_heads == ["head:1"] and first_aux.display_index == 1
    assert lanes[("unit:sidecar:head1", 1)].display_index == 2
    assert lanes[("unit:sidecar:head3", 1)].reachable_heads == ["head:3"]
    assert result.topology.complete is False and "sidecar_beta_unverified_on_hardware" in codes(result.diagnostics)
    assert {b.slot_id for b in result.topology.bindings} == {"slot:0", "slot:4", "slot:5", "slot:13"}
    assert run("sidecar", "gcode_request").ok


def test_accessory_sidecar_untagged_gcode_invents_no_mapping():
    result = run("sidecar", "gcode_untagged")
    assert result.topology.units == [] and result.topology.heads == [] and {"tools", "lanes"} <= set(result.unknowns)


def test_accessory_sidecar_blocked_marker_is_a_warning_with_sanitised_reason():
    result = run("sidecar", "gcode_blocked")
    blocked = [d for d in result.diagnostics if d.code == "sidecar_blocked"]
    assert blocked and blocked[0].field == "no lane map"


def test_accessory_sidecar_loadcell_force_is_observation_not_remaining_mass():
    result = run("sidecar", "loadcell_ok")
    assert sorted(o.field for o in result.observations) == ["net_g"] * 4 + ["raw_g"] * 4     # four lanes, two fields
    assert result.material_facts == [] and "loadcell_force_is_not_remaining_mass" in codes(result.diagnostics)
    assert all(ln.reachable_heads is None and ln.state == "unknown" for ln in result.topology.lanes())


def test_accessory_sidecar_failed_reply_is_unavailable_and_unpublished_bodies_are_unknown():
    assert "unavailable" in codes(run("sidecar", "disconnected").errors)
    for case in ("state_body_unpublished", "lane_meta_unpublished"):
        result = run("sidecar", case)
        assert "body_shape_not_published" in codes(result.diagnostics)
        assert result.topology.heads == [] and {"heads", "lanes", "materials"} <= set(result.unknowns)


# -- (f) observations -----------------------------------------------------------------------------
@pytest.mark.parametrize("system,case", [("multiace", "normal"), ("afc", "status_colon"),
                                         ("bmcu", "plan_ok"), ("sidecar", "gcode_processed")])
def test_accessory_observations_fall_back_to_receipt_time_with_diagnostic_and_ttl(system, case):
    result = run("sidecar" if system == "sidecar" else system, case)
    adapter = SYSTEMS[system][0]
    assert result.observations
    assert all(o.observed_at == RECEIVED and o.ttl_s == adapter.info.ttl_s for o in result.observations)
    assert "observed_at_is_receipt_time" in codes(result.diagnostics)


# -- (h) cross-adapter topology ---------------------------------------------------------------------
def _four_head_text(route_to):
    lines = [f"BMCU_SET_ENDPOINT NAME=e{i} DRIVER=snapmaker_u1 EXTRUDER={'extruder' if i == 0 else f'extruder{i}'}"
             for i in range(4)]
    # Eight lanes are two devices of four channels each (CHANNEL is 0..3 on one device).
    lines += [f"BMCU_SET_ROUTE DEVICE=bmcu{c // 4} CHANNEL={c % 4} ENDPOINT={route_to(c)}" for c in range(8)]
    lines += ["BMCU_PRINT_BEGIN SCHEMA=1 RESET=1", "BMCU_MAP_TOOL TOOL=4 DEVICE=bmcu0 CHANNEL=0",
              "BMCU_MAP_TOOL TOOL=5 DEVICE=bmcu1 CHANNEL=0", "BMCU_PRINT_COMMIT"]
    return {"http_status": 200, "body": {"kind": "klipper_text", "text": "\n".join(lines)}}


def test_accessory_four_heads_eight_lanes_two_lanes_competing_for_one_head():
    result = BMCU.parse(_four_head_text(lambda c: f"e{c % 4}"), received_at=RECEIVED, source_version="1")
    assert len(result.topology.heads) == 4 and len(result.topology.lanes()) == 8
    answer = assignability(result.topology, [ProjectSlotRequirement(4), ProjectSlotRequirement(5)],
                           ResourceConstraints(heads_single_active=True))
    assert [row["result"] for row in answer["per_requirement"]] == ["contended", "contended"]
    assert answer["assignable"] is not True


def test_accessory_unreachable_lane_does_not_block_other_requirements():
    result = BMCU.parse(_four_head_text(lambda c: "NONE" if c == 4 else f"e{c % 4}"), received_at=RECEIVED,
                        source_version="1")
    unreachable = lanes_by(result)[("unit:bmcu:bmcu1", 0)]
    assert unreachable.reachable_heads == []
    answer = assignability(result.topology, [ProjectSlotRequirement(4)])
    assert unreachable.id not in answer["per_requirement"][0]["candidates"]


def _bmcu_text(*lines):
    return {"http_status": 200, "body": {"kind": "klipper_text", "text": "\n".join(lines)}}


def test_accessory_bmcu_values_outside_the_contract_are_rejected_not_accepted():
    endpoint = "BMCU_SET_ENDPOINT NAME=main DRIVER=snapmaker_u1 EXTRUDER=extruder"
    for bad in ("BMCU_ROUTE_CONFIRM DEVICE=bmcu0 CHANNEL=0 STATE=UNCERTAIN",     # not EMPTY|PARKED|LOADED
                "BMCU_SET_ROUTE DEVICE=bmcu0 CHANNEL=4 ENDPOINT=main",             # CHANNEL is 0..3
                "BMCU_ROUTE_CONFIRM DEVICE=bmcu0 CHANNEL=7 STATE=LOADED",
                "BMCU_MAP_TOOL TOOL=4 DEVICE=bmcu0 CHANNEL=0",                     # alias needs an open plan
                "BMCU_PRINT_MAP TOOL=4 DEVICE=bmcu0 CHANNEL=0 MATERIAL=PLA"):      # so does the command itself
        result = BMCU.parse(_bmcu_text(endpoint, bad), received_at=RECEIVED, source_version="1")
        assert result.topology is None and result.unknowns == ["all"] and result.errors, bad
    for spelling in ("BMCU_MAP_TOOL", "BMCU_PRINT_MAP"):
        closed = _bmcu_text("BMCU_PRINT_BEGIN SCHEMA=1 RESET=1", "BMCU_PRINT_COMMIT",
                            f"{spelling} TOOL=4 DEVICE=bmcu0 CHANNEL=0")
        assert BMCU.parse(closed, received_at=RECEIVED, source_version="1").topology is None, spelling
        inside = _bmcu_text("BMCU_PRINT_BEGIN SCHEMA=1 RESET=1", f"{spelling} TOOL=4 DEVICE=bmcu0 CHANNEL=0",
                            "BMCU_PRINT_COMMIT")
        assert BMCU.parse(inside, received_at=RECEIVED, source_version="1").topology is not None, spelling
    ok = _bmcu_text(endpoint, "BMCU_SET_ROUTE DEVICE=bmcu0 CHANNEL=3 ENDPOINT=main",
                    "BMCU_ROUTE_CONFIRM DEVICE=bmcu0 CHANNEL=3 STATE=PARKED")
    assert BMCU.parse(ok, received_at=RECEIVED, source_version="1").topology is not None


def test_accessory_multiace_partial_head_map_leaves_the_head_count_unknown():
    body = load("multiace", "normal")
    body["body"]["head_ctx"]["head_nozzles"] = {"0": 0.2}          # the other heads' diameters were unreadable
    result = MULTIACE.parse(body, received_at=RECEIVED, source_version="1")
    assert not counts(result.topology)["complete"] and counts(result.topology)["physical_heads"] is None
    assert "head_list_may_be_partial" in codes(result.diagnostics) and "heads" in result.unknowns
    full = MULTIACE.parse(load("multiace", "normal"), received_at=RECEIVED, source_version="1")
    assert counts(full.topology)["complete"] and counts(full.topology)["physical_heads"] == 4


def test_accessory_sidecar_loadcell_unit_is_studio_context_not_a_reply_key():
    published = load("sidecar", "loadcell_ok")
    assert "unit" not in published["body"]["body"]                 # the reply is {ok, lanes}
    stated = SIDECAR.parse(published, received_at=RECEIVED, source_version="beta-preview")
    assert {u.id for u in stated.topology.units} == {"unit:sidecar:unit2"}
    assert len(stated.topology.lanes()) == 4
    del published["body"]["unit"]
    unstated = SIDECAR.parse(published, received_at=RECEIVED, source_version="beta-preview")
    assert {u.id for u in unstated.topology.units} == {"unit:sidecar:unit_unstated"}
    assert "loadcell_unit_not_stated" in codes(unstated.diagnostics)


def test_accessory_afc_default_zero_weight_is_not_a_remaining_mass_reading():
    result = run("afc", "status_colon")
    remaining = [f for f in result.material_facts if f.field == "remaining_g"]
    assert [f.value for f in remaining] == [612.5]          # the lane that publishes weight 0 adds nothing


# -- (i) isolation ----------------------------------------------------------------------------------
def test_accessory_parsers_are_network_free_and_never_count_heads_from_lanes():
    source = Path(__file__).parents[3] / "snapstudio_core" / "adapters" / "accessory"
    text = "\n".join(path.read_text(encoding="utf-8") for path in source.glob("*.py"))
    for forbidden in ("netguard", "import socket", "urllib", "requests", "slot_count", "len(nozzles)",
                      "snapstudio_core.moonraker", "simultaneous", "guaranteed", "100%"):
        assert forbidden not in text
