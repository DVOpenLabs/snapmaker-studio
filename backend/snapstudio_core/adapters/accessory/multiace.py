"""multiACE loadout parser: GET /multiace/api/preflight/livedata (engine api_version 1).

Contract (decay71/multiACE): docs/LOADOUT_API.md blob bac8805b (sec 1, 2, 4, 7) and
web/backend/main.py blob d19bc7a2 (_live_slots_async lines 1204-1229, _head_mode_context
lines 1256-1330). Wire indices are 0-based. The docs say livedata answers HTTP 409 while a
head is manual; the code returns 200 with head_ctx.manual_heads instead. Both are read.
"""
from __future__ import annotations

from ..base import Adapter, AdapterInfo
from ..registry import register
from ...foundation.decode import WARNING, diag
from ...foundation.materials import MaterialFact
from ...foundation.topology import Lane, index_base_diagnostic, lane_id, unit_id
from ._common import build_topology, invalid, is_index, is_num, note, observe_lane_states, unit_of, unwrap

MODES = ("multi", "head", "normal")


def _str_keyed_ints(raw, result, field):
    """{"0": 0, "1": 1} -> {0: 0, 1: 1}; None when the object is malformed."""
    out = {}
    for key, value in raw.items():
        if not (isinstance(key, str) and key.isdigit()) or not is_num(value):
            invalid(result, field)
            return None
        out[int(key)] = value
    return out


