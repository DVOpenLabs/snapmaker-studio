"""Bounded, read-only monitoring context from configured local Moonraker hosts.

Two GETs only, both through `foundation.netguard.local_request`: `/printer/objects/query` (state)
and `/server/history/list` (last job). There is no websocket: "events" are derived by comparing
polled statuses, so a transition that happens between two polls is never seen, only inferred.
Nothing here sends a control request. A filename match is never proof of which artifact runs.
"""

from __future__ import annotations

import json

from snapstudio_core import moonraker
from snapstudio_core.foundation import netguard

READ_TIMEOUT_S = 1.5
MAX_RESPONSE_BYTES = 256 * 1024
ASSOCIATION_NOTE = "Filename match is unverified; Studio has not confirmed the local artifact."
# Moonraker camera context lives behind endpoints this module does not read.
CAMERA_UNKNOWN = {"state": "unknown", "reason": "camera_context_not_read"}


def _origin(host: str, port: int) -> str:
    checked_host = moonraker.validate_host(host)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("invalid port")
    return f"http://{checked_host}:{port}"


def _get(origin: str, path_and_query: str, resolver) -> dict | None:
    result = netguard.local_request("GET", origin + path_and_query, origin=origin,
                                    timeout=READ_TIMEOUT_S, max_bytes=MAX_RESPONSE_BYTES,
                                    resolver=resolver)
    if not 200 <= result.status < 300:
        return None
    try:
        data = json.loads(result.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def read(host: str, port: int = moonraker.DEFAULT_PORT, *, resolver=None) -> dict:
    """One bounded status GET. Unsupported or absent fields stay unknown."""
    origin = _origin(host, port)
    data = _get(origin, "/printer/objects/query?print_stats&virtual_sdcard", resolver)
    if data is None:
        return {"status": "unavailable", "reason": "invalid_reply", "camera": dict(CAMERA_UNKNOWN)}
    result = data.get("result")
    values = result.get("status") if isinstance(result, dict) else None
    stats = values.get("print_stats") if isinstance(values, dict) else None
    filename = stats.get("filename") if isinstance(stats, dict) else None
    state = stats.get("state") if isinstance(stats, dict) else None
    filename = filename if isinstance(filename, str) and filename else None
    return {"status": "ok", "print_state": state if isinstance(state, str) else "unknown",
            "filename": filename, "association": "unverified" if filename else "unknown",
            "camera": dict(CAMERA_UNKNOWN), "note": ASSOCIATION_NOTE}


def read_history(host: str, port: int = moonraker.DEFAULT_PORT, *, resolver=None) -> dict:
    """One bounded GET of the most recent job record. Never more than one entry is kept."""
    origin = _origin(host, port)
    data = _get(origin, "/server/history/list?limit=1&order=desc", resolver)
    if data is None:
        return {"status": "unavailable", "reason": "invalid_reply"}
    result = data.get("result")
    jobs = result.get("jobs") if isinstance(result, dict) else None
    job = jobs[0] if isinstance(jobs, list) and jobs and isinstance(jobs[0], dict) else None
    if job is None:
        return {"status": "ok", "last_job": None}
    name, outcome = job.get("filename"), job.get("status")
    name = name if isinstance(name, str) and name else None
    return {"status": "ok", "association": "unverified" if name else "unknown",
            "last_job": {"filename": name, "outcome": outcome if isinstance(outcome, str) else "unknown"},
            "note": ASSOCIATION_NOTE}


def reconcile(previous_state: str | None, current: dict) -> dict:
    """Derive events from polling: compare the last state a caller saw with a fresh status.

    The fresh status is the truth. When the state differs, the states in between (if any) are
    unknown, so the result says so instead of inventing a sequence.
    """
    state = current.get("print_state", "unknown") if current.get("status") == "ok" else "unknown"
    events = []
    if isinstance(previous_state, str) and previous_state != state:
        events.append({"kind": "state_changed", "from": previous_state, "to": state, "source": "poll"})
    return {"state": state, "events": events, "source": "polling",
            "intermediate_states_known": False,
            "reconciled_from_status": True}
