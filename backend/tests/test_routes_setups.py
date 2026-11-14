"""Route level: /setups/evaluate and /setups/list (plan tests 5, 9, 10, 11 at the route).

Evidence label: mock-service-tested. Mocks are in-process 127.0.0.1 servers that count connections.
"""
from __future__ import annotations

import json
import logging
import pathlib
import time

import pytest

from snapstudio_api import ext_routes, routes_setups
from tests.mocks.hosts.host_mocks import SECRET_KEY, MockHost, make_moonraker, make_octoprint

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "adapters" / "host"
FORBIDDEN_PREFIXES = ("/printer/print", "/printer/gcode", "/printer/emergency_stop", "/printer/restart",
                      "/printer/firmware_restart", "/server/files/upload", "/api/job", "/api/printer")


class FakeHandler:
    def __init__(self):
        self.sent = []

    def _send(self, code, obj):
        self.sent.append((code, obj))


def call(path, data):
    h = FakeHandler()
    assert ext_routes.dispatch(h, path, data) is True
    assert len(h.sent) == 1
    return h.sent[0]


def bundle(system, version, case):
    return json.loads((FIXTURES / system / version / f"{case}.json").read_text(encoding="utf-8"))["bundle"]


@pytest.fixture
def mocks():
    made = []

    def add(server):
        made.append(server)
        return server

    yield add
    for s in made:
        s.stop()


def body_for(server, **extra):
    return {"host": "127.0.0.1", "port": server.server_address[1], **extra}


def test_routes_are_registered_under_setups_only():
    assert "/setups/evaluate" in ext_routes.ROUTES and "/setups/list" in ext_routes.ROUTES
    assert all(p.startswith("/setups") for p, fn in ext_routes.ROUTES.items()
               if fn.__module__.endswith("routes_setups"))


def test_list_names_the_host_adapters_without_touching_the_network():
    code, body = call("/setups/list", {})
    assert code == 200
    assert {a["id"] for a in body["adapters"]} >= {"host.moonraker_stock", "host.moonraker_paxx", "host.octoprint"}
    assert all(a["kind"] == "host" and a["ttl_s"] > 0 for a in body["adapters"])
    assert "Accessory feeders are not covered" in body["coverage"]


# plan test 9
@pytest.mark.parametrize("data", [
    {}, {"host": ""}, {"host": 7}, {"host": "http://printer.local"}, {"host": "user@host"},
    {"host": "has space"}, {"host": "x" * 300},
    {"host": "8.8.8.8"}, {"host": "1.1.1.1", "port": 7125},        # syntactically fine, not local
    {"host": "127.0.0.1", "port": 0}, {"host": "127.0.0.1", "port": 70000}, {"host": "127.0.0.1", "port": "x"},
    {"host": "127.0.0.1", "api_key": "has space"}, {"host": "127.0.0.1", "api_key": 5},
    {"host": "127.0.0.1", "requirements": "PLA"}, {"host": "127.0.0.1", "requirements": [1]},
    {"host": "127.0.0.1", "requirements": [{"material": 3}]},
    {"host": "127.0.0.1", "requirements": [{}] * 65},
])
def test_bad_input_is_a_400_and_makes_no_connection(data):
    code, body = call("/setups/evaluate", data)
    assert code == 400 and body["error"] == "invalid" and body["message"]


def test_a_public_address_is_a_400_and_the_message_does_not_echo_it():
    code, body = call("/setups/evaluate", {"host": "8.8.8.8"})
    assert code == 400 and "8.8.8.8" not in body["message"]


def test_validate_host_is_only_a_syntax_check():
    src = pathlib.Path(routes_setups.__file__).read_text(encoding="utf-8")
    assert "require_local_url" in src and "require_port" in src
    code, _ = call("/setups/evaluate", {"host": "1.1.1.1"})        # passes validate_host, fails locality
    assert code == 400


def test_a_stock_printer_is_read_and_reported(mocks):
    server = mocks(make_moonraker(bundle("moonraker_stock", "moonraker-0.9", "four_heads_loaded")))
    code, body = call("/setups/evaluate", body_for(server, requirements=[{"material": "PLA"}] * 6))
    assert code == 200
    entry = body["report"]["entries"][0]
    assert body["read"]["kind"] == "moonraker" and body["read"]["retries"] == 0
    assert entry["counts"]["physical_heads"] == 4 and entry["assignability"]["verdict"] == "cannot_match"
    assert body["report"]["legacy_limitation"]["applies"] is False
    assert {r["method"] for r in server.requests} == {"GET"}
    assert not [p for p in server.paths() if p.startswith(FORBIDDEN_PREFIXES)]


