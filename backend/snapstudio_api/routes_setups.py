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
from snapstudio_core.adapters import registry, accessory_integration as ai
from snapstudio_core.foundation.decode import parse_json
from snapstudio_core.adapters import host as _host  # noqa: F401  (registers the host adapters)
from snapstudio_core.adapters.host import reader
from snapstudio_core.foundation import netguard
from snapstudio_core.foundation.observations import to_iso

from . import ext_routes
from . import request_validation as rv

#: Five host reads (one extra fixed-path read for an explicitly selected accessory); keep the whole handler inside ext_routes.HANDLER_BUDGET_S.
READ_TIMEOUT_S = 0.8
ACCESSORY_TIMEOUT_S = 0.55
MAX_REQUIREMENTS = 64
_KEY_RE = re.compile(r"^[A-Za-z0-9._~+/=\-]{1,256}$")
_PREFLIGHT_CODES = ("syntax", "off_network", "public_address", "unresolvable")

COVERAGE = ("Reads stock Moonraker, Paxx Moonraker and OctoPrint hosts. Accessories require explicit input; coverage is partial. Evidence: fixture-tested and mock-service-tested; no real printer "
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
    if data.get("accessory") is not None:
        return evaluate_accessory(data)
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
    adapters = [a.info.to_dict() for a in registry.all_adapters()]
    return 200, {"adapters": adapters, "coverage": COVERAGE + " Explicit accessory live reads and imported snapshots are available; logical mappings are never inferred."}


def evaluate_accessory(data: dict) -> tuple[int, dict]:
    raw = data['accessory']
    try:
        name, mode, mapping = ai.specification(raw)
    except ValueError as exc:
        raise rv.ValidationError(str(exc)) from None
    now = to_iso(time.time())
    if mode == 'live':
        # Fixed read-only upstream path at the explicitly configured origin. No key
        # is sent to the accessory; its authentication contract is not established.
        if raw.get('port') is None:
            raise rv.ValidationError('Enter the accessory service port explicitly.')
        # Validate every request field before any network I/O.
        _requirements(data)
        if data.get('host'):
            _host_url(data)
            _api_key(data)
        path = ai.LIVE_PATHS[name]
        attempted = []
        try:
            origin = _host_url({'host': raw.get('host'), 'port': raw.get('port')})
            attempted.append(path)
            reply = netguard.local_request('GET', origin + path, timeout=ACCESSORY_TIMEOUT_S,
                                          max_bytes=ai.MAX_PAYLOAD_BYTES)
        except netguard.NetguardRefused as exc:
            if exc.code in _PREFLIGHT_CODES:
                raise rv.ValidationError('That address is not on your local network or could not be resolved.') from None
            entry = {'label': name + ' explicit live read', 'status': 'unavailable',
                     'reason': str(exc), 'kind': 'accessory', 'variant': name, 'result': None}
            return 200, {'report': setup_view.evaluate([entry], requirements=_requirements(data)),
                         'topology': None, 'physical_host_read': None,
                         'read': {'status': 'unavailable', 'kind': 'accessory', 'variant': name,
                                  'adapter_id': name, 'reason': str(exc), 'requests': attempted,
                                  'retries': 0, 'notes': ['accessory read did not complete; no topology confirmed']}}
        payload = {'http_status': reply.status, 'body': parse_json(reply.body).value}
        requests = [path]
    else:
        payload, requests = raw['payload'], []
    adapter = registry.get(name)
    if adapter is None:
        raise rv.ValidationError('The selected accessory adapter is unavailable.')
    parsed = adapter.parse(payload, received_at=now, source_version=raw['source_version'])
    physical, host_summary = None, None
    if data.get('host'):
        res = reader.read_host(_host_url(data), api_key=_api_key(data), timeout=ACCESSORY_TIMEOUT_S)
        host_summary = res.to_dict()
        if res.status == 'ok' and res.adapter_id and res.bundle is not None:
            host_adapter = registry.get(res.adapter_id)
            if host_adapter is not None:
                physical = host_adapter.parse(res.bundle, received_at=now, source_version='host_bundle/1')
    try:
        parsed = ai.compose(parsed, physical, mapping, historical=mode == 'snapshot')
    except ValueError as exc:
        raise rv.ValidationError(str(exc)) from None
    entry = {'label': name + (' imported snapshot' if mode == 'snapshot' else ' explicit live read'),
             'status': 'ok' if parsed.ok else 'unavailable', 'reason': None,
             'kind': 'accessory', 'variant': name, 'result': parsed}
    report = setup_view.evaluate([entry], requirements=_requirements(data))
    if mapping is not None and parsed.ok:
        # The generic report describes upstream mappings. Do not attribute a
        # user-authored logical map to the device that supplied only lanes.
        report['entries'][0]['label'] += ' + your declared logical map'
        for capability in report['entries'][0]['capabilities']:
            if capability['key'] == 'logical_slots':
                capability['reason'] = f'You declared {len(mapping)} logical material slots; the device did not report this tool order.'
            elif capability['key'] == 'slot_mapping':
                capability['reason'] = 'Your explicit slot-to-lane declaration is shown. It is not a device-reported slot-to-head mapping.'
        limitation = report['legacy_limitation']
        limitation['reasons'] = [reason.replace('This setup reports', 'You declared', 1) if re.match(r'This setup reports \d+ logical slots,', reason) else reason for reason in limitation['reasons']]
    topology = parsed.topology.to_dict() if parsed.ok and parsed.topology else None
    return 200, {'report': report, 'topology': topology,
                 'read': {'status': entry['status'], 'kind': 'accessory', 'variant': name,
                          'adapter_id': name, 'reason': None, 'requests': requests,
                          'retries': 0, 'notes': ['explicit accessory; no inferred logical slots',
                                               'snapshot observations are historical' if mode == 'snapshot' else 'live read']},
                 'physical_host_read': host_summary}
