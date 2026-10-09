"""The /scene/* HTTP surface: authentication, validation, status codes, pre-serialized body."""
import http.client
import json
import threading
import time

import pytest

from snapstudio_api import scene_jobs as sj
from snapstudio_api.server import build_server
from snapstudio_core import scene_limits as L
from tests import scene_fixtures as fx
from tests.test_scene_contract import assert_valid, sub_validator


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    sj.reset_default_for_tests()
    httpd, token = build_server()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1], token
    httpd.shutdown()
    httpd.server_close()
    sj.reset_default_for_tests()


def call(port, route, payload, token, *, raw=False):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Auth-Token"] = token
        conn.request("POST", route, body=json.dumps(payload).encode(), headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        assert resp.getheader("Content-Length") == str(len(body))
        assert resp.getheader("Content-Type") == "application/json"
        return resp.status, (body if raw else json.loads(body))
    finally:
        conn.close()


def poll(port, token, job_id, *states, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        code, body = call(port, "/scene/status", {"job_id": job_id}, token)
        assert code == 200
        if body["state"] in states:
            return body
        time.sleep(0.02)
    raise AssertionError("timeout")


def test_every_scene_route_requires_the_token(server, tmp_path):
    port, token = server
    for route in sj.ROUTES:
        assert call(port, route, {}, None)[0] == 401
        assert call(port, route, {}, "wrong-token")[0] == 401


def test_full_flow_returns_the_exact_serialized_scene(server, tmp_path):
    port, token = server
    path = fx.bambu_project(tmp_path / "p.3mf", parts=2, items=[("100", fx.tf(10, 10, 0))], plates=[(1, [("100", 0)])])
    code, started = call(port, "/scene/start", {"path": str(path), "request_id": "req-flow-0001"}, token)
    assert code == 200 and not list(sub_validator("job_start").iter_errors(started))
    status = poll(port, token, started["job_id"], "succeeded")
    assert not list(sub_validator("job_status").iter_errors(status))
    code, raw = call(port, "/scene/result", {"job_id": started["job_id"], "expected_revision": status["revision"]}, token, raw=True)
    assert code == 200
    sc = json.loads(raw)
    assert_valid(sc)
    assert raw == json.dumps(sc, separators=(",", ":")).encode()      # compact, serialized once, no re-dump
    assert len(raw) <= L.MAX_RESPONSE_BYTES


def test_error_statuses_and_bodies(server, tmp_path):
    port, token = server
    err = sub_validator("error_response")
    cases = [
        ("/scene/start", {"request_id": "req-err-00001"}, 400, "INVALID_REQUEST"),
        ("/scene/start", {"path": str(tmp_path / "nope.3mf"), "request_id": "req-err-00001"}, 400, "INVALID_REQUEST"),
        ("/scene/start", {"path": "x.3mf", "request_id": "short"}, 400, "INVALID_REQUEST"),
        ("/scene/start", {"path": "x.3mf", "request_id": "has spaces in it!"}, 400, "INVALID_REQUEST"),
        ("/scene/start", {"path": str(tmp_path / "a.obj"), "request_id": "req-err-00002"}, 422, "UNSUPPORTED_FORMAT"),
        ("/scene/status", {}, 400, "INVALID_REQUEST"),
        ("/scene/status", {"job_id": "0" * 32}, 404, "EXPIRED"),
        ("/scene/result", {"job_id": "0" * 32}, 404, "EXPIRED"),
        ("/scene/result", {"job_id": "0" * 32, "expected_revision": "nothex"}, 400, "INVALID_REQUEST"),
        ("/scene/cancel", {"job_id": "0" * 32}, 404, "EXPIRED"),
    ]
    (tmp_path / "a.obj").write_text("v")
    for route, payload, status, code in cases:
        got, body = call(port, route, payload, token)
        assert (got, body["error"]) == (status, code), (route, payload, got, body)
        assert not list(err.iter_errors(body))


def test_failed_job_result_is_422_and_cancelled_is_409(server, tmp_path):
    port, token = server
    bad = tmp_path / "bad.3mf"
    bad.write_bytes(b"junk" * 50)
    _, started = call(port, "/scene/start", {"path": str(bad), "request_id": "req-bad-00001"}, token)
    poll(port, token, started["job_id"], "failed")
    code, body = call(port, "/scene/result", {"job_id": started["job_id"]}, token)
    assert (code, body["error"]) == (422, "INVALID_ARCHIVE")
    ok = fx.plain_cube_3mf(tmp_path / "ok.3mf")
    _, second = call(port, "/scene/start", {"path": str(ok), "request_id": "req-ok-000001"}, token)
    code, status = call(port, "/scene/cancel", {"job_id": second["job_id"]}, token)
    assert code == 200 and status["state"] in ("cancelled", "succeeded")
    if status["state"] == "cancelled":
        code, body = call(port, "/scene/result", {"job_id": second["job_id"]}, token)
        assert (code, body["error"]) == (409, "CANCELLED")


def test_request_id_conflict_and_idempotency_over_http(server, tmp_path):
    port, token = server
    a = fx.plain_cube_3mf(tmp_path / "a.3mf")
    b = fx.plain_cube_3mf(tmp_path / "b.3mf", size=11)
    _, one = call(port, "/scene/start", {"path": str(a), "request_id": "req-same-0001"}, token)
    _, again = call(port, "/scene/start", {"path": str(a), "request_id": "req-same-0001"}, token)
    assert one["job_id"] == again["job_id"]
    code, body = call(port, "/scene/start", {"path": str(b), "request_id": "req-same-0001"}, token)
    assert (code, body["error"], body["reason"]) == (409, "INVALID_REQUEST", "request_id reused for another path")


def test_not_ready_and_wedged_over_http(server, tmp_path, monkeypatch):
    port, token = server
    gate = threading.Event()
    started = threading.Event()

    def stuck(path, revision, ctl):
        started.set()
        gate.wait(10)
        return b"{}"
    jobs = sj.SceneJobs(builder=stuck, wedge_grace=0.2)
    monkeypatch.setattr(sj, "_default", jobs)
    path = fx.plain_cube_3mf(tmp_path / "c.3mf")
    _, a = call(port, "/scene/start", {"path": str(path), "request_id": "req-wedge-001"}, token)
    started.wait(5)
    code, body = call(port, "/scene/result", {"job_id": a["job_id"]}, token)
    assert (code, body["error"], body["state"]) == (409, "NOT_READY", "running")
    call(port, "/scene/cancel", {"job_id": a["job_id"]}, token)
    time.sleep(0.4)
    code, body = call(port, "/scene/start", {"path": str(path), "request_id": "req-wedge-002"}, token)
    assert (code, body["error"]) == (503, "WORKER_WEDGED")
    gate.set()
    for _ in range(200):
        if not jobs.wedged():
            break
        time.sleep(0.02)
    code, _ = call(port, "/scene/start", {"path": str(path), "request_id": "req-wedge-003"}, token)
    assert code == 200
    jobs.close()


def test_other_routes_still_behave(server):
    port, token = server
    assert call(port, "/definitely_not_a_route", {}, token)[0] == 404


@pytest.mark.parametrize("body", [[1, 2], "text", 7, None, [], True])
def test_a14_a_non_object_json_body_is_a_400_not_a_500(server, body):
    port, token = server
    for route in sj.ROUTES:
        code, resp = call(port, route, body, token)
        assert code == 400 and resp["error"] == "INVALID_REQUEST", (route, body, code, resp)