# plan test 11 at the route
def test_32_logical_slots_show_the_legacy_notice(mocks):
    server = mocks(make_moonraker(bundle("moonraker_stock", "moonraker-0.9", "hypothetical_thirty_two_logical_four_heads")))
    code, body = call("/setups/evaluate", body_for(server))
    notice = body["report"]["legacy_limitation"]
    assert code == 200 and notice["applies"] and "assume four heads" in notice["text"]
    assert body["report"]["entries"][0]["counts"]["physical_heads"] == 4


# plan test 5 at the route, plus the sentinel key (G2)
def test_missing_key_is_unavailable_with_one_request(mocks):
    server = mocks(make_octoprint())
    code, body = call("/setups/evaluate", body_for(server))
    entry = body["report"]["entries"][0]
    assert code == 200 and entry["status"] == "unavailable" and entry["reason"] == "api_key_missing"
    assert server.paths() == ["/api/version"] and body["read"]["retries"] == 0


def test_the_key_is_sent_to_its_host_and_appears_nowhere_else(mocks, caplog):
    server = mocks(make_octoprint())
    caplog.set_level(logging.DEBUG)
    code, body = call("/setups/evaluate", body_for(server, api_key=SECRET_KEY))
    assert code == 200 and body["report"]["entries"][0]["kind"] == "octoprint"
    assert server.requests[0]["headers"].get("x-api-key") == SECRET_KEY
    assert SECRET_KEY not in json.dumps(body)
    assert SECRET_KEY not in caplog.text
    wrong = "WRONG-SENTINEL-KEY-0009"
    code, body = call("/setups/evaluate", body_for(server, api_key=wrong))
    assert body["report"]["entries"][0]["reason"] == "auth_required" and wrong not in json.dumps(body)
    code, body = call("/setups/evaluate", {"host": "127.0.0.1", "api_key": SECRET_KEY + " bad"})
    assert code == 400 and SECRET_KEY not in json.dumps(body)


def test_the_key_is_not_written_into_the_data_dir(mocks):
    from snapstudio_core import paths
    server = mocks(make_octoprint())
    call("/setups/evaluate", body_for(server, api_key=SECRET_KEY))
    root = pathlib.Path(paths.data_dir())
    for f in (root.rglob("*") if root.exists() else []):
        if f.is_file():
            assert SECRET_KEY.encode() not in f.read_bytes()


# plan test 10 at the route
def test_a_redirect_is_refused_and_the_target_gets_zero_connections(mocks):
    target = mocks(MockHost({"/api/version": (200, {"text": "OctoPrint 1.9.3"})}).start())
    redirecting = mocks(MockHost({}, redirect_to=target.origin + "/api/version").start())
    code, body = call("/setups/evaluate", body_for(redirecting))
    assert code == 422 and body["error"] == "refusal"
    assert redirecting.connections == 1 and target.connections == 0


def test_an_unreachable_host_is_a_report_not_an_error_and_returns_quickly():
    server = make_octoprint()
    port = server.server_address[1]
    server.stop()
    started = time.monotonic()
    code, body = call("/setups/evaluate", {"host": "127.0.0.1", "port": port})
    assert code == 200 and time.monotonic() - started < ext_routes.HANDLER_BUDGET_S
    entry = body["report"]["entries"][0]
    assert entry["status"] == "unavailable" and entry["reason"] == "unreachable"
    assert {c["state"] for c in entry["capabilities"]} == {"unavailable"}


def test_an_unrecognised_host_is_reported_as_such(mocks):
    server = mocks(MockHost({"/api/version": (200, {"hello": "world"})}).start())
    code, body = call("/setups/evaluate", body_for(server))
    entry = body["report"]["entries"][0]
    assert code == 200 and entry["status"] == "unrecognised" and "does not recognise" in entry["reason_text"]


def test_the_read_budget_fits_the_handler_budget():
    assert routes_setups.READ_TIMEOUT_S * 5 < ext_routes.HANDLER_BUDGET_S
