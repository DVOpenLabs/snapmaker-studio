"""Host layer: bounded read-only GETs through `netguard.local_request`, then hand over a bundle.

This is the only place under `adapters/host` that touches the network, and it does so only via
`netguard`. Every request is a GET, bounded in size and time, never retried, and carries the
OctoPrint key (when the caller supplied one) only to the configured origin.

Policy:
- `NetguardRefused` for a safety reason (redirect, public address, off network, bad path ...)
  propagates: the route turns it into a refusal. A transport failure (`network`, `deadline`,
  `unavailable`, `protocol`, `tls`) is reported as `unavailable`, not raised.
- 401 / 403 on any read -> `unavailable` (`auth_required`, or `api_key_missing` when no key was
  supplied). The request is not repeated and no retry is recorded.
- Kind is decided from reply bodies (`classify`), never from a preset `host_type`.
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from ...foundation import netguard
from ...foundation.decode import parse_json
from . import classify as cl
from . import moonraker_parse as mp

MAX_REPLY_BYTES = 1024 * 1024
_TRANSPORT_CODES = ("network", "deadline", "unavailable", "protocol", "tls", "too_large")

ADAPTER_IDS = {"stock": "host.moonraker_stock", "paxx": "host.moonraker_paxx"}
OCTOPRINT_ADAPTER_ID = "host.octoprint"


@dataclass
class HostRead:
    status: str                       # ok | unavailable | unrecognised
    kind: str | None = None           # moonraker | octoprint | unknown
    variant: str | None = None        # stock | paxx (moonraker only)
    adapter_id: str | None = None
    reason: str | None = None
    bundle: dict | None = None
    requests: list = field(default_factory=list)     # paths asked, in order (no query, no secrets)
    retries: int = 0                                   # always 0: a failed read is never repeated
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"status": self.status, "kind": self.kind, "variant": self.variant,
                "adapter_id": self.adapter_id, "reason": self.reason, "requests": list(self.requests),
                "retries": self.retries, "notes": list(self.notes)}


class _Auth(Exception):
    pass


class _Reader:
    def __init__(self, origin: str, api_key: str | None, timeout: float) -> None:
        self.origin = origin
        self.headers = {"X-Api-Key": api_key} if api_key else {}
        self.has_key = bool(api_key)
        self.timeout = timeout
        self.requests: list = []

    def get(self, path: str) -> tuple[int | None, Any]:
        """(status, parsed JSON or None). Transport failure -> (None, None). 401/403 raises `_Auth`."""
        self.requests.append(path.split("?", 1)[0])
        try:
            reply = netguard.local_request(
                "GET", self.origin + path, headers=self.headers, timeout=self.timeout,
                max_bytes=MAX_REPLY_BYTES, secret_headers=("x-api-key",), origin=self.origin)
        except netguard.NetguardRefused as exc:
            if exc.code in _TRANSPORT_CODES:
                return None, None
            raise
        if reply.status in (401, 403):
            raise _Auth()
        if not 200 <= reply.status < 300 or not reply.body:
            return reply.status, None
        return reply.status, parse_json(reply.body).value


def read_host(url: str, *, api_key: str | None = None, timeout: float = 3.0,
              variant_hint: str | None = None) -> HostRead:
    """Identify the host at `url` and fetch the bundle its adapter reads.

    `url` is a bare origin such as `http://192.168.1.50:7125`; any path in it is ignored.
    Raises `NetguardRefused` when the address is not on the user's own network.
    """
    checked = netguard.require_local_url(url)
    parts = urllib.parse.urlsplit(checked)
    origin = f"{parts.scheme}://{parts.netloc}"
    rd = _Reader(origin, api_key, timeout)
    out = HostRead("unavailable")
    try:
        try:
            return _read(rd, out, variant_hint)
        finally:
            out.requests = list(rd.requests)
    except _Auth:
        out.status = "unavailable"
        out.reason = "auth_required" if rd.has_key else "api_key_missing"
        out.bundle = None
        return out


def _read(rd: _Reader, out: HostRead, variant_hint: str | None) -> HostRead:
    status, api = rd.get("/api/version")
    if status is None:                   # transport failure: nothing answered, do not ask again
        out.reason = "unreachable"
        return out
    _, server_info = rd.get("/server/info")
    kind = cl.classify(api, server_info)
    out.kind = kind
    if kind == cl.UNKNOWN:
        out.status = "unrecognised"
        out.reason = "not_moonraker_or_octoprint"
        return out
    if kind == cl.OCTOPRINT:
        out.status, out.adapter_id = "ok", OCTOPRINT_ADAPTER_ID
        out.bundle = {"api_version": api}
        return out
    bundle: dict = {"server_info": server_info}
    if isinstance(api, dict):
        bundle["api_version"] = api
    for key, path in (("objects_list", "/printer/objects/list"),
                      ("print_task_config", "/printer/objects/query?print_task_config"),
                      ("system_info", "/machine/system_info")):
        got_status, body = rd.get(path)
        if body is not None:
            bundle[key] = body
        else:
            out.notes.append(f"{key}_not_read")
    cfg = mp.print_task_config(bundle.get("print_task_config")) or {}
    variant = variant_hint if variant_hint in ADAPTER_IDS else ("paxx" if "filament_spool_id" in cfg else "stock")
    out.status, out.variant, out.adapter_id, out.bundle = "ok", variant, ADAPTER_IDS[variant], bundle
    return out
