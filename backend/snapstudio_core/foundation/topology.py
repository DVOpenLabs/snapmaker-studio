"""Printer topology: physical heads, feeder units, lanes, logical slots and bindings.

Hard rules: Studio never assumes four heads or sixteen slots. A head count is only
reported when the topology says its head list is complete; `reachable_heads` of None
means "unknown" while [] means "known unreachable"; project slot requirements are kept
apart from setup bindings. Internal indices are 0-based; `display_index = index + 1`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .decode import Decoded, Diagnostic, ERROR, NOTE, Reader, content_hash, decode_document, diag, revision_envelope
from .materials import LaneOccupancy
from .observations import parse_time

SCHEMA_VERSION = "topology/1"

UNIT_KINDS = ("stock", "multiace", "afc", "bmcu", "sidecar", "other")
LANE_STATES = ("loaded", "empty", "uncertain", "unknown")

#: Wire index bases. Adapters convert to 0-based internal indices and record the source.
INDEX_BASES = {"internal": 0, "gcode_t": 0, "multiace_wire": 0, "orca_filament": 1, "display": 1}

_NAME = r"[A-Za-z0-9_.-]+"
_HEAD_RE = re.compile(r"^head:(\d+)$")
_SLOT_RE = re.compile(r"^slot:(\d+)$")
_UNIT_RE = re.compile(rf"^unit:([a-z]+):({_NAME})$")
_LANE_RE = re.compile(rf"^lane:(unit:[a-z]+:{_NAME}):(\d+)$")


# -- ids and index bases ----------------------------------------------------------
def head_id(n: int) -> str:
    return f"head:{_index(n)}"


def slot_id(n: int) -> str:
    return f"slot:{_index(n)}"


def unit_id(kind: str, instance: str) -> str:
    if kind not in UNIT_KINDS:
        raise ValueError(f"unknown unit kind {kind!r}")
    if not isinstance(instance, str) or not re.fullmatch(_NAME, instance):
        raise ValueError("unit instance must be a simple name")
    return f"unit:{kind}:{instance}"


def lane_id(unit: str, n: int) -> str:
    if not _UNIT_RE.match(unit):
        raise ValueError("lane_id needs a unit id")
    return f"lane:{unit}:{_index(n)}"


def _index(n: int) -> int:
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ValueError("index must be a non-negative integer")
    return n


def id_kind(value: Any) -> str | None:
    """'head' | 'unit' | 'lane' | 'slot' for a well-formed id, else None."""
    if not isinstance(value, str):
        return None
    for kind, rx in (("head", _HEAD_RE), ("slot", _SLOT_RE), ("unit", _UNIT_RE), ("lane", _LANE_RE)):
        if rx.match(value):
            return kind
    return None


def id_suffix_index(value: str) -> int | None:
    """The trailing number of a head/slot/lane id."""
    for rx in (_HEAD_RE, _SLOT_RE):
        m = rx.match(value)
        if m:
            return int(m.group(1))
    m = _LANE_RE.match(value)
    return int(m.group(2)) if m else None


def normalise_index(source: str, value: Any) -> int | None:
    """Wire index -> 0-based internal index. None when `value` is not a usable index.

    G-code `T0` and Orca filament `1` both give 0 (slot:0). An unknown `source` is a
    programming error and raises.
    """
    if source not in INDEX_BASES:
        raise ValueError(f"unknown index base source {source!r}")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    result = value - INDEX_BASES[source]
    return result if result >= 0 else None


def denormalise_index(source: str, index: int) -> int:
    """0-based internal index -> the wire value for `source`."""
    if source not in INDEX_BASES:
        raise ValueError(f"unknown index base source {source!r}")
    return _index(index) + INDEX_BASES[source]


def index_base_diagnostic(source: str) -> Diagnostic:
    """The note an adapter records when it normalised an index from `source`."""
    if source not in INDEX_BASES:
        raise ValueError(f"unknown index base source {source!r}")
    return diag("index_base_source", source, NOTE)


# -- documents ------------------------------------------------------------------
@dataclass
class PhysicalToolhead:
    id: str
    index: int
    nozzle_mm: float | None = None
    evidence: list = field(default_factory=list)

    @property
    def display_index(self) -> int:
        return self.index + 1

    def to_dict(self) -> dict:
        return {"id": self.id, "index": self.index, "nozzle_mm": self.nozzle_mm,
                "evidence": list(self.evidence)}


@dataclass
class Lane:
    id: str
    unit_id: str
    index: int
    reachable_heads: list | None = None   # None = unknown; [] = known unreachable
    path: list | None = None              # ordered hub/buffer/merger ids, informational
    state: str = "unknown"
    occupancy: LaneOccupancy | None = None

    @property
    def display_index(self) -> int:
        return self.index + 1

    def to_dict(self) -> dict:
        return {"id": self.id, "unit_id": self.unit_id, "index": self.index,
                "reachable_heads": None if self.reachable_heads is None else list(self.reachable_heads),
                "path": None if self.path is None else list(self.path),
                "state": self.state,
                "occupancy": self.occupancy.to_dict() if self.occupancy else None}


@dataclass
class FeederUnit:
    id: str
    kind: str
    source_version: str | None = None
    lanes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "source_version": self.source_version,
                "lanes": [x.to_dict() for x in self.lanes]}


@dataclass
class LogicalSlot:
    id: str
    index: int
    binding: str | None = None   # lane id or head id; None = unbound
    nozzle_mm: float | None = None

    @property
    def display_index(self) -> int:
        return self.index + 1

    def to_dict(self) -> dict:
        return {"id": self.id, "index": self.index, "binding": self.binding, "nozzle_mm": self.nozzle_mm}


@dataclass
class ProjectSlotRequirement:
    """What a project asks for. Kept apart from SlotBinding, which is what the setup provides."""
    index: int
    material: str | None = None
    colour: str | None = None
    recipe_id: str | None = None

    def to_dict(self) -> dict:
        return {"index": self.index, "material": self.material, "colour": self.colour,
                "recipe_id": self.recipe_id}


@dataclass
class SlotBinding:
    slot_id: str
    target: str | None = None    # lane id or head id
    evidence: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"slot_id": self.slot_id, "target": self.target, "evidence": list(self.evidence)}


@dataclass
class ResourceConstraints:
    """None = unknown. `exclusive_paths`: lane groups of which only one may be active at a time."""
    exclusive_paths: list | None = None
    heads_single_active: bool | None = None


@dataclass
class Topology:
    snapshot_id: str
    received_at: str
    observed_at: str | None = None
    mapping_revision: str | None = None
    heads: list = field(default_factory=list)
    units: list = field(default_factory=list)
    slots: list = field(default_factory=list)
    bindings: list = field(default_factory=list)
    complete: bool = False     # True only when `heads` is the full physical head list
    evidence: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)

    def lanes(self) -> list:
        return [lane for unit in self.units for lane in unit.lanes]

    def content_hash(self) -> str:
        """Hash of what the topology says, ignoring when it was read and its diagnostics."""
        body = self.to_dict()
        for volatile in ("observed_at", "received_at", "diagnostics"):
            body.pop(volatile, None)
        return content_hash(body)

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "snapshot_id": self.snapshot_id,
                "observed_at": self.observed_at, "received_at": self.received_at,
                "mapping_revision": self.mapping_revision,
                "heads": [x.to_dict() for x in self.heads],
                "units": [x.to_dict() for x in self.units],
                "slots": [x.to_dict() for x in self.slots],
                "bindings": [x.to_dict() for x in self.bindings],
                "complete": self.complete, "evidence": list(self.evidence),
                "diagnostics": [d.to_dict() for d in self.diagnostics]}

    @classmethod
    def from_dict(cls, raw: Any) -> Decoded["Topology"]:
        return decode_document(raw, SCHEMA_VERSION, cls._build)

    @classmethod
    def _build(cls, r: Reader) -> "Topology":
        heads = []
        for i, item in enumerate(r.items("heads")):
            hr = r.child(item, f"heads[{i}]")
            heads.append(PhysicalToolhead(hr.string("id") or "", hr.integer("index", minimum=0) or 0,
                                          hr.number("nozzle_mm"), hr.string_list("evidence")))
        units = []
        for i, item in enumerate(r.items("units")):
            ur = r.child(item, f"units[{i}]")
            uid = ur.string("id") or ""
            lanes = []
            for j, litem in enumerate(ur.items("lanes")):
                lr = ur.child(litem, f"lanes[{j}]")
                occ_raw = lr.raw.get("occupancy")
                occ = LaneOccupancy._read(lr.child(occ_raw, "occupancy")) if isinstance(occ_raw, dict) else None
                if occ_raw is not None and not isinstance(occ_raw, dict):
                    lr.error("wrong_type", "occupancy")
                lanes.append(Lane(lr.string("id") or "", lr.string("unit_id") or "",
                                  lr.integer("index", minimum=0) or 0,
                                  lr.optional_string_list("reachable_heads"),
                                  lr.optional_string_list("path"),
                                  lr.enum("state", LANE_STATES, required=False, default="unknown"), occ))
            units.append(FeederUnit(uid, ur.enum("kind", UNIT_KINDS) or "other",
                                    ur.string("source_version", required=False), lanes))
        slots = []
        for i, item in enumerate(r.items("slots")):
            sr = r.child(item, f"slots[{i}]")
            slots.append(LogicalSlot(sr.string("id") or "", sr.integer("index", minimum=0) or 0,
                                     sr.string("binding", required=False), sr.number("nozzle_mm")))
        bindings = []
        for i, item in enumerate(r.items("bindings")):
            br = r.child(item, f"bindings[{i}]")
            bindings.append(SlotBinding(br.string("slot_id") or "", br.string("target", required=False),
                                        br.string_list("evidence")))
        diagnostics = []
        for i, item in enumerate(r.items("diagnostics")):
            dr = r.child(item, f"diagnostics[{i}]")
            code = dr.string("code")
            if code:
                diagnostics.append(diag(code, dr.raw.get("field") if isinstance(dr.raw.get("field"), str) else "",
                                        dr.enum("severity", ("error", "warning", "note"), required=False,
                                                default="warning")))
        received = r.string("received_at")
        observed = r.string("observed_at", required=False)
        for name, value in (("received_at", received), ("observed_at", observed)):
            if value is not None and parse_time(value) is None:
                r.warn("time_unreadable", name)
        return cls(snapshot_id=r.string("snapshot_id") or "", received_at=received or "",
                   observed_at=observed, mapping_revision=r.string("mapping_revision", required=False),
                   heads=heads, units=units, slots=slots, bindings=bindings,
                   complete=bool(r.boolean("complete", required=True)),
                   evidence=r.string_list("evidence"), diagnostics=diagnostics)


# -- validate ---------------------------------------------------------------------
def validate(topology: Topology) -> list[Diagnostic]:
    """Structural checks. Each problem gets a named diagnostic; nothing is repaired."""
    out: list[Diagnostic] = []
    seen: dict[str, int] = {}

    def register(value: str, expected_kind: str, where: str) -> None:
        seen[value] = seen.get(value, 0) + 1
        if seen[value] == 2:
            out.append(diag("duplicate_id", value, ERROR))
        if id_kind(value) != expected_kind:
            out.append(diag("invalid_id", f"{where}:{value}", ERROR))

    for head in topology.heads:
        register(head.id, "head", "heads")
    for unit in topology.units:
        register(unit.id, "unit", "units")
        for lane in unit.lanes:
            register(lane.id, "lane", "lanes")
            if lane.unit_id != unit.id or not lane.id.startswith(f"lane:{unit.id}:"):
                out.append(diag("lane_unit_mismatch", lane.id, ERROR))
    for slot in topology.slots:
        register(slot.id, "slot", "slots")

    head_ids = {h.id for h in topology.heads}
    lane_ids = {lane.id for lane in topology.lanes()}
    slot_ids = {s.id for s in topology.slots}

    for lane in topology.lanes():
        for h in lane.reachable_heads or []:
            if h not in head_ids:
                out.append(diag("lane_unknown_head", f"{lane.id}->{h}", ERROR))

    # Contiguity of ids and indices: all in one base, or flagged.
    groups = [("heads", [(h.id, h.index) for h in topology.heads])]
    groups.append(("slots", [(s.id, s.index) for s in topology.slots]))
    for unit in topology.units:
        groups.append((f"lanes:{unit.id}", [(lane.id, lane.index) for lane in unit.lanes]))
    for name, pairs in groups:
        offsets = {id_suffix_index(i) - idx for i, idx in pairs if id_suffix_index(i) is not None}
        if len(offsets) > 1:
            out.append(diag("mixed_index_bases", name, ERROR))
        elif offsets and offsets != {0}:
            out.append(diag("index_id_mismatch", name, ERROR))

    targets: dict[str, set] = {}
    for slot in topology.slots:
        if slot.binding is not None:
            targets.setdefault(slot.id, set()).add(slot.binding)
    for binding in topology.bindings:
        if binding.slot_id not in slot_ids:
            out.append(diag("binding_dangling", binding.slot_id, ERROR))
        if binding.target is not None:
            targets.setdefault(binding.slot_id, set()).add(binding.target)
    for slot_ref, tset in targets.items():
        for t in tset:
            if t not in head_ids and t not in lane_ids:
                out.append(diag("binding_dangling", f"{slot_ref}->{t}", ERROR))
        if len(tset) > 1:
            out.append(diag("contradictory_binding", slot_ref, ERROR))
    return out


# -- counts -----------------------------------------------------------------------
def counts(topology: Topology) -> dict:
    """Head and slot counts. Never derived from `len(slots)`; no default of 4 or 16."""
    lanes = topology.lanes()
    known_heads = len(topology.heads) if (topology.complete and topology.heads) else None
    return {"physical_heads": known_heads,
            "logical_slots": len(topology.slots),
            "lanes": len(lanes),
            "lanes_with_known_reach": sum(1 for lane in lanes if lane.reachable_heads is not None),
            "complete": bool(topology.complete)}


# -- assignability ----------------------------------------------------------------
class _SearchLimit(Exception):
    pass


_NODE_BUDGET = 200_000
_WILD = "*"


def _path_groups(lanes: list) -> list[frozenset]:
    """Lanes sharing any hub/buffer/merger id form one candidate-shared group."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: dict[str, str] = {}
    for lane in lanes:
        for element in lane.path or []:
            if element in owner:
                parent[find(lane.id)] = find(owner[element])
            else:
                owner[element] = lane.id
                find(lane.id)
    members: dict[str, set] = {}
    for lane in lanes:
        if lane.path:
            members.setdefault(find(lane.id), set()).add(lane.id)
    return [frozenset(g) for g in members.values() if len(g) > 1]


