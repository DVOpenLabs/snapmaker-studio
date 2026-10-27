"""Sidecar (beta preview) parser for the contracts upstream publishes.

Contract (dcan999/Sidecar-Beta): README.md blob 6cfdc4b1 line 27 (virtual tool T is toolhead
T // 4, lane (T % 4) + 1); host/pi/runtime/sc_watchd.py blob c1e93fb4 lines 9-11 and 255-275
(G-code markers `;SIDECAR:REQUEST=1`, `;SIDECAR:PROCESSED=1`, `;SIDECAR:BLOCKED=1`,
`;SIDECAR:REASON=<text>`); host/pi/ui/source/src/lib/sidecarApi.ts blob 6d9823fc lines 123-165
(client for the Pi API on port 8090; only the load-cell reply shape is visible there).
docs/STATUS.md blob bbb11613: beta preview, stock-U1 handoff not validated on hardware.

Accepted payloads (a Studio wrapper only carries upstream text or a reply body):
  {"kind": "gcode", "text": "<sliced G-code>"}
  {"kind": "loadcell", "unit": 1, "body": {"ok": true, "lanes": {"1": {"raw_g": n, "net_g": n}}}}
      (`unit` is the unit Studio asked about. The aux fallback reply, sidecarApi.ts lines 123-142,
      does not carry it; the Pi /api/v1/loadcell/state body is passed through unpublished and the
      client reads a `unit` from it at line 150, which Studio does not rely on or cross-check.)
  {"kind": "state" | "lane_meta", "body": {...}}   -> reply bodies are not published: all unknown
"""
from __future__ import annotations

import re

from ..base import Adapter, AdapterInfo
from ..registry import register
from ...foundation.decode import ERROR, NOTE, WARNING, diag
from ...foundation.topology import (Lane, LogicalSlot, SlotBinding, index_base_diagnostic, lane_id,
                                    normalise_index, slot_id, unit_id)
from ._common import build_topology, invalid, is_num, note, observe_lane_states, unit_of, unwrap

_MARKER = re.compile(r"^\s*;\s*SIDECAR:(REQUEST|PROCESSED|BLOCKED|REASON)=(.*?)\s*$", re.M)
_TOOL = re.compile(r"^\s*T(\d+)\s*(?:;.*)?$", re.M)
_UNSAFE = re.compile(r"[^A-Za-z0-9 _.-]")


class SidecarAdapter(Adapter):
    info = AdapterInfo("sidecar", "accessory", ("beta-preview",), 120.0)

    def _parse(self, payload, received_at, result):
        body, _ = unwrap(payload, result)
        if body is None:
            return
        if not isinstance(body, dict):
            invalid(result)
            return
        kind = body.get("kind")
        if kind == "gcode" and isinstance(body.get("text"), str):
            self._gcode(body["text"], received_at, result)
        elif kind == "loadcell" and isinstance(body.get("body"), dict):
            self._loadcell(body["body"], body.get("unit"), received_at, result)
        elif kind in ("state", "lane_meta") and isinstance(body.get("body"), dict):
            self._unpublished(body["body"], received_at, result)
        else:
            invalid(result, "kind")

    def _gcode(self, text, received_at, result):
        markers = {}
        for name, value in _MARKER.findall(text):
            markers[name] = value
        tagged = any(k in markers for k in ("REQUEST", "PROCESSED", "BLOCKED"))
        if not tagged:
            # No Sidecar marker: T cannot be read as a Sidecar tool, so no head or lane is invented.
            build_topology(self, result, received_at, heads=[], units=[], complete=False)
            result.unknowns.extend(["tools", "lanes"])
            note(result, "untagged_no_sidecar_mapping", "gcode")
            return
        tools = sorted({int(t) for t in _TOOL.findall(text)})
        by_head = {}
        for t in tools:
            head, index = t // 4, t % 4
            uid = unit_id("sidecar", f"head{head}")
            by_head.setdefault(uid, []).append(
                Lane(lane_id(uid, index), uid, index, reachable_heads=[f"head:{head}"], state="unknown"))
        units = [unit_of(uid, "sidecar", result, lanes) for uid, lanes in sorted(by_head.items())]
        heads = sorted({t // 4 for t in tools})
        topology = build_topology(self, result, received_at, heads=[(h, None) for h in heads], units=units,
                                  complete=False)
        topology.slots = [LogicalSlot(slot_id(t), t) for t in tools]
        topology.bindings = [SlotBinding(slot_id(t), lane_id(unit_id("sidecar", f"head{t // 4}"), t % 4),
                                         ["sidecar_t_mapping"]) for t in tools]
        result.diagnostics.append(index_base_diagnostic("gcode_t"))
        if "PROCESSED" in markers:
            note(result, "sidecar_processed", "gcode")
        if "BLOCKED" in markers:
            reason = _UNSAFE.sub("", markers.get("REASON", ""))[:64]
            result.diagnostics.append(diag("sidecar_blocked", reason, WARNING))
        result.unknowns.append("lane_states")
        note(result, "sidecar_beta_unverified_on_hardware", "gcode")
        observe_lane_states(self, result, received_at, "sidecar")

    def _loadcell(self, reply, unit, received_at, result):
        # The published reply (sidecarApi.ts lines 123-142) is {ok, lanes}. It does not say which
        # unit was asked, so `unit` is Studio's own request context from the wrapper, not a reply key.
        lanes = reply.get("lanes")
        if reply.get("ok") is False or "_http" in reply:
            result.errors.append(diag("unavailable", "ok", ERROR))
            result.unknowns.append("all")
            return
        if not isinstance(lanes, dict):
            invalid(result, "loadcell")
            return
        if isinstance(unit, int) and not isinstance(unit, bool) and unit >= 1:
            uid = unit_id("sidecar", f"unit{unit}")
        else:
            uid = unit_id("sidecar", "unit_unstated")
            note(result, "loadcell_unit_not_stated", "loadcell")
        rows = []
        for key, cell in lanes.items():
            index = normalise_index("display", int(key)) if isinstance(key, str) and key.isdigit() else None
            if index is None or not isinstance(cell, dict):
                invalid(result, "loadcell.lanes")
                return
            rows.append((index, cell))
        rows.sort(key=lambda r: r[0])
        # A load-cell force reading is not presence and not a head route: both stay unknown.
        topology = build_topology(self, result, received_at, heads=[],
                                  units=[unit_of(uid, "sidecar", result,
                                                 [Lane(lane_id(uid, i), uid, i) for i, _ in rows])],
                                  complete=False)
        for index, cell in rows:
            for field in ("raw_g", "net_g"):
                value = cell.get(field)
                if value is None:
                    continue
                if not is_num(value):
                    invalid(result, f"loadcell.{field}")
                    return
                self.observe(result, observation_id=f"sidecar-{uid}-{index}-{field}",
                             subject={"kind": "lane", "id": lane_id(uid, index)}, field=field, value=value,
                             snapshot_id=topology.snapshot_id, received_at=received_at)
        result.diagnostics.append(index_base_diagnostic("display"))
        note(result, "loadcell_force_is_not_remaining_mass", "loadcell")
        result.unknowns.extend(["lane_states", "reachable_heads"])

    def _unpublished(self, reply, received_at, result):
        if reply.get("ok") is False or "_http" in reply:
            result.errors.append(diag("unavailable", "ok", ERROR))
            result.unknowns.append("all")
            return
        build_topology(self, result, received_at, heads=[], units=[], complete=False)
        result.unknowns.extend(["heads", "lanes", "materials"])
        result.diagnostics.append(diag("body_shape_not_published", "body", NOTE))


ADAPTER = register(SidecarAdapter())
