"""Capabilities and requirements.

A capability is evidence that something is supported, unsupported or unknown within a
scope (host, slicer, generator, version, process). A missing key is unknown, never
"unsupported". Conflicting evidence yields unknown with both pieces of evidence, and a
capability observed under a different scope (for example another calibration basis in
`process`) does not apply, so the answer falls back to unknown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .decode import Decoded, Reader, content_hash, decode_document, revision_envelope

SCHEMA_VERSION = "capability_set/1"

STATES = ("supported", "unsupported", "unknown", "conflicting")
SCOPE_KEYS = ("host", "slicer", "generator", "version", "process")
SATISFIED, UNMET, UNKNOWN = "satisfied", "unmet", "unknown"


def _scope(raw: dict | None) -> dict:
    raw = raw or {}
    return {k: (raw.get(k) if isinstance(raw.get(k), str) else None) for k in SCOPE_KEYS}


@dataclass
class Capability:
    key: str
    state: str
    scope: dict = field(default_factory=lambda: _scope(None))
    evidence: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"unknown capability state {self.state!r}")
        self.scope = _scope(self.scope)

    def to_dict(self) -> dict:
        return {"key": self.key, "state": self.state, "scope": dict(self.scope),
                "evidence": list(self.evidence)}


@dataclass
class CapabilitySet:
    capabilities: dict = field(default_factory=dict)   # key -> [Capability]

    def add(self, capability: Capability) -> None:
        self.capabilities.setdefault(capability.key, []).append(capability)

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION,
                "capabilities": {k: [c.to_dict() for c in v] for k, v in sorted(self.capabilities.items())}}

    @classmethod
    def from_dict(cls, raw: Any) -> Decoded["CapabilitySet"]:
        return decode_document(raw, SCHEMA_VERSION, cls._build)

    @classmethod
    def _build(cls, r: Reader) -> "CapabilitySet":
        out = cls()
        for key, items in r.mapping("capabilities", required=True).items():
            if not isinstance(items, list):
                r.error("wrong_type", f"capabilities.{key}")
                continue
            for i, item in enumerate(items):
                cr = r.child(item, f"capabilities.{key}[{i}]")
                state = cr.enum("state", STATES)
                scope = cr.mapping("scope")
                for sk, sv in scope.items():
                    if sk not in SCOPE_KEYS or not (sv is None or isinstance(sv, str)):
                        cr.error("wrong_type", f"scope.{sk}")
                evidence = cr.string_list("evidence")
                if state:
                    out.add(Capability(key, state, _scope(scope), evidence))
        return out


@dataclass
class Requirement:
    key: str
    params: dict = field(default_factory=dict)
    alternatives: list = field(default_factory=list)   # [Requirement]: any one satisfies
    source: str | None = None

    def to_dict(self) -> dict:
        return {"key": self.key, "params": dict(self.params),
                "alternatives": [a.to_dict() for a in self.alternatives], "source": self.source}


def _applies(capability: Capability, context: dict) -> bool:
    """A capability applies when every scope field it names equals the evaluation context's."""
    return all(value is None or context.get(name) == value for name, value in capability.scope.items())


def _evaluate_one(req: Requirement, capability_set: CapabilitySet, context: dict) -> dict:
    found = [c for c in capability_set.capabilities.get(req.key, []) if _applies(c, context)]
    evidence = [e for c in found for e in c.evidence]
    states = {c.state for c in found}
    if not found:
        return {"key": req.key, "result": UNKNOWN, "matched": None, "evidence": []}
    if "conflicting" in states or ("supported" in states and "unsupported" in states):
        return {"key": req.key, "result": UNKNOWN, "matched": None, "evidence": evidence}
    if "supported" in states:
        return {"key": req.key, "result": SATISFIED,
                "matched": next(c for c in found if c.state == "supported"), "evidence": evidence}
    if "unsupported" in states:
        return {"key": req.key, "result": UNMET,
                "matched": next(c for c in found if c.state == "unsupported"), "evidence": evidence}
    return {"key": req.key, "result": UNKNOWN, "matched": None, "evidence": evidence}


class EvaluationResults(list):
    """The per-requirement results, plus the `inputs_revision` envelope they were computed from."""
    inputs_revision: dict


def evaluate(requirements: list, capability_set: CapabilitySet, *, scope: dict | None = None,
             revisions: dict | None = None) -> list[dict]:
    """One result per requirement: satisfied | unmet | unknown.

    `scope` is the evaluation context (host, slicer, generator, version, process). A requirement
    is satisfied if it, or any alternative, is satisfied; otherwise unknown if anything is
    unknown; otherwise unmet.
    """
    context = _scope(scope)
    results = EvaluationResults()
    results.inputs_revision = revision_envelope(
        {"capability_set": content_hash(capability_set.to_dict()),
         "requirements": [q.to_dict() for q in requirements], "scope": context}, revisions)
    for req in requirements:
        own = _evaluate_one(req, capability_set, context)
        if own["result"] == SATISFIED:
            results.append(own)
            continue
        options = [own] + [_evaluate_one(a, capability_set, context) for a in req.alternatives]
        satisfied = next((o for o in options if o["result"] == SATISFIED), None)
        if satisfied is not None:
            results.append({**satisfied, "key": req.key})
            continue
        evidence = [e for o in options for e in o["evidence"]]
        if any(o["result"] == UNKNOWN for o in options):
            results.append({"key": req.key, "result": UNKNOWN, "matched": None, "evidence": evidence})
        else:
            results.append({"key": req.key, "result": UNMET, "matched": own["matched"], "evidence": evidence})
    return results


def evaluation_to_document(results: list[dict]) -> dict:
    """The serialised evaluation: `{"inputs_revision": {...}, "results": [...]}`."""
    envelope = getattr(results, "inputs_revision", None)
    return {"inputs_revision": dict(envelope) if envelope else None, "results": evaluation_to_dict(results)}


def evaluation_to_dict(results: list[dict]) -> list[dict]:
    return [{"key": r["key"], "result": r["result"],
             "matched": r["matched"].to_dict() if r["matched"] else None, "evidence": list(r["evidence"])}
            for r in results]
