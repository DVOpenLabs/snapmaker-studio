"""Shared Moonraker bundle parser. `moonraker_stock` and `moonraker_paxx` subclass it.

Input is a pre-fetched bundle (see README): `server_info`, `objects_list`, `print_task_config`
and `system_info` replies, each optional. Absent or unreadable parts stay unknown; nothing is
defaulted. In particular:

- a head count comes only from toolhead objects in `/printer/objects/list` (`extruder`,
  `extruder1`, ...). `print_task_config` describes logical filament entries and never heads;
- slots come from the filament arrays only (4 on a stock U1, u1-klipper `PHYSICAL_EXTRUDER_NUM`),
  never from the 32-long `extruder_map_table`;
- entries bind to physical heads only through `extruder_map_table`. Without it the
  bindings are unknown; identity is never assumed.
"""
from __future__ import annotations

from typing import Any

from ...foundation import topology as topo
from ...foundation.decode import ERROR, NOTE, WARNING, diag
from ...foundation.materials import MaterialFact
from ...foundation.observations import parse_time, to_iso
from ..base import Adapter, AdapterResult
from . import moonraker_parse as mp

HOST_SUBJECT = {"kind": "host", "id": "host:moonraker"}


class MoonrakerBundleAdapter(Adapter):
    """Not registered itself; subclasses declare `info`."""

    # -- hooks ---------------------------------------------------------------
    def _spool_pass(self, cfg: dict, count: int, ctx: "_Ctx") -> None:
        """Stock firmware names no spool identity: every slot's spool stays unknown."""
        if count:
            ctx.result.unknowns.append("spool")

    # -- parse ---------------------------------------------------------------
    def _parse(self, data: Any, received_at: Any, result: AdapterResult) -> None:
        if not isinstance(data, dict):
            result.errors.append(diag("bundle_not_object", "", ERROR))
            return
        stamp = parse_time(received_at)
        received_iso = to_iso(stamp.timestamp()) if stamp is not None else "invalid"
        if stamp is None:
            result.diagnostics.append(diag("received_at_unreadable", "received_at", WARNING))
        snapshot = mp.snapshot_id_of(data)
        ctx = _Ctx(self, result, snapshot, received_at)

        server = mp.result_of(data.get("server_info"))
        version = server.get("moonraker_version")
        if isinstance(version, str) and version.strip():
            ctx.observe(HOST_SUBJECT, "service", "moonraker")
            ctx.observe(HOST_SUBJECT, "moonraker_version", version.strip()[:64])
        else:
            result.unknowns.append("host_identity")
        state = server.get("klippy_state")
        if isinstance(state, str) and state.strip():
            ctx.observe(HOST_SUBJECT, "klippy_state", state.strip()[:32])
            if state.strip().lower() != "ready":
                result.diagnostics.append(diag("klippy_not_ready", "server_info", WARNING))
        elif server.get("klippy_connected") is False:
            ctx.observe(HOST_SUBJECT, "klippy_state", "disconnected")
            result.diagnostics.append(diag("klippy_not_ready", "server_info", WARNING))
        else:
            result.unknowns.append("klippy_state")

        # Heads: toolhead objects only.
        indices = mp.toolhead_indices(data.get("objects_list"))
        machine = mp.machine_info_from(data.get("system_info")) if "system_info" in data else None
        diameters = machine["nozzle_diameters"] if machine else None
        heads = []
        complete = False
        if indices is None:
            result.unknowns.append("heads")
        else:
            for i in indices:
                nozzle = diameters[i] if diameters is not None and i < len(diameters) else None
                heads.append(topo.PhysicalToolhead(topo.head_id(i), i, nozzle, ["objects_list"]))
            complete = mp.contiguous_from_zero(indices)
            if not complete:
                result.unknowns.append("heads")
                if indices:
                    result.diagnostics.append(diag("toolhead_objects_not_contiguous", "objects_list", WARNING))
        for head in heads:
            if head.nozzle_mm is not None:
                ctx.observe({"kind": "head", "id": head.id}, "nozzle_mm", head.nozzle_mm)
        if machine is not None:
            if machine["storage_bytes"] is not None:
                ctx.observe(HOST_SUBJECT, "storage_total_bytes", machine["storage_bytes"])
            if diameters is None:
                result.unknowns.append("nozzle_diameter")

        # Logical entries.
        cfg = mp.print_task_config(data.get("print_task_config"))
        status = mp.status_of(data.get("print_task_config"))
        entries = mp.loaded_filaments_from(cfg) if cfg is not None else []
        if cfg is None:
            result.unknowns.append("slots")
        if len(entries) > mp.MAX_SLOTS:
            result.errors.append(diag("too_many_slots", "print_task_config", ERROR))
            return
        slots = []
        for i, entry in enumerate(entries):
            sid = topo.slot_id(i)
            slots.append(topo.LogicalSlot(sid, i))
            # The filament arrays are indexed by physical extruder (u1_print_task_config.py lines 8-9
            # and 25-45), while extruder_map_table maps logical T entries to those extruders. Material
            # facts therefore belong to the physical head at that index, never to logical slot i.
            subject = {"kind": "head", "id": topo.head_id(i)}
            if entry["present"] is False:
                ctx.observe(subject, "occupancy", "empty")
                continue
            if entry["present"] is True:
                ctx.observe(subject, "occupancy", "loaded")
            elif "occupancy" not in result.unknowns:
                result.unknowns.append("occupancy")
            for fld, key, mfield in (("material", "material", "material"),
                                     ("colour", "colour", "colour"),
                                     ("brand", "vendor", "brand")):
                if entry[key] is not None:
                    obs = ctx.observe(subject, fld, entry[key])
                    result.material_facts.append(MaterialFact(mfield, entry[key], "provider", obs.observation_id))

        # Bindings: extruder_map_table only.
        bindings = []
        table = mp.extruder_map(cfg or {}, status) if cfg is not None else None
        head_ids = {h.id for h in heads}
        if table is None:
            if entries:
                result.unknowns.append("bindings")
        else:
            result.diagnostics.append(topo.index_base_diagnostic("gcode_t"))
            beyond = max(0, len(table) - len(slots))
            if beyond:
                # Stock u1-klipper reports a 32-long map table next to 4-long filament arrays
                # (blob 340b4232, lines 8-9 and 40). Entries past the filament arrays describe no
                # slot Studio can see: ONE diagnostic carrying the count, and the slot count stays
                # unknown. 32 logical slots are never claimed from the map table alone.
                result.diagnostics.append(
                    diag("map_entries_beyond_filament_arrays", f"extruder_map_table:{beyond}", WARNING))
                result.unknowns.append("logical_slots_beyond_filament_arrays")
            for i, raw in enumerate(table):
                if i >= len(slots):
                    break
                m = topo.normalise_index("gcode_t", raw)
                target = topo.head_id(m) if m is not None else None
                if target is None or target not in head_ids:
                    # A table entry naming a head Studio cannot see stays unknown, never guessed.
                    result.diagnostics.append(diag("binding_target_unknown", f"extruder_map_table[{i}]", WARNING))
                    if "bindings" not in result.unknowns:
                        result.unknowns.append("bindings")
                    continue
                bindings.append(topo.SlotBinding(slots[i].id, target, ["extruder_map_table"]))
                slots[i].binding = target
            if len(table) < len(slots) and "bindings" not in result.unknowns:
                result.unknowns.append("bindings")

        if cfg is not None:
            self._spool_pass(cfg, len(entries), ctx)

        result.topology = topo.Topology(
            snapshot_id=snapshot, received_at=received_iso, heads=heads, slots=slots,
            bindings=bindings, complete=complete,
            evidence=["objects_list"] if indices is not None else [],
            diagnostics=[d for d in result.diagnostics if d.severity == NOTE or d.code == "klippy_not_ready"])


class _Ctx:
    """Per-parse state handed to hooks."""

    def __init__(self, adapter: Adapter, result: AdapterResult, snapshot: str, received_at: Any) -> None:
        self.adapter = adapter
        self.result = result
        self.snapshot = snapshot
        self.received_at = received_at

    def observe(self, subject: dict, field: str, value: Any):
        return self.adapter.observe(
            self.result, observation_id=f"{self.adapter.info.id}:{self.snapshot}:{subject['id']}:{field}",
            subject=subject, field=field, value=value, snapshot_id=self.snapshot,
            received_at=self.received_at)
