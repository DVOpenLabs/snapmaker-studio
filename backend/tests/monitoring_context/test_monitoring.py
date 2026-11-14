"""P8 monitoring tests 3-7 against an in-process 127.0.0.1 mock. Evidence label: mock-service-tested."""
import json

import pytest

from snapstudio_core import monitoring_context as mc
from tests.mocks.hosts.host_mocks import MockHost

STATUS = {"result": {"status": {"print_stats": {"filename": "demo.3mf", "state": "printing"}}}}
HISTORY = {"result": {"jobs": [{"filename": "demo.3mf", "status": "completed"}]}}


@pytest.fixture
def host():
    mock = MockHost({"/printer/objects/query": (200, STATUS), "/server/history/list": (200, HISTORY)}).start()
    yield mock
    mock.stop()


def port_of(mock):
    return mock.server_address[1]


def test_4_reads_are_two_bounded_gets_and_zero_control_requests(host):
    state = mc.read("127.0.0.1", port_of(host))
    last = mc.read_history("127.0.0.1", port_of(host))
    assert state["print_state"] == "printing" and last["last_job"]["outcome"] == "completed"
    assert sorted(host.paths()) == ["/printer/objects/query", "/server/history/list"]
    assert {r["method"] for r in host.requests} == {"GET"}
    control = ("/printer/print/", "/printer/emergency_stop", "/printer/gcode/script", "/printer/restart")
    assert not [p for p in host.paths() if p.startswith(control)]


def test_7_filename_match_is_unverified_and_never_claims_printing_this_file(host):
    result = mc.read("127.0.0.1", port_of(host))
    assert result["association"] == "unverified"
    assert "printing this file" not in json.dumps(result).lower()
    assert mc.read_history("127.0.0.1", port_of(host))["association"] == "unverified"


def test_unsupported_fields_remain_unknown():
    mock = MockHost({"/printer/objects/query": (200, {"result": {"status": {}}})}).start()
    try:
        result = mc.read("127.0.0.1", port_of(mock))
    finally:
        mock.stop()
    assert result["print_state"] == "unknown" and result["association"] == "unknown"
    assert result["filename"] is None


def test_6_camera_is_unknown_not_inferred(host):
    assert mc.read("127.0.0.1", port_of(host))["camera"]["state"] == "unknown"


def test_invalid_reply_is_unavailable_not_an_exception():
    mock = MockHost({"/printer/objects/query": (200, ["not", "an", "object"])}).start()
    try:
        result = mc.read("127.0.0.1", port_of(mock))
    finally:
        mock.stop()
    assert result["status"] == "unavailable" and result["camera"]["state"] == "unknown"


def test_5_missed_events_reconcile_from_current_status(host):
    # A caller last saw "paused"; the printer is now "printing". The transition path is unknown.
    current = mc.read("127.0.0.1", port_of(host))
    rec = mc.reconcile("paused", current)
    assert rec["state"] == "printing" and rec["reconciled_from_status"] is True
    assert rec["events"] == [{"kind": "state_changed", "from": "paused", "to": "printing", "source": "poll"}]
    assert rec["source"] == "polling" and rec["intermediate_states_known"] is False
    assert mc.reconcile("printing", current)["events"] == []
    assert mc.reconcile(None, current)["events"] == []
    assert mc.reconcile("printing", {"status": "unavailable"})["state"] == "unknown"


def test_connection_failure_is_a_refusal_not_a_hang():
    from snapstudio_core.foundation import netguard
    with pytest.raises(netguard.NetguardRefused):
        mc.read("8.8.8.8", 7125)                      # public address: refused before any dial


def test_invalid_port_rejected():
    with pytest.raises(ValueError):
        mc.read("127.0.0.1", 0)
    with pytest.raises(ValueError):
        mc.read("127.0.0.1", True)