def _max_assign(idxs: list, opts: dict, heads_exclusive: bool, groups: list) -> int:
    lane_groups: dict[str, set] = {}
    for gi, group in enumerate(groups):
        for lane in group:
            lane_groups.setdefault(lane, set()).add(gi)
    best = 0
    nodes = 0
    order = list(idxs)

    def walk(pos: int, count: int, lanes: set, heads: set, direct: set, used_groups: set) -> None:
        nonlocal best, nodes
        nodes += 1
        if nodes > _NODE_BUDGET:
            raise _SearchLimit()
        if count > best:
            best = count
        if pos == len(order) or count + (len(order) - pos) <= best:
            return
        for lane, head in opts.get(order[pos], ()):
            if lane is None:
                if head in heads or head in direct:
                    continue
                walk(pos + 1, count + 1, lanes, heads, direct | {head}, used_groups)
                continue
            if lane in lanes:
                continue
            if head != _WILD and head in direct:
                continue
            if heads_exclusive and head != _WILD and head in heads:
                continue
            gset = lane_groups.get(lane, set())
            if gset & used_groups:
                continue
            # Heads used by lanes are always tracked so a direct head binding conflicts with a lane
            # through the same head whichever is placed first; only lane-vs-lane sharing of a head
            # depends on `heads_exclusive`.
            walk(pos + 1, count + 1, lanes | {lane},
                 heads | {head} if head != _WILD else heads,
                 direct, used_groups | gset)
        walk(pos + 1, count, lanes, heads, direct, used_groups)

    walk(0, 0, set(), set(), set(), set())
    return best


