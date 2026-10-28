"""BMCU-Klipper parser for the contracts upstream publishes.

Contract (jarczakpawel/BMCU-Klipper): docs/COMMANDS.md blob 2bc051ed (sec 3 routing commands,
print plan `BMCU_PRINT_BEGIN SCHEMA=1 RESET=1` / REQUIRE / MAP / COMMIT, `BMCU_MAP_TOOL` alias,
`BMCU_SET_ENDPOINT`, `BMCU_SET_ROUTE`, `BMCU_ROUTE_CONFIRM STATE=EMPTY|PARKED|LOADED`),
printers/Snapmaker_U1/README.md blob eac7b8c3 (T0-T3 native, T4+ BMCU channels) and
web/bmcu_panel_server.py blob bd2d86ae lines 1973-2047 (`GET /api/transport-status`, schema 1).

Accepted payloads (a Studio wrapper only carries the upstream text or body):
  {"kind": "klipper_text", "text": "<G-code / config lines>"}
  {"kind": "transport_status", "body": {<panel reply>}}
BMCU_STATUS output and the panel's per-device `status` object are not published, so channel
states come only from a user's `BMCU_ROUTE_CONFIRM` line and are otherwise unknown.
"""
from __future__ import annotations

import re

from ..base import Adapter, AdapterInfo
from ..registry import register
from ...foundation.decode import ERROR, NOTE, WARNING, diag
from ...foundation.materials import MaterialFact
from ...foundation.observations import to_iso
from ...foundation.topology import (Lane, LogicalSlot, SlotBinding, index_base_diagnostic, lane_id, slot_id,
                                    unit_id)
from ._common import build_topology, head_from_extruder, invalid, is_num, note, observe_lane_states, safe_name, \
    unit_of, unwrap

_PARAM = re.compile(r'([A-Za-z_]+)=("[^"]*"|\S+)')
# bmcu_COMMANDS.md lines 530-535: BMCU_ROUTE_CONFIRM STATE is EMPTY, PARKED or LOADED, nothing else.
_STATES = {"LOADED": "loaded", "EMPTY": "empty", "PARKED": "unknown"}
_MAX_CHANNEL = 3     # bmcu_COMMANDS.md lines 612-617: CHANNEL=0..3 on one device
_MAP = {"BMCU_PRINT_MAP", "BMCU_MAP_TOOL"}
_ROUTE = {"BMCU_SET_ROUTE", "BMCU_SET_OUTPUT"}


def _params(line: str) -> dict:
    return {k.upper(): v.strip('"') for k, v in _PARAM.findall(line)}


def _int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


