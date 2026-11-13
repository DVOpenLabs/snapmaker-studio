"""Material facts, spool identity and field-by-field reconciliation.

Two providers that both call a spool `42` have two different spools unless a
`SpoolAlias` declares otherwise. Facts are reconciled per field; provenance is never
promoted, and a provider that reports only a weight never inherits identity fields
from another provider's row. `material_providers.combine` is not the canonical merge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from . import observations as obs_mod
from .decode import Decoded, Diagnostic, Reader, decode_document, diag, is_finite_number, NOTE, WARNING

SCHEMA_VERSION = "material_view/1"

FIELDS = ("material", "subtype", "colour", "brand", "spool", "remaining_g", "td", "nozzle_temp")
PROVENANCES = ("rfid", "user", "provider", "project", "derived", "unknown")
OCCUPANCY_STATES = ("loaded", "empty", "uncertain", "unknown")

#: Tie-break only (when observed_at is equal or unknown): higher wins.
RANK = {"rfid": 5, "user": 4, "provider": 3, "project": 2, "derived": 1, "unknown": 0}


@dataclass(frozen=True)
class SpoolRef:
    provider_instance_id: str
    provider_spool_id: str

    def __post_init__(self) -> None:
        for name in ("provider_instance_id", "provider_spool_id"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (str, int)) or str(value).strip() == "":
                raise ValueError(f"{name} must be a non-empty string or integer")
            object.__setattr__(self, name, str(value))

    def to_dict(self) -> dict:
        return {"provider_instance_id": self.provider_instance_id,
                "provider_spool_id": self.provider_spool_id}

    @classmethod
    def _read(cls, r: Reader) -> "SpoolRef | None":
        provider = r.string("provider_instance_id")
        spool = r.raw.get("provider_spool_id")
        if isinstance(spool, bool) or not isinstance(spool, (str, int)) or str(spool).strip() == "":
            r.error("wrong_type" if spool is not None else "missing_field", "provider_spool_id")
            return None
        return cls(provider, str(spool)) if provider else None


@dataclass(frozen=True)
class SpoolAlias:
    """The only way two providers' spools become one physical spool."""
    refs: tuple
    evidence: str
    declared_by: str

    def __post_init__(self) -> None:
        refs = tuple(self.refs)
        if len(refs) < 2 or not all(isinstance(x, SpoolRef) for x in refs):
            raise ValueError("an alias needs at least two SpoolRefs")
        object.__setattr__(self, "refs", refs)

    def to_dict(self) -> dict:
        return {"refs": [x.to_dict() for x in self.refs], "evidence": self.evidence,
                "declared_by": self.declared_by}

    @classmethod
    def _read(cls, r: Reader) -> "SpoolAlias | None":
        refs = []
        for i, item in enumerate(r.items("refs", required=True)):
            ref = SpoolRef._read(r.child(item, f"refs[{i}]"))
            if ref is not None:
                refs.append(ref)
        if len(refs) < 2:
            r.error("alias_needs_two_refs", "refs")
        evidence = r.string("evidence")
        declared_by = r.string("declared_by")
        if len(refs) < 2 or not evidence or not declared_by:
            return None
        return cls(tuple(refs), evidence, declared_by)


def _spool_groups(aliases: Iterable[SpoolAlias]) -> dict[SpoolRef, frozenset]:
    parent: dict[SpoolRef, SpoolRef] = {}

    def find(x: SpoolRef) -> SpoolRef:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for alias in aliases:
        first = find(alias.refs[0])
        for other in alias.refs[1:]:
            parent[find(other)] = first
    groups: dict[SpoolRef, set] = {}
    for ref in list(parent):
        groups.setdefault(find(ref), set()).add(ref)
    return {ref: frozenset(g) for g in groups.values() for ref in g}


def same_spool(a: SpoolRef, b: SpoolRef, aliases: Iterable[SpoolAlias] = ()) -> bool:
    """Equal refs, or declared the same physical spool by an alias. Colour and material never decide this."""
    if a == b:
        return True
    group = _spool_groups(aliases).get(a)
    return group is not None and b in group


