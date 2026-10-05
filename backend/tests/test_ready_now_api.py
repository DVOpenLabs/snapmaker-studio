"""Ready Now scan: the background job, its guards (one printer read, one provider read,
50 newest projects, bounded cache) and its privacy and read-only promises.

The printer and the provider are fakes with call counters; project traits are faked
too, so no real 3MF is needed — only files that exist on disk for the cache to stat.
"""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from snapstudio_api import service
from snapstudio_api.server import build_server
from snapstudio_core import library, material_providers as providers
from snapstudio_core import plate_placement, project_traits
from tests.test_api import _request, _run
from tests.test_readiness import NOW, spool, traits

HOST = "secret-printer.invalid"
PROVIDER_URL = "http://192.168.77.77:7912"
PROVIDER_KEY = "SECRET-PROVIDER-KEY-123"


class Fakes:
    """Counters for everything the scan is allowed to read exactly once."""

    def __init__(self, monkeypatch, *, loaded=None, reachable=True, state="standby"):
        self.printer_reads = self.provider_reads = 0
        self.extracts = self.placements = 0
        self.traits_by_name: dict[str, dict] = {}
        self.loaded = loaded if loaded is not None else [spool()]
        self.reachable, self.state = reachable, state
        monkeypatch.setattr(service, "printer_facts", self._printer)
        monkeypatch.setattr(providers, "read", self._provider)
        monkeypatch.setattr(project_traits, "extract", self._extract)
        monkeypatch.setattr(plate_placement, "assess", self._assess)

    def _printer(self, host=None, port=7125):
        self.printer_reads += 1
        if not self.reachable:
            return {"reachable": False, "error": f"{host} did not answer"}
        return {"reachable": True, "host": host, "port": port, "toolhead_count": 4,
                "bed_mm": {"x": 270, "y": 270, "z": 270}, "nozzle_diameters": [0.4] * 4,
                "nozzle_confirmed_by": "printer", "print_state": self.state,
                "klipper_objects": [], "loaded_filaments": None}

    def _provider(self, kind, url, slot_map=None, timeout=4.0, slot_base=None, key=None):
        self.provider_reads += 1
        slots = [providers._slot(i, material=s["material"], color=s["color"],
                                 remaining_g=s["remaining_g"], source="spoolman",
                                 remaining_quality="tracked", remaining_as_of=NOW,
                                 confirmed_by="provider")
                 for i, s in enumerate(self.loaded) if s]
        return {"available": True, "source": "spoolman", "remaining_known": True,
                "slots": slots, "spools": slots, "error": None, "error_code": None}

    def _extract(self, path):
        self.extracts += 1
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        return self.traits_by_name.get(name) or traits()

    def _assess(self, path, bed=None, bed_name=None):
        self.placements += 1
        return {"available": True, "off_plate": []}


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    service._READY_CACHE.clear()
    yield
    service._READY_CACHE.clear()


def add_project(tmp_path, name, minute=0, *, create=True):
    path = tmp_path / name
    if create:
        path.write_bytes(b"x" * 10)
    conn = service._conn()
    try:
        library.upsert_project(conn, name=name, source_path=str(path), source_family=None,
                               output_path=None, verdict=None, score=None, filament_count=None,
                               last_action="doctor", updated_at=f"2026-10-01T10:{minute:02d}:00Z")
    finally:
        conn.close()
    return path


def scan(**kw):
    kw.setdefault("host", HOST)
    job = service.ready_now_start(**kw)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        st = service.ready_now_status(job["job_id"])
        if st["status"] in ("done", "error"):
            return st
        time.sleep(0.02)
    raise AssertionError("scan did not finish")


def by_name(status):
    return {r["name"]: r for r in status["result"]["results"]}


def test_one_printer_read_and_one_provider_read_serve_every_project(tmp_path, monkeypatch):
    fakes = Fakes(monkeypatch)
    for i in range(6):
        add_project(tmp_path, f"p{i}.3mf", i)
    st = scan(provider_url=PROVIDER_URL, provider_key=PROVIDER_KEY)
    assert st["status"] == "done" and st["result"]["scanned"] == 6
    assert fakes.printer_reads == 1
    assert fakes.provider_reads == 1


def test_buckets_come_from_the_composed_checks(tmp_path, monkeypatch):
    fakes = Fakes(monkeypatch, loaded=[spool("PLA", "#FF0000")])
    for i, n in enumerate(["ready", "petg", "foreign", "colour"]):
        add_project(tmp_path, f"{n}.3mf", i)
    fakes.traits_by_name = {
        "petg.3mf": traits(slots=(("PETG", "#FF0000"),)),
        "foreign.3mf": traits(foreign=True),
        "colour.3mf": traits(slots=(("PLA", "#0000FF"),)),
    }
    st = scan(provider_url=PROVIDER_URL)
    got = by_name(st)
    assert got["ready.3mf"]["bucket"] == "ready_now"
    assert got["petg.3mf"]["bucket"] == "one_change_away"
    assert got["foreign.3mf"]["bucket"] == "needs_preparation"
    assert got["colour.3mf"]["bucket"] == "ready_now" and got["colour.3mf"]["colour_notes"]
    # results are listed bucket by bucket, in decision order
    order = [r["bucket"] for r in st["result"]["results"]]
    assert order == sorted(order, key=lambda b: ["needs_preparation", "needs_attention",
                           "cant_determine", "one_change_away", "ready_now"].index(b))
    assert st["result"]["counts"]["ready_now"] == 2


