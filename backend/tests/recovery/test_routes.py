"""Recovery and monitoring routes through the real HTTP server. Evidence label: mock-service-tested."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from snapstudio_api import ext_routes
from snapstudio_api.server import build_server
from tests.mocks.hosts.host_mocks import MockHost

SENTINEL = "SENTINEL-KEY-9f3a"
STATUS = {"result": {"status": {"print_stats": {"filename": "demo.3mf", "state": "printing"}}}}


@pytest.fixture
def api():
    httpd, token = build_server(port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]

    def post(path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                     method="POST", headers={"X-Auth-Token": token, "X-Api-Key": SENTINEL,
                                                             "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    yield post
    httpd.shutdown()
    httpd.server_close()


def test_routes_register_within_owned_prefixes():
    ext_routes.load_all()
    for path in ("/monitoring/read", "/monitoring/history", "/recovery/checkpoint", "/recovery/restore"):
        assert path in ext_routes.ROUTES


def test_checkpoint_then_restore_over_http_and_no_secret_echo(api):
    status, text = api("/recovery/restore", {})
    assert status == 200 and json.loads(text)["missing_checkpoint"] is True
    status, text = api("/recovery/checkpoint", {"workspace": {"name": "demo", "token": SENTINEL},
                                                "jobs": [{"job_id": "j1", "state": "running"}]})
    assert status == 200 and SENTINEL not in text
    status, text = api("/recovery/restore", {})
    body = json.loads(text)
    assert status == 200 and SENTINEL not in text
    assert body["jobs"][0]["state"] == "interrupted" and body["fresh_read_required"] is True


def test_checkpoint_rejects_malformed_content(api):
    assert api("/recovery/checkpoint", {"workspace": []})[0] == 400
    assert api("/recovery/checkpoint", {"files": "no"})[0] == 400


def test_monitoring_route_reads_mock_with_reconciliation_and_no_control(api):
    mock = MockHost({"/printer/objects/query": (200, STATUS)}).start()
    try:
        status, text = api("/monitoring/read", {"host": "127.0.0.1", "port": mock.server_address[1],
                                                "previous_state": "paused"})
        requests = list(mock.requests)
    finally:
        mock.stop()
    body = json.loads(text)
    assert status == 200 and SENTINEL not in text
    assert body["association"] == "unverified" and body["camera"]["state"] == "unknown"
    assert body["reconciliation"]["events"][0]["to"] == "printing"
    assert [(r["method"], r["path"]) for r in requests] == [("GET", "/printer/objects/query")]
    assert "x-api-key" not in requests[0]["headers"]        # the app's own header is never forwarded


def test_monitoring_route_refuses_public_host_and_bad_input(api):
    assert api("/monitoring/read", {"host": "8.8.8.8"})[0] == 422
    assert api("/monitoring/read", {"host": "127.0.0.1", "previous_state": 5})[0] == 400
    assert api("/monitoring/history", {})[0] == 400


def test_malformed_monitoring_host_is_a_400_not_a_500(api):
    for host in ("evil.com/path", "user@host", "http://x"):
        code, _ = api("/monitoring/read", {"host": host})
        assert code == 400, host
        code, _ = api("/monitoring/history", {"host": host})
        assert code == 400, host


def test_checkpoint_with_stale_expected_revision_is_refused(api):
    code, body = api("/recovery/checkpoint", {"workspace": {"project": "a"}})
    assert code == 200
    revision = json.loads(body)["revision"]
    code, _ = api("/recovery/checkpoint", {"workspace": {"project": "b"}, "expected_revision": revision})
    assert code == 200
    code, _ = api("/recovery/checkpoint", {"workspace": {"project": "c"}, "expected_revision": revision})
    assert code == 422
    code, _ = api("/recovery/checkpoint", {"workspace": {}, "expected_revision": "x"})
    assert code == 400
