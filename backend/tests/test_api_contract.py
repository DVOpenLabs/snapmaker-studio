"""API contract guard: required response fields the frontend (desktop/src/api.ts)
relies on must not silently disappear. Shape/field-presence checks (not brittle
full snapshots). Hermetic — uses payloads that need no real mesh.
"""
import json
import threading
import urllib.request

from snapstudio_api.server import build_server


def _run(httpd):
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


def _post(port, route, payload, token, *, attempts=4):
    """One call, on one connection, retried when the machine has no port to spare.

    A socket per request is what made this suite fail intermittently on a machine
    with 14,000 connections held open by something else — a fact about the machine
    that says nothing about the contract being checked.
    """
    import http.client
    import time

    last = None
    for attempt in range(attempts):
        connection = None
        try:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request("POST", route, body=json.dumps(payload).encode(),
                               headers={"Content-Type": "application/json",
                                        "X-Auth-Token": token})
            return json.loads(connection.getresponse().read())
        except OSError as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
        finally:
            if connection is not None:
                connection.close()
    raise AssertionError(f"the machine would not give this test a port ({last})")


# route -> (payload, [required top-level keys])
_CONTRACT = {
    "/quality_check": ({"symptom": "stringing"}, ["result", "warnings"]),
    "/first_layer_check": ({"symptom": "not_stick"}, ["result", "warnings"]),
    "/model_search": ({"query": "x"}, ["results", "warnings"]),
    "/scale_options": ({"path": "none"}, ["available", "schema_version"]),
    "/print_failure_troubleshoot": ({"path": "none"},
        ["available", "summary", "findings", "troubleshooting_steps", "disclaimers"]),
    # Ecosystem advice must answer even for a file that cannot be read — the UI
    # shows the honest "could not read" summary rather than an error page.
    "/ecosystem_advice": ({"path": "none"},
        ["schema_version", "primary", "alternatives", "discover", "summary", "traits"]),
    "/project_traits": ({"path": "none"},
        ["schema_version", "readable", "format", "notes"]),
    "/project_cost": ({"path": "none"}, ["schema_version", "available", "basis"]),
    "/placement_check": ({"path": "none"}, ["schema_version", "available", "items"]),
    "/painted_preview": ({"path": "none"}, ["schema", "available", "state", "reason", "slots", "meshes", "instances"]),
    "/preflight": ({"path": "none"}, ["schema_version", "checks", "counts", "summary"]),
    "/fidelity": ({"original": "none", "prepared": "none"},
        ["schema_version", "available", "rows", "claims", "summary"]),
    "/color_plan": ({"path": "none"},
        ["schema_version", "available", "verdict", "headline", "summary"]),
    "/fix_history": ({}, ["schema_version", "entries"]),
    "/fix_original": ({"output": "none"}, ["available"]),
}


def test_api_response_contract():
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        for route, (payload, required) in _CONTRACT.items():
            body = _post(port, route, payload, token)
            for key in required:
                assert key in body, f"{route} dropped required field '{key}'"
        # print_failure findings carry the fields the UI renders
        pf = _post(port, "/print_failure_troubleshoot",
                   {"path": "none", "known_good_print": True}, token)
        assert pf["findings"], "expected at least one finding"
        for f in pf["findings"]:
            for key in ("id", "title", "explanation", "suggested_action"):
                assert key in f, f"finding dropped '{key}'"
    finally:
        httpd.shutdown()
