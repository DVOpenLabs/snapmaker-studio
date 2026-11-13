"""AFC-Klipper-Add-On status parser: GET /printer/afc/status (Moonraker webhook).

Contract (AFCProject/AFC-Klipper-Add-On): extras/AFC.py blob 9553d159 `_webhooks_status`
lines 2572-2612 sends the literal key "status:" (trailing colon) wrapping {"AFC": {...}};
extras/AFC_lane.py blob f6b98e2c `get_status` lines 2183-2235 and `AFCLaneState` lines 65-76.
Unit entries are every key except "system"; a lane that has not finished connecting reports {}.
"""
from __future__ import annotations

from ..base import Adapter, AdapterInfo
from ..registry import register
from ...foundation.decode import NOTE, diag
from ...foundation.materials import MaterialFact, SpoolRef
from ...foundation.topology import Lane, lane_id, unit_id
from ._common import (build_topology, head_from_extruder, invalid, is_index, is_num, observe_lane_states,
                      safe_name, unit_of, unwrap)

# AFCLaneState strings (afc_lane.py lines 65-76) that mean filament is present in the lane.
PRESENT = {"Loaded", "Tooled", "Tool Loaded", "Infinite Runout"}
TRANSITIONAL = {"Error", "Tool Loading", "Tool Unloading", "HUB Loading", "Ejecting", "Calibrating"}


def lane_state(lane: dict) -> str:
    """Only fields AFC publishes decide this; anything else is unknown, never empty."""
    if not lane:
        return "unknown"
    status = lane.get("status")
    if status in PRESENT or lane.get("tool_loaded") is True:
        return "loaded"
    if status in TRANSITIONAL:
        return "uncertain"
    if lane.get("prep") is True:
        return "loaded"
    if status == "None" and lane.get("prep") is False and lane.get("load") is False:
        return "empty"
    return "unknown"


class AFCAdapter(Adapter):
    info = AdapterInfo("afc", "accessory", ("1",), 300.0)

    def _parse(self, payload, received_at, result):
        body, _ = unwrap(payload, result)
        if body is None:
            return
        if isinstance(body, dict) and isinstance(body.get("result"), dict):
            body = body["result"]           # Moonraker's own envelope around a webhook reply
        if not isinstance(body, dict):
            invalid(result)
            return
        wrapper = body.get("status:", body.get("status"))
        afc = wrapper.get("AFC") if isinstance(wrapper, dict) else None
        if not isinstance(afc, dict) or not isinstance(afc.get("system"), dict):
            invalid(result, "status:.AFC")
            return
        system = afc["system"]
        extruders = system.get("extruders", {})
        if not isinstance(extruders, dict):
            invalid(result, "system.extruders")
            return
        head_indexes = sorted({h for h in map(head_from_extruder, extruders) if h is not None})
        if extruders and not head_indexes:
            result.unknowns.append("heads")

        units, used, rows = [], set(), []
        for name, entry in afc.items():
            if name == "system":
                continue
            if not isinstance(entry, dict) or not isinstance(entry.get("system"), dict):
                invalid(result, "unit")
                return
            uname = safe_name(name)
            while uname in used:
                uname += "_"
            used.add(uname)
            uid = unit_id("afc", uname)
            lanes = []
            names = [k for k in entry if k != "system"]
            for position, lane_name in enumerate(names):
                raw = entry[lane_name]
                if not isinstance(raw, dict):
                    invalid(result, "lane")
                    return
                head = head_from_extruder(raw.get("extruder"))
                reach = [f"head:{head}"] if head is not None else None
                state = lane_state(raw)
                lane = Lane(lane_id(uid, position), uid, position, reachable_heads=reach, state=state,
                            path=[v for v in (raw.get("hub"), raw.get("buffer")) if isinstance(v, str) and v] or None)
                lanes.append(lane)
                rows.append((lane, lane_name, raw))
            units.append(unit_of(uid, "afc", result, lanes))
        # AFC publishes lane order, not an index base: the position in the unit is used.
        result.diagnostics.append(diag("lane_index_is_position", "lane", NOTE))
        topology = build_topology(self, result, received_at, heads=[(h, None) for h in head_indexes],
                                  units=units, complete=False)
        observe_lane_states(self, result, received_at, "afc")
        for lane, lane_name, raw in rows:
            subject = {"kind": "lane", "id": lane.id}

            def fact(field, value, obs_suffix):
                obs = self.observe(result, observation_id=f"afc-{lane.id}-{obs_suffix}", subject=subject,
                                   field=field, value=value, snapshot_id=topology.snapshot_id,
                                   received_at=received_at)
                result.material_facts.append(MaterialFact(field, value, "provider", obs.observation_id))

            # AFC publishes weight with a default of 0 (afc_lane.py line 130), so 0 is not a reading.
            if is_num(raw.get("weight")) and raw["weight"] > 0:
                fact("remaining_g", raw["weight"], "remaining_g")
            td = raw.get("td1_td")
            if isinstance(td, str) and td.strip():
                try:
                    td = float(td)
                except ValueError:
                    td = None
            if is_num(td):
                fact("td", td, "td")
            if isinstance(raw.get("material"), str) and raw["material"].strip():
                fact("material", raw["material"].strip(), "material")
            if isinstance(raw.get("color"), str) and raw["color"].strip():
                fact("colour", raw["color"].strip().lower(), "colour")
            if is_index(raw.get("spool_id")) and raw["spool_id"] > 0:
                fact("spool", SpoolRef("afc", raw["spool_id"]), "spool")
            runout = raw.get("runout_lane")
            if isinstance(runout, str) and runout:
                result.diagnostics.append(diag("afc_runout_lane_declared", f"{lane_name}->{runout}"[:80], NOTE))


ADAPTER = register(AFCAdapter())