def test_busy_printer_needs_attention(tmp_path, monkeypatch):
    Fakes(monkeypatch, state="printing")
    add_project(tmp_path, "a.3mf")
    assert by_name(scan(provider_url=PROVIDER_URL))["a.3mf"]["bucket"] == "needs_attention"


def test_unreachable_printer_still_prepares_foreign_and_never_claims_ready(tmp_path, monkeypatch):
    fakes = Fakes(monkeypatch, reachable=False)
    add_project(tmp_path, "mine.3mf", 1)
    add_project(tmp_path, "foreign.3mf", 2)
    fakes.traits_by_name = {"foreign.3mf": traits(foreign=True)}
    st = scan()
    got = by_name(st)
    assert got["foreign.3mf"]["bucket"] == "needs_preparation"
    assert got["mine.3mf"]["bucket"] == "cant_determine"
    assert st["result"]["printer"]["reachable"] is False
    assert fakes.placements == 0          # no bed, nothing to place against


def test_no_host_means_no_printer_read_at_all(tmp_path, monkeypatch):
    fakes = Fakes(monkeypatch)
    add_project(tmp_path, "a.3mf")
    st = scan(host=None)
    assert fakes.printer_reads == 0
    assert by_name(st)["a.3mf"]["bucket"] == "cant_determine"


def test_scan_reads_only_the_newest_fifty(tmp_path, monkeypatch):
    fakes = Fakes(monkeypatch)
    for i in range(60):
        add_project(tmp_path, f"p{i:02d}.3mf", i)
    st = scan(provider_url=PROVIDER_URL)
    names = {r["name"] for r in st["result"]["results"]}
    assert st["result"]["scanned"] == 50 and st["result"]["library_total"] == 60
    assert names == {f"p{i:02d}.3mf" for i in range(10, 60)}      # the oldest ten are left out
    assert fakes.extracts == 50 and fakes.printer_reads == 1


def test_limit_is_clamped_in_the_service_and_refused_over_http(tmp_path, monkeypatch):
    Fakes(monkeypatch)
    for i in range(5):
        add_project(tmp_path, f"p{i}.3mf", i)
    assert scan(provider_url=PROVIDER_URL, limit=2)["result"]["scanned"] == 2
    assert scan(provider_url=PROVIDER_URL, limit=999)["result"]["scanned"] == 5
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        for bad in (0, 51, "x", 1.5):
            status, _ = _request(port, "/ready_now/start", {"limit": bad}, token)
            assert status == 400
    finally:
        httpd.shutdown()


def test_second_scan_hits_the_cache_and_an_edited_file_does_not(tmp_path, monkeypatch):
    fakes = Fakes(monkeypatch)
    paths = [add_project(tmp_path, f"p{i}.3mf", i) for i in range(3)]
    first = scan(provider_url=PROVIDER_URL)
    assert fakes.extracts == 3 and fakes.placements == 3
    second = scan(provider_url=PROVIDER_URL)
    assert fakes.extracts == 3 and fakes.placements == 3          # nothing re-read
    assert second["result"]["results"] == first["result"]["results"]
    paths[0].write_bytes(b"y" * 25)                               # size changes
    scan(provider_url=PROVIDER_URL)
    assert fakes.extracts == 4 and fakes.placements == 4
    # printer facts are never cached: each scan reads the printer once
    assert fakes.printer_reads == 3


def test_cache_is_keyed_by_bed_size(tmp_path, monkeypatch):
    fakes = Fakes(monkeypatch)
    add_project(tmp_path, "a.3mf")
    scan(provider_url=PROVIDER_URL)
    monkeypatch.setattr(fakes, "_printer", lambda host=None, port=7125: {
        "reachable": True, "host": host, "port": port, "toolhead_count": 4,
        "bed_mm": {"x": 350, "y": 350, "z": 350}, "nozzle_diameters": [0.4] * 4,
        "nozzle_confirmed_by": "printer", "print_state": "standby", "klipper_objects": [],
        "loaded_filaments": None})
    monkeypatch.setattr(service, "printer_facts", fakes._printer)
    scan(provider_url=PROVIDER_URL)
    assert fakes.placements == 2


def test_cache_is_bounded(tmp_path, monkeypatch):
    Fakes(monkeypatch)
    monkeypatch.setattr(service, "_READY_CACHE_MAX", 3)
    for i in range(8):
        add_project(tmp_path, f"p{i}.3mf", i)
    scan(provider_url=PROVIDER_URL)
    assert len(service._READY_CACHE) == 3