@dataclass(frozen=True)
class MaterialFact:
    field: str
    value: Any
    provenance: str
    observation_id: str

    def __post_init__(self) -> None:
        if self.field not in FIELDS:
            raise ValueError(f"unknown material field {self.field!r}")
        if self.provenance not in PROVENANCES:
            raise ValueError(f"unknown provenance {self.provenance!r}")

    def to_dict(self) -> dict:
        value = self.value.to_dict() if isinstance(self.value, SpoolRef) else self.value
        return {"field": self.field, "value": value, "provenance": self.provenance,
                "observation_id": self.observation_id}

    @classmethod
    def _read(cls, r: Reader) -> "MaterialFact | None":
        name = r.enum("field", FIELDS)
        provenance = r.enum("provenance", PROVENANCES)
        obs_id = r.string("observation_id")
        if "value" not in r.raw:
            r.error("missing_field", "value")
            return None
        value = r.raw["value"]
        if name == "spool" and isinstance(value, dict):
            value = SpoolRef._read(r.child(value, "value"))
        if None in (name, provenance, obs_id):
            return None
        return cls(name, value, provenance, obs_id)


@dataclass(frozen=True)
class LaneOccupancy:
    lane_id: str
    spool: SpoolRef | None
    state: str
    observation_id: str | None = None

    def to_dict(self) -> dict:
        return {"lane_id": self.lane_id, "spool": self.spool.to_dict() if self.spool else None,
                "state": self.state, "observation_id": self.observation_id}

    @classmethod
    def _read(cls, r: Reader) -> "LaneOccupancy | None":
        lane_id = r.string("lane_id")
        state = r.enum("state", OCCUPANCY_STATES)
        spool_raw = r.raw.get("spool")
        spool = SpoolRef._read(r.child(spool_raw, "spool")) if isinstance(spool_raw, dict) else None
        if spool_raw is not None and not isinstance(spool_raw, dict):
            r.error("wrong_type", "spool")
        obs_id = r.string("observation_id", required=False)
        return cls(lane_id, spool, state, obs_id) if lane_id and state else None


@dataclass(frozen=True)
class RemainingQuantity:
    grams: float | None
    observation_id: str | None = None

    def __post_init__(self) -> None:
        if self.grams is not None and (not is_finite_number(self.grams) or self.grams < 0):
            raise ValueError("grams must be a finite non-negative number or None")

    def to_dict(self) -> dict:
        return {"grams": self.grams, "observation_id": self.observation_id}


def _fact_dict(fact: MaterialFact) -> dict:
    return fact.to_dict()