def assignability(topology: Topology, requested: Iterable[ProjectSlotRequirement],
                  constraints: ResourceConstraints | None = None, *, revisions: dict | None = None) -> dict:
    """Material-to-head assignability: can each requested material be given a lane and a head?

    Returns {assignable: True|False|None, bound: {min, max}|None, per_requirement, reasons}.
    `min` assumes the worst case the unknowns allow and `max` the best case; the answer is
    exact only when they agree. Unknown reach or unknown constraints never produce an exact count.
    """
    cons = constraints or ResourceConstraints()
    reqs = list(requested)
    envelope = revision_envelope(
        {"topology": {"snapshot_id": topology.snapshot_id, "hash": topology.content_hash()},
         "mapping_revision": topology.mapping_revision,
         "requested": [q.to_dict() for q in reqs],
         "constraints": {"exclusive_paths": [sorted(g) for g in cons.exclusive_paths]
                         if cons.exclusive_paths is not None else None,
                         "heads_single_active": cons.heads_single_active}},
        revisions)
    lanes = {lane.id: lane for lane in topology.lanes()}
    head_ids = [h.id for h in topology.heads]
    reasons: list[str] = []

    targets: dict[str, set] = {}
    for slot in topology.slots:
        if slot.binding is not None:
            targets.setdefault(slot.id, set()).add(slot.binding)
    for binding in topology.bindings:
        if binding.target is not None:
            targets.setdefault(binding.slot_id, set()).add(binding.target)

    def lane_options(lane: Lane, wildcard: bool) -> list:
        if lane.reachable_heads is None:
            return [(lane.id, _WILD)] if wildcard else []
        return [(lane.id, h) for h in sorted(lane.reachable_heads)]

    forced_unknown: set = set()
    opts_low: dict = {}
    opts_high: dict = {}
    for i, req in enumerate(reqs):
        sid = slot_id(req.index)
        tset = targets.get(sid, set())
        if len(tset) > 1:
            forced_unknown.add(i)
            reasons.append(f"{sid} is bound to more than one target")
            opts_low[i] = opts_high[i] = []
            continue
        target = next(iter(tset)) if tset else None
        for wildcard, store in ((False, opts_low), (True, opts_high)):
            if target is not None and target in lanes:
                store[i] = lane_options(lanes[target], wildcard)
            elif target is not None and id_kind(target) == "head":
                store[i] = [(None, target)]
            elif target is not None:
                store[i] = []
            elif lanes:
                store[i] = [o for lane in lanes.values() for o in lane_options(lane, wildcard)]
            else:
                store[i] = [(None, h) for h in head_ids]
        if target is not None and target not in lanes and id_kind(target) != "head":
            reasons.append(f"{sid} is bound to {target}, which the topology does not contain")

    declared = cons.exclusive_paths
    shared_paths = _path_groups(list(lanes.values()))
    low_groups = [frozenset(g) for g in declared] if declared is not None else shared_paths
    high_groups = [frozenset(g) for g in declared] if declared is not None else []
    low_heads_exclusive = cons.heads_single_active is not False
    high_heads_exclusive = cons.heads_single_active is True

    n = len(reqs)
    idxs = list(range(n))
    try:
        n_low = _max_assign(idxs, opts_low, low_heads_exclusive, low_groups)
        n_high = _max_assign(idxs, opts_high, high_heads_exclusive, high_groups)
        alone_low = {i: _max_assign([i], opts_low, low_heads_exclusive, low_groups) == 1 for i in idxs}
        alone_high = {i: _max_assign([i], opts_high, high_heads_exclusive, high_groups) == 1 for i in idxs}
        ok_low = [i for i in idxs if alone_low[i]]
        joint_ok_set = _max_assign(ok_low, opts_low, low_heads_exclusive, low_groups) == len(ok_low)
        pair_conflict: dict[int, bool] = {}
        for i in ok_low:
            pair_conflict[i] = any(
                _max_assign([i, j], opts_low, low_heads_exclusive, low_groups) < 2 for j in ok_low if j != i)
    except _SearchLimit:
        return {"assignable": None, "bound": None, "per_requirement": [],
                "reasons": reasons + ["The assignment search was too large to finish, so the answer is unknown."],
                "inputs_revision": envelope}

    n_high = max(n_high, n_low)
    if n_low < n_high:
        if any(lane.reachable_heads is None for lane in lanes.values()):
            for lane in lanes.values():
                if lane.reachable_heads is None:
                    reasons.append(f"The reach of {lane.id} is unknown.")
        if cons.heads_single_active is None and _shared_heads(lanes):
            reasons.append("Whether a head can serve only one lane at a time is unknown.")
        if declared is None and shared_paths:
            reasons.append("Whether lanes sharing a feeder path are exclusive is unknown.")

    per_requirement = []
    for i, req in enumerate(reqs):
        sid = slot_id(req.index)
        cands = sorted({(lane if lane is not None else head) for lane, head in opts_high[i]})
        if i in forced_unknown:
            result = "unknown"
        elif not alone_high[i]:
            result = "unreachable"
        elif not alone_low[i]:
            result = "unknown"
        elif n_low == n or joint_ok_set or (any(pair_conflict.values()) and not pair_conflict[i]):
            result = "ok"
        else:
            result = "contended"
        per_requirement.append({"slot_id": sid, "candidates": cands, "result": result})
        if result == "contended":
            reasons.append(f"{sid} competes with another requested material for the same head or feeder path.")

    if n_low == n:
        assignable: bool | None = True
    elif n_high < n:
        assignable = False
    else:
        assignable = None
    return {"assignable": assignable, "bound": {"min": n_low, "max": n_high},
            "per_requirement": per_requirement, "reasons": reasons, "inputs_revision": envelope}


def _shared_heads(lanes: dict) -> bool:
    seen: set = set()
    for lane in lanes.values():
        for h in lane.reachable_heads or []:
            if h in seen:
                return True
            seen.add(h)
    return False