def test_missing_and_unreadable_files(tmp_path, monkeypatch):
    fakes = Fakes(monkeypatch)
    add_project(tmp_path, "gone.3mf", 1, create=False)
    add_project(tmp_path, "bad.3mf", 2)
    fakes.traits_by_name = {"bad.3mf": dict(traits(), readable=False)}
    got = by_name(scan(provider_url=PROVIDER_URL))
    assert got["gone.3mf"]["file_state"] == "missing"
    assert got["gone.3mf"]["bucket"] == "cant_determine"
    assert got["bad.3mf"]["file_state"] == "unreadable"
    assert got["bad.3mf"]["bucket"] == "cant_determine"


def test_one_bad_project_does_not_sink_the_scan(tmp_path, monkeypatch):
    fakes = Fakes(monkeypatch)
    add_project(tmp_path, "boom.3mf", 1)
    add_project(tmp_path, "fine.3mf", 2)
    real = fakes._extract

    def extract(path):
        if path.endswith("boom.3mf"):
            raise RuntimeError(path)
        return real(path)
    monkeypatch.setattr(project_traits, "extract", extract)
    st = scan(provider_url=PROVIDER_URL)
    got = by_name(st)
    assert st["status"] == "done"
    assert got["boom.3mf"]["file_state"] == "unreadable"
    assert got["fine.3mf"]["bucket"] == "ready_now"


def test_no_secret_host_or_provider_detail_in_any_response(tmp_path, monkeypatch):
    Fakes(monkeypatch)
    add_project(tmp_path, "a.3mf")
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        status, started = _request(port, "/ready_now/start", {
            "host": HOST, "provider": "spoolman", "provider_url": PROVIDER_URL,
            "provider_key": PROVIDER_KEY, "slot_map": {"0": 1}}, token)
        assert status == 200
        bodies = [json.dumps(started)]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status, body = _request(port, "/ready_now/status", {"job_id": started["job_id"]}, token)
            assert status == 200
            bodies.append(json.dumps(body))
            if body["status"] == "done":
                break
            time.sleep(0.02)
        assert body["status"] == "done"
        blob = "\n".join(bodies)
        for secret in (HOST, "192.168.77.77", PROVIDER_KEY, "7912"):
            assert secret not in blob
        assert body["result"]["provider_status"]["available"] is True
    finally:
        httpd.shutdown()


def test_error_job_names_only_the_exception_class(tmp_path, monkeypatch):
    Fakes(monkeypatch)
    add_project(tmp_path, "a.3mf")

    def boom(host=None, port=7125):
        raise RuntimeError(f"could not talk to {HOST} with {PROVIDER_KEY}")
    monkeypatch.setattr(service, "printer_facts", boom)
    st = scan()
    assert st["status"] == "error" and st["error"] == "RuntimeError"
    assert HOST not in json.dumps(st) and PROVIDER_KEY not in json.dumps(st)


def _snapshot(db_path):
    conn = sqlite3.connect(db_path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                             "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in tables}
    finally:
        conn.close()


def test_a_scan_writes_nothing(tmp_path, monkeypatch):
    Fakes(monkeypatch)
    for i in range(3):
        add_project(tmp_path, f"p{i}.3mf", i)
    before = _snapshot(service._db_path())

    def forbidden(*a, **k):
        raise AssertionError("a Ready Now scan must not write")
    for name in ("save_local_spool", "delete_local_spool", "mark_local_spool_used",
                 "nozzle_confirm_save", "nozzle_clear", "printer_start", "printer_pause",
                 "printer_resume", "printer_cancel", "printer_upload_gcode", "record_diagnosis",
                 "record_conversion", "library_delete", "_record_fix"):
        monkeypatch.setattr(service, name, forbidden)
    st = scan(provider_url=PROVIDER_URL, provider_key=PROVIDER_KEY, slot_map={"0": 1})
    assert st["status"] == "done"
    assert _snapshot(service._db_path()) == before


def test_status_of_unknown_or_foreign_job_is_none(tmp_path, monkeypatch):
    Fakes(monkeypatch)
    assert service.ready_now_status("nope") is None
    with service._jobs_lock:
        service._jobs["batch-job"] = {"id": "batch-job", "status": "done", "error": None,
                                      "result": None}
    try:
        assert service.ready_now_status("batch-job") is None
    finally:
        with service._jobs_lock:
            service._jobs.pop("batch-job", None)


def test_routes_need_the_token_and_unknown_job_is_404(tmp_path):
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        assert _request(port, "/ready_now/start", {}, "wrong")[0] == 401
        assert _request(port, "/ready_now/status", {"job_id": "x"}, "wrong")[0] == 401
        assert _request(port, "/ready_now/status", {"job_id": "x"}, token)[0] == 404
        assert _request(port, "/ready_now/status", {}, token)[0] == 400
    finally:
        httpd.shutdown()


def test_progress_and_partial_results_are_reported(tmp_path, monkeypatch):
    Fakes(monkeypatch)
    for i in range(4):
        add_project(tmp_path, f"p{i}.3mf", i)
    st = scan(provider_url=PROVIDER_URL)
    assert st["progress"] == {"done": 4, "total": 4}
    assert st["result"]["schema_version"] == "readiness/1"