class BMCUAdapter(Adapter):
    info = AdapterInfo("bmcu", "accessory", ("1",), 180.0)

    def _parse(self, payload, received_at, result):
        body, _ = unwrap(payload, result)
        if body is None:
            return
        if not isinstance(body, dict):
            invalid(result)
            return
        kind = body.get("kind")
        if kind == "klipper_text" and isinstance(body.get("text"), str):
            self._text(body["text"], received_at, result)
        elif kind == "transport_status" and isinstance(body.get("body"), dict):
            self._transport(body["body"], received_at, result)
        else:
            invalid(result, "kind")

    def _transport(self, panel, received_at, result):
        devices = panel.get("devices")
        if panel.get("schema") != 1 or not isinstance(devices, list):
            invalid(result, "schema")
            return
        units = []
        for item in devices:
            name = item.get("name") if isinstance(item, dict) else None
            if not (isinstance(name, str) and re.fullmatch(r"bmcu\d+", name)
                    and isinstance(item.get("online"), bool)):
                invalid(result, "devices")
                return
            units.append((item, unit_id("bmcu", name)))
        build_topology(self, result, received_at, heads=[], complete=False,
                       units=[unit_of(uid, "bmcu", result, []) for _, uid in units])
        for item, uid in units:
            stamp = item.get("updated_at")
            self.observe(result, observation_id=f"bmcu-{uid}-online", subject={"kind": "unit", "id": uid},
                         field="online", value=item["online"], snapshot_id=result.topology.snapshot_id,
                         received_at=received_at,
                         provider_time=to_iso(stamp) if is_num(stamp) and stamp > 0 else None)
        if isinstance(panel.get("error"), str) or any(i.get("error") for i in devices):
            result.diagnostics.append(diag("panel_reported_error", "devices", WARNING))
        result.unknowns.extend(["channels", "routes"])
        note(result, "device_status_shape_not_published", "devices.status")

    def _text(self, text, received_at, result):
        endpoints, routes, confirms, mapped, required = {}, {}, {}, {}, []
        plan = {"schema": None, "committed": False}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line[0] in ";#":
                continue
            command = line.split(None, 1)[0].upper()
            p = _params(line)
            if "CHANNEL" in p and (_int(p["CHANNEL"]) is None or _int(p["CHANNEL"]) > _MAX_CHANNEL):
                invalid(result, "CHANNEL")
                return
            if command in _MAP and not (plan["schema"] is not None and not plan["committed"]):
                # BMCU_MAP_TOOL is an alias of BMCU_PRINT_MAP and upstream rejects it outside an open
                # print plan (bmcu_COMMANDS.md line 311; BEGIN..COMMIT is atomic, lines 581-650).
                invalid(result, command)
                return
            if command == "BMCU_PRINT_BEGIN":
                if p.get("SCHEMA") != "1":
                    result.errors.append(diag("unsupported_plan_schema", "SCHEMA", ERROR))
                    result.unknowns.append("all")
                    return
                plan["schema"] = 1
                plan["committed"] = False
                if p.get("RESET") == "1":
                    mapped.clear()
                    required.clear()
            elif command == "BMCU_PRINT_REQUIRE":
                tool = _int(p.get("TOOL"))
                if tool is None:
                    invalid(result, "TOOL")
                    return
                if tool not in required:
                    required.append(tool)
            elif command in _MAP:
                tool = _int(p.get("TOOL"))
                if tool is None:
                    invalid(result, "TOOL")
                    return
                mapped[tool] = p
            elif command == "BMCU_PRINT_COMMIT":
                plan["committed"] = True
            elif command == "BMCU_SET_ENDPOINT" and p.get("NAME"):
                endpoints[p["NAME"]] = (head_from_extruder(p.get("EXTRUDER")), p.get("SHARED_PATH_GROUP"))
            elif command in _ROUTE and p.get("DEVICE") and _int(p.get("CHANNEL")) is not None:
                routes[(p["DEVICE"], _int(p["CHANNEL"]))] = p.get("ENDPOINT", "")
            elif command == "BMCU_ROUTE_CONFIRM" and p.get("DEVICE") and _int(p.get("CHANNEL")) is not None:
                state = _STATES.get(p.get("STATE", "").upper())
                if state is None:
                    invalid(result, "STATE")
                    return
                confirms[(p["DEVICE"], _int(p["CHANNEL"]))] = state
        keys = set(routes) | set(confirms)
        for p in mapped.values():
            if p.get("DEVICE") and _int(p.get("CHANNEL")) is not None:
                keys.add((p["DEVICE"], _int(p["CHANNEL"])))
        by_device = {}
        for device, channel in sorted(keys):
            endpoint = routes.get((device, channel))
            reach = None
            if endpoint is not None:
                if endpoint.upper() == "NONE":
                    reach = []
                elif endpoint in endpoints and endpoints[endpoint][0] is not None:
                    reach = [f"head:{endpoints[endpoint][0]}"]
            uid = unit_id("bmcu", safe_name(device))
            by_device.setdefault(uid, []).append(
                Lane(lane_id(uid, channel), uid, channel, reachable_heads=reach,
                     state=confirms.get((device, channel), "unknown")))
        units = [unit_of(uid, "bmcu", result, lanes) for uid, lanes in sorted(by_device.items())]
        heads = sorted({h for h, _ in endpoints.values() if h is not None})
        topology = build_topology(self, result, received_at, heads=[(h, None) for h in heads], units=units,
                                  complete=False)
        tools = sorted(set(required) | set(mapped))
        topology.slots = [LogicalSlot(slot_id(t), t) for t in tools]
        for t, p in sorted(mapped.items()):
            if p.get("DEVICE") and _int(p.get("CHANNEL")) is not None:
                target = lane_id(unit_id("bmcu", safe_name(p["DEVICE"])), _int(p["CHANNEL"]))
                topology.bindings.append(SlotBinding(slot_id(t), target, ["bmcu_print_map"]))
        result.diagnostics.append(index_base_diagnostic("gcode_t"))
        for group in sorted({g for _, g in endpoints.values() if g}):
            members = sorted(n for n, (_, g) in endpoints.items() if g == group)
            result.diagnostics.append(diag("shared_path_group", f"{group}:{'+'.join(members)}"[:80], NOTE))
        if plan["schema"] is not None:
            if not plan["committed"]:
                result.diagnostics.append(diag("plan_not_committed", "BMCU_PRINT_COMMIT", WARNING))
            for t in required:
                if t not in mapped:
                    result.diagnostics.append(diag("required_tool_unmapped", f"T{t}", WARNING))
                    result.unknowns.append(f"source:T{t}")
        for t in tools:
            if t < 4:
                note(result, "native_u1_source", f"T{t}")
        observe_lane_states(self, result, received_at, "bmcu")
        for t, p in sorted(mapped.items()):
            for field, key in (("material", "MATERIAL"), ("colour", "COLOR")):
                value = p.get(key)
                if not value:
                    continue
                if value.startswith("{"):
                    note(result, "plan_placeholder_unresolved", f"T{t}.{key}")
                    continue
                obs = self.observe(result, observation_id=f"bmcu-T{t}-{field}",
                                   subject={"kind": "slot", "id": slot_id(t)}, field=field, value=value,
                                   snapshot_id=topology.snapshot_id, received_at=received_at)
                result.material_facts.append(MaterialFact(field, value, "project", obs.observation_id))
        if not units:
            result.unknowns.append("lanes")


ADAPTER = register(BMCUAdapter())
