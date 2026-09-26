import json
import struct
import threading
import time
import urllib.request
import urllib.error
from snapstudio_api import service
from snapstudio_api.server import build_server
from snapstudio_core.stl_wrap import wrap_stl


def _request(port, route, payload, token, *, method="POST", attempts=4):
    """One HTTP call, retried when the machine has no source port to spare.

    These tests open a loopback connection per request. On a machine whose
    dynamic port range is busy — one here had 14,000 connections held open by
    Docker Desktop — that intermittently fails with WinError 10048, which says
    nothing about the code under test. The retry keeps the suite reporting on
    Studio rather than on the machine it happens to be running on.
    """
    import http.client

    last = None
    for attempt in range(attempts):
        connection = None
        try:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            body = json.dumps(payload).encode() if payload is not None else None
            headers = {"Content-Type": "application/json"}
            if token:
                headers["X-Auth-Token"] = token
            connection.request(method, route, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else {})
        except OSError as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
        finally:
            if connection is not None:
                connection.close()
    raise AssertionError(f"the machine would not give this test a port ({last})")


def _poll_until_finished(get_status, timeout=15.0):
    """Poll a batch status callable until its result is finished or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = get_status()
        res = (st or {}).get("result")
        if st and st.get("status") in ("done", "error") and res and res.get("finished"):
            return st
        time.sleep(0.05)
    raise AssertionError("batch did not finish in time")


def _bin_tetra():
    head = b"\x00" * 80 + struct.pack("<I", 2)
    for v1, v2, v3 in [((0, 0, 0), (10, 0, 0), (0, 10, 0)),
                       ((0, 0, 0), (0, 10, 0), (0, 0, 10))]:
        head += struct.pack("<12fH", 0, 0, 0, *v1, *v2, *v3, 0)
    return head


def _sample_u1(tmp_path):
    stl = tmp_path / "cube.stl"; stl.write_bytes(_bin_tetra())
    out = tmp_path / "cube_U1.3mf"
    wrap_stl(str(stl)).save(out)
    return out


# ---- adapter functions (no network) ----
def test_service_health():
    h = service.health()
    assert h["status"] == "ok" and h["api_version"] == "api/1"


def test_service_doctor(tmp_path):
    out = _sample_u1(tmp_path)
    d = service.doctor(str(out))
    assert d["verdict"] == "READY" and d["is_compatible"] is True


def test_service_insights_stl(tmp_path):
    stl = tmp_path / "cube.stl"; stl.write_bytes(_bin_tetra())
    info = service.insights(str(stl))
    assert info["schema_version"] == "insights/1"
    assert info["source_type"] == "stl"
    assert info["verdict"] == "CONVERTIBLE"  # an STL converts to a U1 project
    assert info["dimensions_mm"] is not None and info["dimensions_mm"]["x"] >= 0
    assert info["triangles"] == 2  # the test tetra has 2 facets
    assert info["complexity"] == "low"


def test_service_insights_3mf_materials(tmp_path):
    out = _sample_u1(tmp_path)
    info = service.insights(str(out))
    assert info["verdict"] == "READY"
    assert isinstance(info["materials"], list)
    assert len(info["materials"]) == info["colors"]
    assert all("color" in m for m in info["materials"])


def test_service_report(tmp_path):
    out = _sample_u1(tmp_path)
    rep = service.report(str(out))
    assert rep["schema_version"] == "report/1"
    # Honest readiness: ready only when no check fails and nothing is at-risk.
    assert isinstance(rep["ready"], bool)
    if not rep["ready"]:
        assert rep["at_risk"] or any(c["status"] != "pass" for c in rep["checks"])
    assert any("geometry" in p.lower() for p in rep["preserved"])
    assert all(c["status"] in ("pass", "warn", "fail") for c in rep["checks"])
    assert isinstance(rep["changes"], list) and isinstance(rep["at_risk"], list)


def test_service_diff(tmp_path):
    a = _sample_u1(tmp_path)
    d = service.diff(str(a), str(a))   # same file vs itself
    assert d["schema_version"] == "diff/1"
    assert d["geometry_changed"] is False
    assert d["has_changes"] is False


def test_service_convert_stl(tmp_path):
    from pathlib import Path
    stl = tmp_path / "cube.stl"; stl.write_bytes(_bin_tetra())
    res = service.convert(str(stl))
    assert res["source_type"] == "stl"
    assert res["validated_ok"] is True
    assert res["output_name"].endswith("_SnapmakerU1.3mf")
    assert Path(res["output_path"]).exists()
    assert stl.exists()  # source untouched


def test_convert_never_overwrites_previous_output(tmp_path):
    from pathlib import Path
    stl = tmp_path / "cube.stl"; stl.write_bytes(_bin_tetra())
    first = service.convert(str(stl))
    second = service.convert(str(stl))
    # second conversion must NOT reuse/overwrite the first output
    assert first["output_path"] != second["output_path"]
    assert Path(first["output_path"]).exists() and Path(second["output_path"]).exists()
    assert second["output_name"].endswith("_SnapmakerU1_2.3mf")


def test_xml_special_chars_in_name_are_escaped(tmp_path):
    # filename with XML-significant chars must not produce malformed model_settings
    import xml.dom.minidom as M
    from snapstudio_core.stl_wrap import build_model_settings, build_model_settings_multi
    bad = 'a<b>&"c'
    for blob in (build_model_settings(name=bad), build_model_settings_multi([2], name=bad)):
        M.parseString(blob)  # raises if malformed
        assert b"a<b>" not in blob  # raw angle brackets not interpolated


# ---- loopback server round-trip ----
def _run(httpd):
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


def test_server_health_open():
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, body = _request(port, "/health", None, None, method="GET")
        assert status == 200 and body["status"] == "ok"
    finally:
        httpd.shutdown()


def test_server_doctor_requires_token(tmp_path):
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        out = _sample_u1(tmp_path)

        status, _ = _request(port, "/doctor", {"path": str(out)}, None)
        assert status == 401, "expected 401 without token"

        status, body = _request(port, "/doctor", {"path": str(out)}, token)
        assert status == 200 and body["verdict"] == "READY"
    finally:
        httpd.shutdown()


def _post(port, route, payload, token):
    status, _body = _request(port, route, payload, token)
    return status


def test_server_plate_dry_run_rejects_missing_filament(tmp_path):
    # bad input must be a clean 400, not a 500 crash from int(None)
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        out = _sample_u1(tmp_path)
        code = _post(port, "/plate_dry_run", {"path": str(out), "ui_plate": 1}, token)
        assert code == 400
    finally:
        httpd.shutdown()


def test_server_bad_content_length_is_400():
    # malformed Content-Length must be a clean 400, not a pre-auth crash
    import socket
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        # A raw socket, because the point is a malformed header no HTTP client
        # would send. Retried like every other connection in this file: a machine
        # with no source port to spare says nothing about how the server handles
        # this request.
        response = None
        for attempt in range(4):
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=10)
            except OSError:
                time.sleep(0.5 * (attempt + 1))
                continue
            try:
                sock.sendall(b"POST /doctor HTTP/1.1\r\nHost: x\r\n"
                             b"Content-Length: notanumber\r\nConnection: close\r\n\r\n")
                response = sock.recv(256)
            finally:
                sock.close()
            break
        assert response is not None, "the machine would not give this test a port"
        assert b"400" in response.split(b"\r\n", 1)[0]
    finally:
        httpd.shutdown()


def test_server_shutdown_requires_token_and_stops_the_server():
    httpd, token = build_server(port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        status, _ = _request(port, "/shutdown", {}, None)
        assert status == 401, "expected 401 without token"
        assert thread.is_alive(), "an unauthenticated /shutdown must not stop the server"

        status, body = _request(port, "/shutdown", {}, token)
        assert status == 200 and body["ok"] is True
        thread.join(timeout=5)
        assert not thread.is_alive(), "serve_forever did not return after /shutdown"
    finally:
        if thread.is_alive():
            httpd.shutdown()


def test_server_new_endpoints_are_routed():
    # Regression guard for the beta.4 stale-sidecar bug: these routes must exist
    # (a missing route returns 404; an executed route returns 200/400/500).
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        for route, payload in [
            ("/compatibility_check", {"path": "none"}),
            ("/scale_preview", {"path": "none", "scale_percent": 100}),
            ("/model_search", {"query": "x"}),
            ("/quality_check", {"symptom": "stringing"}),
            ("/first_layer_check", {"symptom": "not_stick"}),
        ]:
            assert _post(port, route, payload, token) != 404, f"{route} not routed"
        # valid advisory symptoms succeed
        assert _post(port, "/quality_check", {"symptom": "stringing"}, token) == 200
        assert _post(port, "/first_layer_check", {"symptom": "not_stick"}, token) == 200
    finally:
        httpd.shutdown()


def _post_full(port, route, raw_or_payload, token):
    """Returns (code, body_text). raw_or_payload may be bytes (sent verbatim)."""
    import http.client

    data = (raw_or_payload if isinstance(raw_or_payload, (bytes, bytearray))
            else json.dumps(raw_or_payload).encode())
    last = None
    for attempt in range(4):
        connection = None
        try:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request("POST", route, body=data,
                               headers={"Content-Type": "application/json",
                                        "X-Auth-Token": token})
            response = connection.getresponse()
            return response.status, response.read().decode()
        except OSError as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
        finally:
            if connection is not None:
                connection.close()
    raise AssertionError(f"the machine would not give this test a port ({last})")


def test_server_input_validation_returns_400(tmp_path):
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        out = str(_sample_u1(tmp_path))
        # bad string for a numeric field
        c, b = _post_full(port, "/scale_preview", {"path": out, "scale_percent": "abc"}, token)
        assert c == 400 and "scale_percent" in b
        # NaN / Infinity (Python json accepts these tokens; server must reject)
        for bad in ('{"path": "%s", "scale_percent": NaN}' % out,
                    '{"path": "%s", "scale_percent": Infinity}' % out):
            c, b = _post_full(port, "/scale_preview", bad.encode(), token)
            assert c == 400, f"expected 400 for {bad}"
        # missing required field (plate_export without to_filament)
        c, _ = _post_full(port, "/plate_export",
                          {"path": out, "ui_plate": 1, "from_filament": 0}, token)
        assert c == 400
        # bad port
        c, _ = _post_full(port, "/printer/status", {"host": "127.0.0.1", "port": "notaport"}, token)
        assert c == 400
        # malformed JSON
        c, _ = _post_full(port, "/scale_preview", b"{not json", token)
        assert c == 400
        # valid request still works (200; advisory result may be available:false)
        c, _ = _post_full(port, "/scale_preview", {"path": "none", "scale_percent": 100}, token)
        assert c == 200
    finally:
        httpd.shutdown()


def test_server_preflight_confirmed_nozzle_diameters(tmp_path):
    """End-to-end: /preflight accepts confirmed_nozzle_diameters, rejects a
    malformed one with 400, and never lets a bad value reach the engine."""
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        out = str(_sample_u1(tmp_path))
        # No printer configured (host omitted) — still a valid request; the
        # engine reports "unreachable"/no live nozzle data, which is exactly
        # the case confirmed_nozzle_diameters exists to help with.
        c, b = _post_full(port, "/preflight",
                          {"path": out, "confirmed_nozzle_diameters": [0.4],
                           "confirmed_nozzle_at": "2026-09-26"}, token)
        assert c == 200, b
        # Rejected: zero is not a valid nozzle diameter.
        c, b = _post_full(port, "/preflight",
                          {"path": out, "confirmed_nozzle_diameters": [0.0]}, token)
        assert c == 400 and "confirmed_nozzle_diameters" in b
        # Rejected: not a list.
        c, b = _post_full(port, "/preflight",
                          {"path": out, "confirmed_nozzle_diameters": "0.4"}, token)
        assert c == 400 and "confirmed_nozzle_diameters" in b
        # Absent entirely still works (the existing, pre-this-feature behaviour).
        c, b = _post_full(port, "/preflight", {"path": out}, token)
        assert c == 200, b
    finally:
        httpd.shutdown()


def test_server_400_body_has_no_traceback(tmp_path):
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        out = str(_sample_u1(tmp_path))
        c, b = _post_full(port, "/scale_preview", {"path": out, "scale_percent": "abc"}, token)
        assert c == 400
        lower = b.lower()
        assert "traceback" not in lower and "file \"" not in lower and "line " not in lower
    finally:
        httpd.shutdown()


def test_server_batch_pricing_bad_factor_is_400(tmp_path):
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        out = str(_sample_u1(tmp_path))
        c, _ = _post_full(port, "/batch_pricing", {"paths": [out], "price_per_kg": "abc"}, token)
        assert c == 400
        c, _ = _post_full(port, "/batch_pricing", {"paths": [out], "price_per_kg": 25.0}, token)
        assert c == 200
    finally:
        httpd.shutdown()


def test_cors_allow_origin_allowlist():
    from snapstudio_api.server import cors_allow_origin
    # allowed local app/dev origins are echoed
    for ok in ("http://tauri.localhost", "https://tauri.localhost", "tauri://localhost",
               "http://localhost:1420", "http://127.0.0.1:5173"):
        assert cors_allow_origin(ok) == ok
    # arbitrary remote pages are not granted permissive CORS
    for bad in ("https://evil.example.com", "http://attacker.test", "http://localhost.evil.com"):
        assert cors_allow_origin(bad) is None
    # no Origin (non-browser/local) -> no header needed
    assert cors_allow_origin(None) is None
    assert cors_allow_origin("") is None


# ---- library index ----
def test_library_record_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    out = _sample_u1(tmp_path)
    service.record_diagnosis(str(out), service.doctor(str(out)))
    listing = service.library_list()
    assert listing["count"] == 1
    p = listing["projects"][0]
    assert p["name"] == "cube_U1.3mf" and p["verdict"] == "READY"
    assert p["last_action"] == "doctor"


def test_library_convert_records_output(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    stl = tmp_path / "cube.stl"; stl.write_bytes(_bin_tetra())
    res = service.convert(str(stl))
    service.record_conversion(str(stl), res)
    p = service.library_list()["projects"][0]
    assert p["last_action"] == "convert"
    assert p["output_path"] == res["output_path"]


def test_library_history_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    out = _sample_u1(tmp_path)
    service.record_diagnosis(str(out), service.doctor(str(out)))
    pid = service.library_list()["projects"][0]["id"]
    hist = service.library_history(pid)
    assert hist["schema_version"] == "history/1"
    assert len(hist["events"]) >= 1
    assert hist["events"][0]["action"] == "doctor"
    # unknown project id -> empty timeline, never raises
    assert service.library_history(999999)["events"] == []


def test_library_search_and_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    out = _sample_u1(tmp_path)
    service.record_diagnosis(str(out), service.doctor(str(out)))
    assert service.library_list("cube")["count"] == 1
    assert service.library_list("nomatch")["count"] == 0
    pid = service.library_list()["projects"][0]["id"]
    service.library_delete(pid)
    assert service.library_list()["count"] == 0


def test_server_library_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        out = _sample_u1(tmp_path)
        hdr = {"Content-Type": "application/json", "X-Auth-Token": token}

        # diagnose over the wire -> auto-records into the library
        _request(port, "/doctor", {"path": str(out)}, token)

        # list via /library
        _status, body = _request(port, "/library", {}, token)
        assert body["count"] == 1 and body["projects"][0]["name"] == "cube_U1.3mf"
    finally:
        httpd.shutdown()


# ---- batch conversion ----
def test_batch_start_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    paths = []
    for i in range(3):
        stl = tmp_path / f"cube{i}.stl"; stl.write_bytes(_bin_tetra())
        paths.append(str(stl))

    job = service.batch_start(paths)
    assert job["total"] == 3 and job["job_id"]

    st = _poll_until_finished(lambda: service.batch_status(job["job_id"]))
    res = st["result"]
    assert res["total"] == 3 and res["done"] == 3 and res["failed"] == 0
    assert all(it["status"] == "done" and it["validated_ok"] for it in res["items"])
    # each batched conversion was indexed in the library too
    assert service.library_list()["count"] == 3


def test_batch_isolates_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    good = tmp_path / "ok.stl"; good.write_bytes(_bin_tetra())
    bad = tmp_path / "missing.stl"  # never created -> convert raises
    job = service.batch_start([str(good), str(bad)])
    st = _poll_until_finished(lambda: service.batch_status(job["job_id"]))
    res = st["result"]
    assert res["done"] == 1 and res["failed"] == 1
    by = {it["path"]: it for it in res["items"]}
    assert by[str(good)]["status"] == "done"
    assert by[str(bad)]["status"] == "error" and by[str(bad)]["error"]


def test_batch_status_unknown_job():
    assert service.batch_status("nope-not-a-job") is None


def test_server_batch_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        stl = tmp_path / "cube.stl"; stl.write_bytes(_bin_tetra())

        _status, start = _request(port, "/batch", {"paths": [str(stl)]}, token)
        job_id = start["job_id"]

        def status():
            # Polled every 50 ms until the batch finishes: a socket per poll is
            # what made this the last flaky test in the suite.
            _code, body = _request(port, "/batch/status", {"job_id": job_id}, token)
            return body

        st = _poll_until_finished(status)
        assert st["result"]["done"] == 1
    finally:
        httpd.shutdown()


# ---- local/manual spools (Known Limitations item D) ----

def test_server_local_spools_save_list_delete_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, saved = _request(port, "/local_spools/save", {
            "host": "u1.local", "slot": 0, "material": "PLA", "color": "#FF0000",
            "starting_g": 1000.0, "remaining_g": 800.0,
        }, token)
        assert status == 200
        assert saved["remaining_quality"] == "user_confirmed"

        status, listing = _request(port, "/local_spools", {"host": "u1.local"}, token)
        assert status == 200 and listing["available"] is True
        assert listing["slots"][0]["material"] == "PLA"

        status, empty = _request(port, "/local_spools", {"host": "other.local"}, token)
        assert status == 200 and empty["available"] is False

        status, deleted = _request(port, "/local_spools/delete",
                                   {"host": "u1.local", "slot": 0}, token)
        assert status == 200 and deleted["deleted"] is True

        status, gone = _request(port, "/local_spools", {"host": "u1.local"}, token)
        assert status == 200 and gone["available"] is False
    finally:
        httpd.shutdown()


def test_server_local_spools_mark_used(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        _request(port, "/local_spools/save", {
            "host": "u1.local", "slot": 0, "material": "PLA",
            "starting_g": 1000.0, "remaining_g": 800.0,
        }, token)

        status, updated = _request(port, "/local_spools/mark_used",
                                   {"host": "u1.local", "slot": 0, "used_g": 50.0}, token)
        assert status == 200
        assert updated["remaining_g"] == 750.0
        assert updated["remaining_quality"] == "derived"

        # A slot Studio has no remaining weight for is refused, not invented.
        status, err = _request(port, "/local_spools/mark_used",
                               {"host": "u1.local", "slot": 1, "used_g": 10.0}, token)
        assert status == 400 and "no local spool record" in err["error"]
    finally:
        httpd.shutdown()


def test_server_local_spools_rejects_bad_input(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, _ = _request(port, "/local_spools/save",
                             {"host": "u1.local", "slot": -1}, token)
        assert status == 400
        status, _ = _request(port, "/local_spools/save",
                             {"host": "u1.local", "slot": 0, "remaining_g": -5}, token)
        assert status == 400
        status, _ = _request(port, "/local_spools", {"host": ""}, token)
        assert status == 400
    finally:
        httpd.shutdown()
