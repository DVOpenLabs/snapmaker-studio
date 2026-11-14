"""Helpers shared by the accessory parsers. Parsers read upstream-published payloads only."""
from __future__ import annotations

import re

from ..base import AdapterResult
from ...foundation.decode import ERROR, NOTE, diag
from ...foundation.topology import FeederUnit, PhysicalToolhead, Topology, head_id

_EXTRUDER_RE = re.compile(r"^extruder(\d*)$")
_BAD_NAME = re.compile(r"[^A-Za-z0-9_.-]")


def unwrap(payload, result: AdapterResult, accept=(200,)):
    """Read the optional HTTP envelope {"http_status": n, "body": ...}.

    401/403 give an error diagnostic and nothing from the body is kept. A status outside
    `accept` is an error. Returns (body, status); body is None when nothing may be read.
    """
    if not isinstance(payload, dict) or "http_status" not in payload:
        return payload, 200
    status = payload.get("http_status")
    if status in (401, 403):
        result.errors.append(diag("unavailable", "http_status", ERROR))
        result.unknowns.append("all")
        return None, status
    if status not in accept or "body" not in payload:
        result.errors.append(diag("http_error", "http_status", ERROR))
        result.unknowns.append("all")
        return None, status
    return payload["body"], status


def invalid(result: AdapterResult, field: str = "body") -> None:
    result.errors.append(diag("malformed_payload", field, ERROR))
    result.unknowns.append("all")


def is_num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value \
        and value not in (float("inf"), float("-inf"))


def is_index(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def head_from_extruder(name):
    """Klipper extruder object name -> head index: `extruder` is 0, `extruderN` is N, else None."""
    match = _EXTRUDER_RE.match(name) if isinstance(name, str) else None
    if not match:
        return None
    return int(match.group(1)) if match.group(1) else 0


def safe_name(value: str) -> str:
    cleaned = _BAD_NAME.sub("_", str(value)).strip("._-")
    return cleaned or "unit"


def build_topology(adapter, result: AdapterResult, received_at, *, heads, units, complete,
                   observed_at=None, evidence=None) -> Topology:
    """`heads` is a list of (index, nozzle_mm|None); `units` a list of FeederUnit."""
    result.topology = Topology(
        snapshot_id=f"{adapter.info.id}:{received_at}", received_at=str(received_at),
        observed_at=observed_at, heads=[PhysicalToolhead(head_id(i), i, nozzle_mm=n) for i, n in heads],
        units=units, complete=bool(complete and heads), evidence=evidence or ["fixture-tested"])
    return result.topology


def observe_lane_states(adapter, result: AdapterResult, received_at, prefix: str, provider_time=None) -> None:
    for unit in result.topology.units:
        for lane in unit.lanes:
            adapter.observe(result, observation_id=f"{prefix}-{unit.id}-{lane.index}-state",
                            subject={"kind": "lane", "id": lane.id}, field="state", value=lane.state,
                            snapshot_id=result.topology.snapshot_id, received_at=received_at,
                            provider_time=provider_time)


def note(result: AdapterResult, code: str, field: str = "") -> None:
    result.diagnostics.append(diag(code, field, NOTE))


def unit_of(uid: str, kind: str, result: AdapterResult, lanes) -> FeederUnit:
    return FeederUnit(uid, kind, result.source_version, lanes)