class MultiAceAdapter(Adapter):
    info = AdapterInfo("multiace", "accessory", ("1",), 300.0)

    def _parse(self, payload, received_at, result):
        body, status = unwrap(payload, result, accept=(200, 409))
        if body is None:
            return
        if status == 409:
            # Docs: 409 = a head is manual, the slot-based matcher is unavailable. Not an error,
            # and it says nothing about head count or slots.
            result.diagnostics.append(diag("assignment_unavailable_manual_head", "http_status", WARNING))
            result.unknowns.extend(["heads", "lanes", "manual_heads"])
            build_topology(self, result, received_at, heads=[], units=[], complete=False)
            return
        if not isinstance(body, dict) or not isinstance(body.get("live_slots"), list) \
                or not isinstance(body.get("head_ctx"), dict):
            invalid(result, "livedata")
            return
        ctx = body["head_ctx"]
        mode = ctx.get("mode")
        if mode not in MODES:
            invalid(result, "head_ctx.mode")
            return
        nozzles_raw = ctx.get("head_nozzles", {})
        head_ace_raw = ctx.get("head_ace", {})
        if not isinstance(nozzles_raw, dict) or not isinstance(head_ace_raw, dict):
            invalid(result, "head_ctx")
            return
        nozzles = _str_keyed_ints(nozzles_raw, result, "head_ctx.head_nozzles")
        head_ace = _str_keyed_ints(head_ace_raw, result, "head_ctx.head_ace")
        if nozzles is None or head_ace is None:
            return
        ace_heads = ctx.get("ace_heads", [])
        if not isinstance(ace_heads, list) or not all(is_index(h) for h in ace_heads):
            invalid(result, "head_ctx.ace_heads")
            return
        manual = ctx.get("manual_heads", [])
        feeders = ctx.get("feeders", [])
        empty_slots = ctx.get("empty_slots", [])
        for name, rows, keys in (("manual_heads", manual, ("head",)), ("feeders", feeders, ("head",)),
                                 ("empty_slots", empty_slots, ("ace", "slot"))):
            if not isinstance(rows, list) or not all(
                    isinstance(r, dict) and all(is_index(r.get(k)) for k in keys) for r in rows):
                invalid(result, f"head_ctx.{name}")
                return
        slots = []
        for row in body["live_slots"]:
            if not (isinstance(row, dict) and is_index(row.get("ace")) and is_index(row.get("slot"))
                    and isinstance(row.get("material"), str) and isinstance(row.get("color"), str)):
                invalid(result, "live_slots")
                return
            slots.append(row)
        types = ctx.get("head_nozzle_types")
        if types is not None and (not isinstance(types, dict) or not all(
                isinstance(k, str) and k.isdigit() and isinstance(v, str) for k, v in types.items())):
            invalid(result, "head_ctx.head_nozzle_types")
            return

        manual_ids = {r["head"] for r in manual}
        heads = sorted(nozzles.items())
        if not heads:
            result.unknowns.append("heads")
        if types is None:
            note(result, "nozzle_types_unknown", "head_ctx.head_nozzle_types")
        result.diagnostics.append(index_base_diagnostic("multiace_wire"))

        def reach(ace, slot):
            if mode == "multi":
                return [] if slot in manual_ids else [f"head:{slot}"]
            if mode == "head":
                if not ace_heads:
                    return None
                return [f"head:{h}" for h in sorted(ace_heads)
                        if head_ace.get(h, h) == ace and h not in manual_ids]
            return None

        units = {}

        def lane_for(ace, slot, state):
            uid = unit_id("multiace", f"ace{ace}")
            units.setdefault(uid, []).append(
                Lane(lane_id(uid, slot), uid, slot, reachable_heads=reach(ace, slot), state=state))

        facts = []
        if mode == "normal":
            note(result, "multiace_not_driving_feed", "head_ctx.mode")
            result.unknowns.append("lanes")
        else:
            for row in slots:
                lane_for(row["ace"], row["slot"], "loaded")
            for row in empty_slots:
                lane_for(row["ace"], row["slot"], "empty")
            if not slots and not empty_slots:
                result.unknowns.append("lanes")
        lane_units = [unit_of(uid, "multiace", result, sorted(lanes, key=lambda x: x.index))
                      for uid, lanes in sorted(units.items())]
        if mode != "normal":
            # Printer-side feeders and hand-fed heads are separate single-colour sources.
            for kind_name, rows, state, prov in (("feeder", feeders, "loaded", "provider"),
                                                 ("manual", manual, "uncertain", "user")):
                if not rows:
                    continue
                uid = unit_id("stock" if kind_name == "feeder" else "other", kind_name)
                lanes = [Lane(lane_id(uid, r["head"]), uid, r["head"],
                              reachable_heads=[f"head:{r['head']}"], state=state)
                         for r in sorted(rows, key=lambda r: r["head"])]
                lane_units.append(unit_of(uid, "stock" if kind_name == "feeder" else "other", result, lanes))
        # head_nozzles is a best-effort nozzle map, not a head inventory: multiACE queries only
        # extruder..extruder3 and drops any head whose diameter it cannot read (contracts/multiace_main.py
        # _machine_nozzles). The list is treated as complete only when every queried head came back.
        queried = {0, 1, 2, 3}
        head_list_complete = {index for index, _ in heads} == queried
        if heads and not head_list_complete:
            note(result, "head_list_may_be_partial", "head_ctx.head_nozzles")
            result.unknowns.append("heads")
        topology = build_topology(self, result, received_at, heads=heads, units=lane_units,
                                  complete=head_list_complete)
        for head in topology.heads:
            if types is not None and str(head.index) in types:
                head.evidence.append(f"nozzle_type:{types[str(head.index)]}")
        observe_lane_states(self, result, received_at, "multiace")
        # Identity facts: only live_slots (rfid or override) and pinned feeder/manual entries.
        by_lane = {(u.id, ln.index): ln for u in topology.units for ln in u.lanes}
        for row in slots:
            lane = by_lane.get((unit_id("multiace", f"ace{row['ace']}"), row["slot"]))
            if lane is None:
                continue
            for field, value in (("material", row["material"]), ("colour", row["color"])):
                if value:
                    obs = self.observe(result, observation_id=f"multiace-{lane.id}-{field}",
                                       subject={"kind": "lane", "id": lane.id}, field=field, value=value,
                                       snapshot_id=topology.snapshot_id, received_at=received_at)
                    facts.append(MaterialFact(field, value, "provider", obs.observation_id))
        result.material_facts.extend(facts)


ADAPTER = register(MultiAceAdapter())
