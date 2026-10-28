"""Shared builders for the setup-to-prepare tests. Synthetic projects; hand-built topologies."""
from __future__ import annotations

from snapstudio_core.foundation.topology import (LogicalSlot, PhysicalToolhead, SlotBinding, Topology,
                                                 head_id, slot_id)
from tests.test_project_materials import _cfg

# Setting contract (Snapmaker Orca b1831e5, Preset.cpp / PrintConfig.cpp), written out independently of
# the implementation's data file: filament options have one entry per project filament, the printer's
# extruder options one entry per physical head.
FILAMENT_SCOPE = ("nozzle_temperature", "nozzle_temperature_initial_layer",
                  "nozzle_temperature_range_high", "nozzle_temperature_range_low")
HEAD_SCOPE = ("z_hop", "z_hop_types", "z_hop_when_prime")


def project_cfg(filaments: int, heads: int = 4):
    """A project with `filaments` materials and head-addressed settings sized for `heads` heads."""
    cfg = _cfg(
        filament_settings_id=["Generic PLA @BBL H2D"] * filaments, filament_vendor=["Bambu Lab"] * filaments,
        filament_colour=[f"#{i:02X}0000" for i in range(filaments)], filament_type=["PLA"] * filaments,
        filament_flow_ratio=["1"] * filaments, enable_pressure_advance=["0"] * filaments,
        different_settings_to_system=[""] * (filaments + 2))
    for key in FILAMENT_SCOPE:
        cfg[key] = [f"{key}-{i}" for i in range(filaments)]
    for key in HEAD_SCOPE:
        cfg[key] = [f"{key}-{i}" for i in range(heads)]
    return cfg


def topology(heads=4, slots=8, complete=True, bind_to=None, extra_binding=None, unbound=()):
    t = Topology(snapshot_id="t", received_at="2026-10-27T10:00:00Z", complete=complete)
    t.heads = [PhysicalToolhead(head_id(i), i, 0.4, []) for i in range(heads)]
    t.slots = [LogicalSlot(slot_id(i), i, None, None) for i in range(slots)]
    t.bindings = [SlotBinding(slot_id(i), bind_to(i) if bind_to else head_id(i % max(1, heads)), [])
                  for i in range(slots) if i not in unbound]
    if extra_binding:
        t.bindings.append(extra_binding)
    return t
