"""Which kind of host answered? Decided from reply bodies, never from a preset's `host_type`.

OctoPrint is identified by the body of `GET /api/version`. Moonraker's `octoprint_compat`
component answers the same endpoint with an OctoPrint-shaped body, so a Moonraker is told
apart by `GET /server/info` (its `moonraker_version`), which wins whenever it is present.
"""
from __future__ import annotations

from typing import Any

from . import moonraker_parse as mp

MOONRAKER = "moonraker"
OCTOPRINT = "octoprint"
UNKNOWN = "unknown"


def classify(api_version: Any, server_info: Any) -> str:
    """`moonraker` | `octoprint` | `unknown` from already-fetched bodies (either may be None)."""
    version = mp.result_of(server_info).get("moonraker_version")
    if isinstance(version, str) and version.strip():
        return MOONRAKER
    if isinstance(api_version, dict):
        text = api_version.get("text")
        if isinstance(text, str):
            lowered = text.lower()
            if "moonraker" in lowered:
                return MOONRAKER
            if lowered.startswith("octoprint"):
                return OCTOPRINT
    return UNKNOWN
