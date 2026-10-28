"""Routes of the Setups track: read one host and report what it says about the printer setup.

    POST /setups/evaluate   {host, port?, api_key?, requirements?}  -> {report, read}
    POST /setups/list       {}                                       -> {adapters, coverage}

The handlers only perform guarded GETs (through `netguard.local_request`, inside the host reader)
and never touch a printer-control path. The OctoPrint key lives in the request, in memory, for the
duration of the call: it is never stored, logged, or put in a response, an error or a job.
"""
from __future__ import annotations

import re
import time

from snapstudio_core import moonraker, setup_view
from snapstudio_core.adapters import registry
from snapstudio_core.adapters import host as _host  # noqa: F401  (registers the host adapters)
from snapstudio_core.adapters.host import reader
from snapstudio_core.foundation import netguard
from snapstudio_core.foundation.observations import to_iso

from . import ext_routes
from . import request_validation as rv

#: Five reads at most; keep the whole handler inside ext_routes.HANDLER_BUDGET_S.
READ_TIMEOUT_S = 0.8
MAX_REQUIREMENTS = 64
_KEY_RE = re.compile(r"^[A-Za-z0-9._~+/=\-]{1,256}$")
_PREFLIGHT_CODES = ("syntax", "off_network", "public_address", "unresolvable")

COVERAGE = ("Reads stock Moonraker, Paxx Moonraker and OctoPrint hosts. Accessory feeders are not "
            "covered by this build. Evidence: fixture-tested and mock-service-tested; no real printer "
            "has been read.")


def _host_url(data: dict) -> str:
    """The origin to read. Bad input is a 400; the address is syntax-checked, then checked for locality."""
    raw = rv.require_bounded_str(data, "host", 255)
    port = rv.require_port(data, "port", moonraker.DEFAULT_PORT)
    try:
        host = moonraker.validate_host(raw)
    except moonraker.InvalidHost as exc:
        raise rv.ValidationError(str(exc)) from None
    url = f"http://{host}:{port}"
    try:
        return netguard.require_local_url(url)
    except netguard.NetguardRefused as exc:
        if exc.code in _PREFLIGHT_CODES:
            raise rv.ValidationError("That address is not on your local network. Use the IP address "
                                     "or .local name of a device on your network.") from None
        raise


def _api_key(data: dict) -> str | None:
    key = data.get("api_key")
    if key is None or key == "":
        return None
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise rv.ValidationError("Invalid 'api_key'")
    return key


def _requirements(data: dict) -> list:
    raw = data.get("requirements")
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_REQUIREMENTS:
        raise rv.ValidationError("Invalid 'requirements'")
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise rv.ValidationError("Invalid 'requirements'")
        entry = {"index": i}
        for name in ("material", "colour"):
            value = rv.optional_bounded_str(item, name, 64)
            entry[name] = value
        out.append(entry)
    return out


@ext_routes.route("/setups/evaluate")
def evaluate(data: dict) -> tuple[int, dict]:
    url = _host_url(data)
    key = _api_key(data)
    requirements = _requirements(data)
    res = reader.read_host(url, api_key=key, timeout=READ_TIMEOUT_S)
    parsed = None
    if res.status == "ok" and res.adapter_id and res.bundle is not None:
        adapter = registry.get(res.adapter_id)
        if adapter is not None:
            parsed = adapter.parse(res.bundle, received_at=to_iso(time.time()),
                                   source_version="host_bundle/1")
    entry = {"label": "Host", "status": res.status if parsed is not None else
             ("unavailable" if res.status == "ok" else res.status),
             "reason": res.reason, "kind": res.kind, "variant": res.variant, "result": parsed}
    report = setup_view.evaluate([entry], requirements=requirements)
    topology = parsed.topology.to_dict() if parsed is not None and parsed.topology is not None else None
    return 200, {"report": report, "read": res.to_dict(), "topology": topology}


@ext_routes.route("/setups/list")
def list_adapters(data: dict) -> tuple[int, dict]:
    adapters = [a.info.to_dict() for a in registry.all_adapters("host")]
    return 200, {"adapters": adapters, "coverage": COVERAGE}