@dataclass
class MaterialView:
    spool: SpoolRef | None = None
    fields: dict = field(default_factory=dict)     # name -> {value, provenance, observation_id, freshness}
    conflicts: list = field(default_factory=list)  # [{field, a: MaterialFact, b: MaterialFact}]
    diagnostics: list = field(default_factory=list)

    def to_dict(self) -> dict:
        fields_out = {}
        for name, entry in self.fields.items():
            value = entry["value"].to_dict() if isinstance(entry["value"], SpoolRef) else entry["value"]
            fields_out[name] = {**entry, "value": value}
        return {"schema_version": SCHEMA_VERSION,
                "spool": self.spool.to_dict() if self.spool else None,
                "fields": fields_out,
                "conflicts": [{"field": c["field"], "a": c["a"].to_dict(), "b": c["b"].to_dict()}
                              for c in self.conflicts],
                "diagnostics": [d.to_dict() for d in self.diagnostics]}

    @classmethod
    def from_dict(cls, raw: Any) -> Decoded["MaterialView"]:
        return decode_document(raw, SCHEMA_VERSION, cls._build)

    @classmethod
    def _build(cls, r: Reader) -> "MaterialView":
        spool_raw = r.raw.get("spool")
        spool = SpoolRef._read(r.child(spool_raw, "spool")) if isinstance(spool_raw, dict) else None
        fields_out = {}
        for name, entry in r.mapping("fields").items():
            er = r.child(entry, f"fields.{name}")
            if name not in FIELDS:
                er.error("bad_enum", "")
                continue
            if "value" not in er.raw:
                er.error("missing_field", "value")
                continue
            value = er.raw["value"]
            if name == "spool" and isinstance(value, dict):
                value = SpoolRef._read(er.child(value, "value"))
            provenance = er.enum("provenance", PROVENANCES)
            obs_id = er.string("observation_id")
            fresh = er.mapping("freshness", required=True)
            fields_out[name] = {"value": value, "provenance": provenance, "observation_id": obs_id,
                                "freshness": dict(fresh)}
        conflicts = []
        for i, item in enumerate(r.items("conflicts")):
            cr = r.child(item, f"conflicts[{i}]")
            a = MaterialFact._read(cr.child(cr.raw.get("a"), "a"))
            b = MaterialFact._read(cr.child(cr.raw.get("b"), "b"))
            name = cr.enum("field", FIELDS)
            if a and b and name:
                conflicts.append({"field": name, "a": a, "b": b})
        return cls(spool=spool, fields=fields_out, conflicts=conflicts, diagnostics=[])


def _comparable(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, SpoolRef):
        return (value.provider_instance_id, value.provider_spool_id)
    return value


def _unknown_freshness() -> dict:
    return {"state": obs_mod.UNKNOWN, "age_s": None, "usable_for_loadout": False,
            "reason": "No observation is recorded for this fact."}


def reconcile(facts: Iterable[MaterialFact], observations: dict, now: Any = None) -> MaterialView:
    """Field-by-field reconciliation.

    Per field: (1) facts whose observation is UNUSABLE are discarded; (2) a fresh/ageing
    fact beats a stale one, a stale fact with a known time beats one with unknown time, and
    among equals the newest `observed_at` wins; (3) ties on equal or unknown `observed_at`
    go to rank rfid > user > provider > project > derived > unknown; (4) losing facts with a
    different value are kept in `conflicts`; (5) provenance is never promoted; (6) fields
    come only from facts for that field, so a weight-only provider adds no identity fields.
    """
    view = MaterialView()
    by_field: dict[str, list] = {}
    for fact in facts:
        observation = observations.get(fact.observation_id)
        fresh = obs_mod.freshness(observation, now) if observation is not None else _unknown_freshness()
        if fresh["state"] == obs_mod.UNUSABLE:
            view.diagnostics.append(diag("fact_discarded_unusable", fact.field, WARNING))
            continue
        stamp = obs_mod.parse_time(observation.observed_at) if observation is not None else None
        received = obs_mod.parse_time(observation.received_at) if observation is not None else None
        state = fresh["state"]
        tier = 0 if state in (obs_mod.FRESH, obs_mod.AGEING) else (1 if state == obs_mod.STALE and stamp else 2)
        key = (tier,
               -stamp.timestamp() if (tier < 2 and stamp is not None) else 0.0,
               -RANK[fact.provenance],
               -(received.timestamp() if received else 0.0),
               fact.observation_id)
        by_field.setdefault(fact.field, []).append((key, fact, fresh))

    for name, candidates in by_field.items():
        candidates.sort(key=lambda c: c[0])
        _, winner, fresh = candidates[0]
        view.fields[name] = {"value": winner.value, "provenance": winner.provenance,
                             "observation_id": winner.observation_id, "freshness": fresh}
        for _, loser, _ in candidates[1:]:
            if _comparable(loser.value) != _comparable(winner.value):
                view.conflicts.append({"field": name, "a": winner, "b": loser})
    spool_entry = view.fields.get("spool")
    if spool_entry and isinstance(spool_entry["value"], SpoolRef):
        view.spool = spool_entry["value"]
    return view
