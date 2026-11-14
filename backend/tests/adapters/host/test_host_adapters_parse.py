"""Host adapters (stock Moonraker, Paxx Moonraker, OctoPrint): parsers over documentation-derived fixtures.

Evidence label: fixture-tested. No real printer, no network.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from snapstudio_core.adapters import registry
from snapstudio_core.adapters.host import moonraker_parse as mp
from snapstudio_core.adapters.host import moonraker_paxx, moonraker_stock, octoprint
from snapstudio_core.foundation import observations as obs_mod
from snapstudio_core.foundation import topology as topo

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "adapters" / "host"
STOCK, PAXX, OCTO = moonraker_stock.INSTANCE, moonraker_paxx.INSTANCE, octoprint.INSTANCE

S = ("moonraker_stock", "moonraker-0.9")
P = ("moonraker_paxx", "paxx-synthetic-1")
O = ("octoprint", "octoprint-1.9-synthetic")


def load(system: str, version: str, case: str) -> dict:
    return json.loads((FIXTURES / system / version / f"{case}.json").read_text(encoding="utf-8"))


def parse(adapter, doc: dict):
    return adapter.parse(doc["bundle"], received_at=doc["received_at"], source_version=doc["source_version"])


def run(adapter, system: str, version: str, case: str):
    return parse(adapter, load(system, version, case))


def test_registration_and_declared_ttl():
    registry.discover()
    for adapter in (STOCK, PAXX, OCTO):
        assert registry.get(adapter.info.id) is adapter
        assert adapter.info.kind == "host" and adapter.info.ttl_s > 0
    assert {a.info.id for a in registry.all_adapters("host")} >= {
        "host.moonraker_stock", "host.moonraker_paxx", "host.octoprint"}


# plan test 1
def test_thirty_two_logical_entries_never_yield_thirty_two_heads():
    res = run(STOCK, *S, "hypothetical_thirty_two_logical_four_heads")
    assert res.ok
    t = res.topology
    assert len(t.slots) == 32
    assert topo.counts(t)["physical_heads"] == 4 and len(t.heads) == 4 and t.complete

    res = run(STOCK, *S, "hypothetical_thirty_two_logical_no_head_objects")
    t = res.topology
    assert len(t.slots) == 32 and t.heads == [] and not t.complete
    assert topo.counts(t)["physical_heads"] is None
    assert "heads" in res.unknowns


# plan test 2
def test_extruder_map_table_gives_logical_to_physical_bindings_and_absence_is_unknown():
    res = run(STOCK, *S, "crossed_map_table")
    pairs = {(b.slot_id, b.target) for b in res.topology.bindings}
    assert pairs == {("slot:0", "head:3"), ("slot:1", "head:2"), ("slot:2", "head:1"), ("slot:3", "head:0")}
    assert topo.validate(res.topology) == []

    res = run(STOCK, *S, "no_map_table")
    assert res.topology.bindings == [] and all(s.binding is None for s in res.topology.slots)
    assert "bindings" in res.unknowns


def test_map_table_entry_naming_an_unseen_head_stays_unbound():
    doc = load(*S, "four_heads_loaded")
    doc["bundle"]["print_task_config"]["result"]["status"]["print_task_config"]["extruder_map_table"] = [0, 9, "x", True]
    res = parse(STOCK, doc)
    assert [(b.slot_id, b.target) for b in res.topology.bindings] == [("slot:0", "head:0")]
    assert "bindings" in res.unknowns and topo.validate(res.topology) == []


def test_empty_entries_observations_nozzles_and_storage():
    res = run(STOCK, *S, "empty_entries")
    occ = {o.subject["id"]: o.value for o in res.observations if o.field == "occupancy"}
    assert occ == {"head:0": "loaded", "head:1": "empty", "head:2": "loaded", "head:3": "empty"}
    assert not [f for f in res.material_facts if f.observation_id.endswith("head:1:material")]
    first = res.observations[0]
    assert first.ttl_s == STOCK.info.ttl_s
    assert obs_mod.freshness(first, first.received_at)["state"] == obs_mod.FRESH

    res = run(STOCK, *S, "four_heads_loaded")
    assert [h.nozzle_mm for h in res.topology.heads] == [0.4] * 4
    assert any(o.field == "storage_total_bytes" and o.value == 8000000000 for o in res.observations)


def test_stock_never_emits_spool_facts():
    res = run(STOCK, *S, "four_heads_loaded")
    assert not [f for f in res.material_facts if f.field == "spool"]
    assert "spool" in res.unknowns


# plan test 6
def test_paxx_missing_spool_id_is_unknown_not_cleared_or_invented():
    res = run(PAXX, *P, "spool_id_missing")
    assert res.ok
    assert not [f for f in res.material_facts if f.field == "spool"]
    assert not [o for o in res.observations if o.field == "spool"]
    assert "spool" in res.unknowns
    assert any(d.code == "spool_id_missing" for d in res.diagnostics)
    assert [f for f in res.material_facts if f.field == "material"]   # other facts still reported


def test_paxx_spool_ids_become_provider_scoped_refs():
    res = run(PAXX, *P, "spool_ids_present")
    refs = sorted((f.value.provider_instance_id, f.value.provider_spool_id)
                  for f in res.material_facts if f.field == "spool")
    assert refs == [("host.moonraker_paxx", s) for s in ("11", "12", "13", "14")]


def test_paxx_partial_spool_ids_keep_unusable_entries_unknown():
    res = run(PAXX, *P, "spool_ids_partial")
    got = {f.value.provider_spool_id for f in res.material_facts if f.field == "spool"}
    assert got == {"21", "22"}          # None and 0 are not ids, and are not invented
    assert "spool" in res.unknowns
    assert sum(d.code == "spool_id_unusable" for d in res.diagnostics) == 2


# FOUNDATION sec 4
def test_system_info_extracts_only_nozzle_and_storage():
    res = run(PAXX, *P, "system_info_identifiers")
    blob = json.dumps(res.to_dict())
    for leaked in ("SYNTH-NAME-DO-NOT-SURFACE", "SYNTH-SERIAL-0001", "00:00:5E:00:53:01", "192.0.2.10"):
        assert leaked not in blob
    info = mp.machine_info_from(load(*P, "system_info_identifiers")["bundle"]["system_info"])
    assert set(info) == {"nozzle_diameters", "storage_bytes"} and info["storage_bytes"] == 16000000000


def test_machine_info_tolerates_nan_bool_and_zero():
    doc = load(*S, "malformed_arrays")["bundle"]["system_info"]
    assert mp.machine_info_from(doc) == {"nozzle_diameters": None, "storage_bytes": None}
    zero = {"result": {"system_info": {"sd_info": {"total_bytes": 0}}}}
    assert mp.machine_info_from(zero)["storage_bytes"] is None


@pytest.mark.parametrize("case", ["disconnected", "malformed_arrays"])
def test_disconnected_and_malformed_stock_stay_unknown_and_never_raise(case):
    res = run(STOCK, *S, case)
    assert res.errors == []
    t = res.topology
    assert t.heads == [] and not t.complete and t.bindings == []
    assert topo.counts(t)["physical_heads"] is None


def test_disconnected_records_klippy_state_without_inventing_heads():
    res = run(STOCK, *S, "disconnected")
    state = [o for o in res.observations if o.field == "klippy_state"]
    assert state and state[0].value == "disconnected"
    assert any(d.code == "klippy_not_ready" for d in res.diagnostics)


@pytest.mark.parametrize("adapter,where", [(STOCK, S), (PAXX, P), (OCTO, O)])
def test_unknown_source_version_is_all_unknown(adapter, where):
    res = run(adapter, *where, "unknown_version")
    assert not res.ok and res.topology is None and res.observations == [] and res.material_facts == []
    assert res.unknowns == ["all"] and res.errors[0].code == "unknown_source_version"


@pytest.mark.parametrize("payload", ["{not json", b"\xff\xfe", "[]", "7", None, {"server_info": 5}, []])
def test_malformed_payload_never_raises(payload):
    for adapter in (STOCK, PAXX, OCTO):
        res = adapter.parse(payload, received_at="2026-10-26T12:00:00Z", source_version="host_bundle/1")
        assert res.to_decoded() is not None
        if payload != {"server_info": 5}:
            assert res.topology is None and not res.ok


def test_too_many_logical_entries_is_refused_not_truncated():
    doc = load(*S, "four_heads_loaded")
    cfg = doc["bundle"]["print_task_config"]["result"]["status"]["print_task_config"]
    cfg["filament_type"] = ["PLA"] * (mp.MAX_SLOTS + 1)
    res = parse(STOCK, doc)
    assert res.errors and res.errors[0].code == "too_many_slots" and res.topology is None


def test_non_contiguous_toolhead_objects_are_not_a_complete_head_list():
    doc = load(*S, "four_heads_loaded")
    doc["bundle"]["objects_list"] = {"result": {"objects": ["extruder", "extruder2"]}}
    res = parse(STOCK, doc)
    assert not res.topology.complete and topo.counts(res.topology)["physical_heads"] is None


def test_octoprint_parser_reports_unknown_heads_and_slots():
    res = run(OCTO, *O, "version_body")
    assert res.ok and res.topology.heads == [] and not res.topology.complete
    assert {"heads", "slots", "materials"} <= set(res.unknowns)
    assert any(o.field == "octoprint_version" and o.value == "1.9.3" for o in res.observations)


def test_octoprint_adapter_refuses_a_moonraker_body_and_a_stranger():
    assert run(OCTO, *O, "moonraker_compat").errors[0].code == "host_is_moonraker"
    assert run(OCTO, *O, "not_octoprint").errors[0].code == "host_not_octoprint"
    assert run(OCTO, *O, "malformed").errors[0].code == "host_not_octoprint"


def test_extended_firmware_from_pages_is_positive_detection_only():
    page = b"<html>Firmware-Config page</html>"
    assert mp.extended_firmware_from(page, b"other", "firmware-config") == {"detected": True, "known": True}
    assert mp.extended_firmware_from(page, page, "firmware-config") == {"detected": False, "known": False}
    assert mp.extended_firmware_from(None, None, "firmware-config")["known"] is False


# Upstream default shape (u1-klipper blob 340b4232): 4-long filament arrays, 32-long map table.
U = ("moonraker_stock", "u1-klipper-340b4232")


def test_upstream_default_shape_gives_four_slots_and_four_bindings_with_one_beyond_diagnostic():
    res = run(STOCK, *U, "upstream_default_shape")
    assert res.ok
    t = res.topology
    assert len(t.slots) == 4 and len(t.heads) == 4 and t.complete
    assert {(b.slot_id, b.target) for b in t.bindings} == {(f"slot:{i}", f"head:{i}") for i in range(4)}
    beyond = [d for d in res.diagnostics if d.code == "map_entries_beyond_filament_arrays"]
    assert len(beyond) == 1 and beyond[0].field == "extruder_map_table:28"
    assert not [d for d in res.diagnostics if d.code == "map_entry_without_slot"]
    assert "logical_slots_beyond_filament_arrays" in res.unknowns
    assert topo.validate(t) == []


def test_integer_filament_color_alone_leaves_colour_unknown():
    # `filament_color` (integer, ARGB upstream) is deliberately not converted: one colour source.
    doc = load(*U, "upstream_default_shape")
    cfg = doc["bundle"]["print_task_config"]["result"]["status"]["print_task_config"]
    cfg["filament_exist"] = [True] * 4
    cfg["filament_type"] = ["PLA"] * 4
    del cfg["filament_color_rgba"]
    res = parse(STOCK, doc)
    assert not [o for o in res.observations if o.field == "colour"]
    assert [o for o in res.observations if o.field == "material"]


def test_rgba_colour_is_rrggbb_then_alpha():
    doc = load(*U, "upstream_default_shape")
    cfg = doc["bundle"]["print_task_config"]["result"]["status"]["print_task_config"]
    cfg["filament_exist"] = [True] * 4
    cfg["filament_color_rgba"] = ["FF8000CC", "000000FF", "FFFFFFFF", "12345678"]
    res = parse(STOCK, doc)
    colours = {o.subject["id"]: o.value for o in res.observations if o.field == "colour"}
    assert colours == {"head:0": "#FF8000", "head:1": "#000000", "head:2": "#FFFFFF", "head:3": "#123456"}
    # a value whose first six characters are hex but which is not RRGGBB[AA] is not a colour
    for bad in ("FF0000garbage", "FF00", "GG0000FF", "FF0000FFAA"):
        cfg["filament_color_rgba"] = [bad, "000000FF", "FFFFFFFF", "12345678"]
        again = {o.subject["id"]: o.value for o in parse(STOCK, doc).observations if o.field == "colour"}
        assert "head:0" not in again, bad


def test_crossed_map_table_keeps_material_with_its_physical_head_not_the_logical_slot():
    doc = load(*U, "upstream_default_shape")
    cfg = doc["bundle"]["print_task_config"]["result"]["status"]["print_task_config"]
    cfg["filament_exist"] = [True] * 4
    cfg["filament_type"] = ["PLA", "ABS", "ASA", "PETG"]
    cfg["extruder_map_table"] = [3, 2, 1, 0] + [0] * 28
    res = parse(STOCK, doc)
    material = {o.subject["id"]: o.value.split()[0] for o in res.observations if o.field == "material"}
    assert material == {"head:0": "PLA", "head:1": "ABS", "head:2": "ASA", "head:3": "PETG"}
    bound = {b.slot_id: b.target for b in res.topology.bindings}
    assert bound["slot:0"] == "head:3" and bound["slot:3"] == "head:0"      # logical T0 uses physical head 3
    assert not any(o.subject["kind"] == "slot" and o.field in ("material", "occupancy") for o in res.observations)


def test_octoprint_accepts_a_reply_without_an_api_key():
    res = run(OCTO, *O, "version_no_api_key")
    assert res.ok and res.errors == []
    assert any(o.field == "octoprint_version" and o.value == "2.0.0" for o in res.observations)


def test_moonraker_compat_server_is_the_octo_version_constant():
    doc = load(*O, "moonraker_compat")
    assert doc["bundle"]["api_version"]["server"] == "1.5.0"


def _head_subjects(res):
    return {o.subject["id"] for o in res.observations if o.subject.get("kind") == "head"}


def test_no_observation_is_attached_to_a_head_the_topology_does_not_contain():
    res = run(STOCK, *S, "hypothetical_thirty_two_logical_four_heads")
    heads = {h.id for h in res.topology.heads}
    assert len(heads) == 4
    assert _head_subjects(res) <= heads
    assert any(d.code == "observation_head_unknown" for d in res.diagnostics)
    assert "occupancy" in res.unknowns            # entries past the head list have no occupancy answer

    res = run(STOCK, *S, "hypothetical_thirty_two_logical_no_head_objects")
    assert res.topology.heads == []
    assert _head_subjects(res) == set()           # every filament entry would have dangled
    assert any(d.code == "observation_head_unknown" for d in res.diagnostics)


def test_a_normal_four_head_host_gets_no_unknown_head_diagnostic():
    res = parse(
        STOCK, load("moonraker_stock", "u1-klipper-340b4232", "upstream_default_shape"))
    assert not any(d.code == "observation_head_unknown" for d in res.diagnostics)
    assert _head_subjects(res) <= {h.id for h in res.topology.heads}
