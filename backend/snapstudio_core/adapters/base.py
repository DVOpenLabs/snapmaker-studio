"""Adapter contract: normalised foundation documents, never an exception.

An adapter declares who it is (`AdapterInfo`), which provider versions it understands
and how long its observations hold (`ttl_s`, mandatory). `Adapter.parse` takes a payload
(dict or JSON text/bytes) and always returns an `AdapterResult`:

- malformed input -> no documents, `errors` says why; nothing is raised;
- a `source_version` the adapter does not list -> every field unknown (no topology, no
  observations, no facts), `errors` says so; a guess is never made;
- a defect inside the adapter's own parser is caught and reported as `adapter_failed`
  (the exception text is dropped: it may carry payload content).

Adapters are network-free: this module imports no transport.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..foundation.decode import Decoded, ERROR, diag, is_finite_number, parse_json
from ..foundation.observations import Observation, ObservedAtTracker
from ..foundation.topology import Topology

SCHEMA_VERSION = "adapter_result/1"
KINDS = ("host", "accessory")


@dataclass(frozen=True)
class AdapterInfo:
    id: str
    kind: str                       # host | accessory
    versions_supported: tuple       # of str
    ttl_s: float                    # how long this adapter's observations hold; mandatory

    def problems(self) -> list:
        out = []
        if not isinstance(self.id, str) or not self.id.strip():
            out.append("id")
        if self.kind not in KINDS:
            out.append("kind")
        if (not isinstance(self.versions_supported, tuple)
                or not all(isinstance(v, str) and v for v in self.versions_supported)):
            out.append("versions_supported")
        if not is_finite_number(self.ttl_s) or self.ttl_s <= 0:
            out.append("ttl_s")
        return out

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind,
                "versions_supported": list(self.versions_supported), "ttl_s": self.ttl_s}


@dataclass
class AdapterResult:
    adapter_id: str
    source_version: str | None
    topology: Topology | None = None
    observations: list = field(default_factory=list)       # [Observation]
    material_facts: list = field(default_factory=list)     # [MaterialFact]
    unknowns: list = field(default_factory=list)           # names of things the payload did not establish
    diagnostics: list = field(default_factory=list)        # [Diagnostic], non-error context
    errors: list = field(default_factory=list)             # [Diagnostic], severity error

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "adapter_id": self.adapter_id,
                "source_version": self.source_version,
                "topology": self.topology.to_dict() if self.topology is not None else None,
                "observations": [o.to_dict() for o in self.observations],
                "material_facts": [f.to_dict() for f in self.material_facts],
                "unknowns": list(self.unknowns),
                "diagnostics": [d.to_dict() for d in self.diagnostics],
                "errors": [d.to_dict() for d in self.errors]}

    def to_decoded(self) -> Decoded:
        """The `Decoded` shape of the contract: value is None when any error exists."""
        value = None if self.errors else self
        return Decoded(SCHEMA_VERSION, value, list(self.errors) + list(self.diagnostics),
                       value is not None)


class Adapter:
    """Subclass, set `info`, implement `_parse`. Never override `parse`."""

    info: AdapterInfo

    def __init__(self) -> None:
        info = getattr(self, "info", None)
        problems = info.problems() if isinstance(info, AdapterInfo) else ["info"]
        if problems:
            raise ValueError("adapter info invalid: " + ",".join(problems))
        self._tracker = ObservedAtTracker()

    def observe(self, result: AdapterResult, *, observation_id: str, subject: dict, field: str,
                value: Any, snapshot_id: str | None, received_at: Any,
                source_kind: str = "live_query", revision: Any = None,
                provider_time: Any = None, ageing_ok: bool = False) -> Observation:
        """Build one observation with this adapter's declared `ttl_s` and add it to `result`."""
        source = {"provider_instance_id": self.info.id, "kind": self.info.kind,
                  "source_version": result.source_version, "snapshot_id": snapshot_id}
        obs, notes = self._tracker.observe(
            observation_id=observation_id, subject=subject, field=field, value=value, source=source,
            source_kind=source_kind, received_at=received_at, ttl_s=self.info.ttl_s,
            revision=revision, provider_time=provider_time, ageing_ok=ageing_ok)
        result.observations.append(obs)
        result.diagnostics.extend(notes)
        return obs

    def parse(self, payload: Any, *, received_at: Any, source_version: str | None) -> AdapterResult:
        result = AdapterResult(self.info.id, source_version if isinstance(source_version, str) else None)
        if source_version not in self.info.versions_supported:
            result.errors.append(diag("unknown_source_version", "source_version", ERROR))
            result.unknowns.append("all")
            return result
        data = payload
        if isinstance(payload, (str, bytes, bytearray)):
            parsed = parse_json(payload)
            if parsed.value is None:
                result.errors.extend(parsed.diagnostics or [diag("malformed_json", "", ERROR)])
                result.unknowns.append("all")
                return result
            data = parsed.value
        if not isinstance(data, (dict, list)):
            result.errors.append(diag("not_an_object", "", ERROR))
            result.unknowns.append("all")
            return result
        try:
            self._parse(data, received_at, result)
        except Exception:  # a parser defect must not escape; the message may carry payload text
            result.errors.append(diag("adapter_failed", "", ERROR))
        if result.errors:
            # Partial documents from a failed parse are not trustworthy: keep only the diagnostics.
            result.topology = None
            result.observations = []
            result.material_facts = []
            if "all" not in result.unknowns:
                result.unknowns.append("all")
        return result

    def _parse(self, data: Any, received_at: Any, result: AdapterResult) -> None:
        raise NotImplementedError
