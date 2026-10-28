"""Topology reaching the real preparation entry point (convert_to_u1 -> repair -> preserve).

Evidence label: fixture-tested. The projects are synthetic; the topologies are built by hand with the
foundation types, not read from a device. Accessory support stays partial until a production caller
supplies a topology it read from a printer; this proves only that a supplied, valid topology survives
preparation and an invalid one is refused without guessing.
"""
from __future__ import annotations

import copy

import pytest

from snapstudio_core import preserve
from snapstudio_core.convert import convert_to_u1
from snapstudio_core.foundation.topology import (LogicalSlot, PhysicalToolhead, SlotBinding, Topology,
                                                 head_id, slot_id)
from tests.test_project_materials import _cfg, _prepared, _project

VECTORS = sorted(preserve.PER_EXTRUDER_VECTORS)


def project_cfg(n):
    return _cfg(
        filament_settings_id=[f"Generic PLA @BBL H2D"] * n, filament_vendor=["Bambu Lab"] * n,
        filament_colour=[f"#{i:02X}0000" for i in range(n)], filament_type=["PLA"] * n,
        filament_flow_ratio=["1"] * n, enable_pressure_advance=["0"] * n,
        different_settings_to_system=[""] * (n + 2),
        **{key: [f"{key}-{i}" for i in range(n)] for key in VECTORS})


def topology(heads=4, slots=8, complete=True, bind_to=None, extra_binding=None):
    t = Topology(snapshot_id="t", received_at="2026-10-27T10:00:00Z", complete=complete)
    t.heads = [PhysicalToolhead(head_id(i), i, 0.4, []) for i in range(heads)]
    t.slots = [LogicalSlot(slot_id(i), i, None, None) for i in range(slots)]
    t.bindings = [SlotBinding(slot_id(i), bind_to(i) if bind_to else head_id(i % heads), []) for i in range(slots)]
    if extra_binding:
        t.bindings.append(extra_binding)
    return t


def prepare(tmp_path, n, topo, name="p"):
    src = _project(tmp_path, project_cfg(n), name=f"{name}.3mf")
    res = convert_to_u1(str(src), out_dir=str(tmp_path / name), prepare_mode="preserve", topology=topo)
    return res, _prepared(res)


def vectors(prepared):
    return {key: prepared[key] for key in VECTORS}


def test_without_a_topology_the_stock_u1_behaviour_is_unchanged(tmp_path):
    _, out = prepare(tmp_path, 8, None)
    assert all(len(v) == 4 for v in vectors(out).values())
    assert all(v == [f"{k}-{i}" for i in range(4)] for k, v in vectors(out).items())


def test_a_valid_eight_slot_topology_keeps_every_vector_entry_and_mapping(tmp_path):
    original = {k: [f"{k}-{i}" for i in range(8)] for k in VECTORS}
    res, out = prepare(tmp_path, 8, topology())
    assert vectors(out) == original
    assert len(out["filament_colour"]) == 8 and len(out["filament_settings_id"]) == 8


def test_the_dict_form_of_a_valid_topology_is_accepted(tmp_path):
    original = {k: [f"{k}-{i}" for i in range(8)] for k in VECTORS}
    _, out = prepare(tmp_path, 8, topology().to_dict())
    assert vectors(out) == original


def test_a_four_slot_topology_changes_nothing_for_a_four_slot_project(tmp_path):
    original = {k: [f"{k}-{i}" for i in range(4)] for k in VECTORS}
    _, out = prepare(tmp_path, 4, topology(slots=4))
    assert vectors(out) == original


@pytest.mark.parametrize("name,topo", [
    ("binding_to_missing_head", lambda: topology(bind_to=lambda i: head_id(9))),
    ("dangling_binding", lambda: topology(extra_binding=SlotBinding(slot_id(40), head_id(0), []))),
    ("contradictory_binding", lambda: topology(extra_binding=SlotBinding(slot_id(0), head_id(3), []))),
    ("incomplete_head_list", lambda: topology(complete=False)),
    ("no_heads", lambda: topology(heads=0, slots=8, bind_to=lambda i: None)),
    ("slot_gap", lambda: _gap()),
    ("no_slots", lambda: topology(slots=0)),
])
def test_an_invalid_topology_is_refused_and_nothing_is_guessed(tmp_path, name, topo):
    res, out = prepare(tmp_path, 8, topo(), name=name)
    # stock behaviour: the first four entries, in order; no remapped or invented value
    assert all(v == [f"{k}-{i}" for i in range(4)] for k, v in vectors(out).items())
    assert "printer setup was not used" in str(res.to_dict()), "the refusal must reach the person"


def _gap():
    t = topology()
    del t.slots[3]
    t.bindings = [b for b in t.bindings if b.slot_id != slot_id(3)]
    return t


def test_a_rejected_topology_is_reported_in_the_repair_report(tmp_path):
    from snapstudio_core.container import ThreeMF
    from snapstudio_core.repair import repair
    tm = ThreeMF.open(_project(tmp_path, project_cfg(8), name="r.3mf"))
    bad = repair(copy.deepcopy(tm), mode="preserve", dry_run=True, topology=topology(complete=False))
    assert bad.report["topology_used"] is False
    assert any("printer setup was not used" in w and "every physical head" in w for w in bad.report["warnings"])
    good = repair(copy.deepcopy(tm), mode="preserve", dry_run=True, topology=topology())
    assert good.report["topology_used"] is True
    assert not any("printer setup was not used" in w for w in good.report["warnings"])
    assert all(c["category"] == "kept_per_logical" for c in good.report["preserved_value_changes"]
               if c["key"] in preserve.PER_EXTRUDER_VECTORS)


def test_accepted_logical_slots_reasons():
    assert preserve.accepted_logical_slots(None) == (None, None)
    assert preserve.accepted_logical_slots(topology()) == (8, None)
    count, why = preserve.accepted_logical_slots(topology(bind_to=lambda i: head_id(9)))
    assert count is None and "binding_dangling" in why
    count, why = preserve.accepted_logical_slots({"not": "a topology"})
    assert count is None and why
    assert preserve.accepted_logical_slots(object())[0] is None
