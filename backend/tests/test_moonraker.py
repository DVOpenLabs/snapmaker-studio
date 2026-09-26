"""Read-only Moonraker spike, tested against a mock Moonraker (no real printer).
Proves discovery/connect/status parsing + that only GET is ever issued."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from snapstudio_core import moonraker

_SERVER_INFO = {"result": {"klippy_state": "ready", "moonraker_version": "v0.9.3",
                           "api_version_string": "1.5.0"}}
_STATUS = {"result": {"status": {
    "print_stats": {"state": "printing", "filename": "liberty_eagle.gcode",
                    "print_duration": 1200.0, "total_duration": 1300.0, "filament_used": 3456.0,
                    "info": {"current_layer": 42, "total_layer": 120}},
    "heater_bed": {"temperature": 60.0, "target": 60.0},
    "toolhead": {"axis_maximum": [270.0, 270.0, 270.0, 0.0], "axis_minimum": [0.0, 0.0, 0.0, 0.0]},
    "virtual_sdcard": {"progress": 0.42},
    "display_status": {"message": "Printing layer 42", "progress": 0.42},
    "gcode_move": {"speed_factor": 1.0, "extrude_factor": 1.0},
    "extruder": {"temperature": 210.0, "target": 210.0},
    "extruder1": {"temperature": 25.0, "target": 0.0},
}}}
_HISTORY = {"result": {"count": 3, "jobs": [
    {"filename": "good.gcode", "status": "completed", "start_time": 1700000000, "end_time": 1700003600,
     "print_duration": 3500.0, "total_duration": 3600.0, "filament_used": 8000.0},
    {"filename": "oops.gcode", "status": "cancelled", "start_time": 1699990000, "end_time": 1699990500,
     "print_duration": 480.0, "total_duration": 500.0, "filament_used": 900.0},
    {"filename": "boom.gcode", "status": "error", "start_time": 1699980000, "end_time": 1699980200,
     "print_duration": 180.0, "total_duration": 200.0, "filament_used": 300.0},
]}}
_TOTALS = {"result": {"job_totals": {"total_jobs": 3, "total_time": 4300.0, "total_print_time": 4160.0,
                                     "total_filament_used": 9200.0, "longest_print": 3500.0}}}
_METADATA = {"result": {
    "filename": "liberty_eagle.gcode", "estimated_time": 11520, "filament_total": 12345.6,
    "filament_weight_total": 38.4, "filament_type": "PLA", "layer_count": 240,
    "layer_height": 0.2, "first_layer_height": 0.24, "object_height": 48.0,
    "first_layer_bed_temp": 60, "first_layer_extr_temp": 220, "nozzle_diameter": 0.4,
    "slicer": "OrcaSlicer", "slicer_version": "2.3.4",
    "thumbnails": [{"width": 300, "height": 300, "relative_path": ".thumbs/x.png"}],
}}
_BEDMESH = {"result": {"status": {"bed_mesh": {
    "profile_name": "default", "mesh_min": [10.0, 10.0], "mesh_max": [260.0, 260.0],
    "probed_matrix": [
        [0.05, 0.02, 0.18],
        [0.01, 0.00, 0.06],
        [0.20, 0.03, 0.10],
    ],
}}}}
_PRINTER_INFO = {"result": {"state": "ready", "state_message": "Printer is ready", "hostname": "U1"}}
_OBJECTS_LIST = {"result": {"objects": ["print_stats", "heater_bed", "toolhead",
                                        "extruder", "extruder1", "extruder2", "extruder3"]}}
# Fabricated for testing only — shaped like a real /machine/system_info response
# (confirmed live against a real Snapmaker U1 this session) but every value here
# is synthetic. device_name/serial_number/mac_address are included specifically
# so test_machine_info_never_returns_identifying_fields can prove they never
# reach moonraker.machine_info()'s return value.
_SYSTEM_INFO = {"result": {"system_info": {
    "product_info": {
        "machine_type": "Snapmaker U1", "nozzle_diameter": [0.4, 0.4, 0.4, 0.4],
        "serial_number": "TEST-SERIAL-DO-NOT-USE", "device_name": "Test Printer Name",
        "firmware_version": "2.0.0",
    },
    "cpu_info": {"serial_number": "TEST-CPU-SERIAL"},
    "sd_info": {"capacity": "Unknown", "total_bytes": 0},
    "network": {"eth0": {"mac_address": "00:00:00:00:00:00",
                         "ip_addresses": [{"family": "ipv4", "address": "203.0.113.1"}]}},
}}}
_SYSTEM_INFO_WITH_STORAGE = {"result": {"system_info": {
    "product_info": {"nozzle_diameter": [0.4, 0.6]},
    "sd_info": {"capacity": "16 GB", "total_bytes": 16000000000},
}}}


def _mock_moonraker(system_info=None):
    methods_seen = []
    system_info = system_info if system_info is not None else _SYSTEM_INFO

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _send(self, obj):
            b = json.dumps(obj).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            methods_seen.append(("GET", self.path))
            if self.path == "/server/info": self._send(_SERVER_INFO)
            elif self.path == "/printer/info": self._send(_PRINTER_INFO)
            elif self.path == "/printer/objects/list": self._send(_OBJECTS_LIST)
            elif self.path == "/machine/system_info": self._send(system_info)
            elif self.path.startswith("/server/history/list"): self._send(_HISTORY)
            elif self.path == "/server/history/totals": self._send(_TOTALS)
            elif self.path.startswith("/server/files/metadata"): self._send(_METADATA)
            elif self.path.startswith("/printer/objects/query") and "bed_mesh" in self.path: self._send(_BEDMESH)
            elif self.path.startswith("/printer/objects/query"): self._send(_STATUS)
            else: self.send_response(404); self.end_headers()
        def do_POST(self):  # must NEVER be hit by the read-only client
            methods_seen.append(("POST", self.path)); self.send_response(405); self.end_headers()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1], methods_seen


def test_probe_connects():
    httpd, port, _ = _mock_moonraker()
    try:
        p = moonraker.probe("127.0.0.1", port, timeout=5)
        assert p["reachable"] is True
        assert p["klippy_state"] == "ready"
        assert p["moonraker_version"] == "v0.9.3"
    finally:
        httpd.shutdown()


def test_probe_unreachable_never_raises():
    p = moonraker.probe("127.0.0.1", 9, timeout=0.5)  # nothing listening
    assert p["reachable"] is False and "error" in p


def test_status_parses_toolheads_and_state():
    httpd, port, seen = _mock_moonraker()
    try:
        s = moonraker.status("127.0.0.1", port, timeout=5)
        assert s["schema_version"] == "printer/1"
        assert s["print_state"] == "printing"
        assert s["filename"] == "liberty_eagle.gcode"
        assert s["progress"] == 0.42
        assert s["bed"]["temperature"] == 60.0
        assert len(s["toolheads"]) == 2  # extruder + extruder1 present
        assert s["toolheads"][0]["temperature"] == 210.0
        # read-only guarantee: the client issued only GETs
        assert all(m == "GET" for m, _ in seen)
    finally:
        httpd.shutdown()


def test_status_enriched_telemetry(tmp_path=None):
    httpd, port, _ = _mock_moonraker()
    try:
        s = moonraker.status("127.0.0.1", port, timeout=5)
        assert s["current_layer"] == 42 and s["total_layer"] == 120
        assert s["message"] == "Printing layer 42"
        assert s["print_duration_s"] == 1200.0 and s["filament_used_mm"] == 3456.0
        assert s["speed_factor"] == 1.0
        # active toolhead = one with a target temp
        assert s["toolheads"][0]["active"] is True and s["toolheads"][1]["active"] is False
    finally:
        httpd.shutdown()


def test_history_and_failure_observation():
    httpd, port, seen = _mock_moonraker()
    try:
        h = moonraker.history("127.0.0.1", port, limit=20, timeout=5)
        assert len(h["jobs"]) == 3
        # two of three jobs failed (cancelled + error)
        assert len(h["failures"]) == 2
        assert {f["status"] for f in h["failures"]} == {"cancelled", "error"}
        assert h["totals"]["total_jobs"] == 3
        assert h["totals"]["total_filament_used_mm"] == 9200.0
        assert all(m == "GET" for m, _ in seen)
    finally:
        httpd.shutdown()


def test_diagnostics_reports_health():
    httpd, port, _ = _mock_moonraker()
    try:
        d = moonraker.diagnostics("127.0.0.1", port, timeout=5)
        assert d["klippy_state"] == "ready"
        assert d["healthy"] is True
        assert d["warnings"] == []
    finally:
        httpd.shutdown()


def test_diagnostics_unreachable_never_raises():
    d = moonraker.diagnostics("127.0.0.1", 9, timeout=0.5)
    assert d["healthy"] is False


def test_file_metadata_reads_slicer_estimates():
    httpd, port, seen = _mock_moonraker()
    try:
        m = moonraker.file_metadata("127.0.0.1", "liberty_eagle.gcode", port=port, timeout=5)
        assert m["available"] is True
        assert m["estimated_time_s"] == 11520
        assert m["filament_weight_g"] == 38.4
        assert m["layer_count"] == 240
        assert m["slicer"] == "OrcaSlicer"
        assert m["thumbnail_count"] == 1
        assert all(meth == "GET" for meth, _ in seen)
    finally:
        httpd.shutdown()


def test_bed_mesh_reduces_to_flatness_stats():
    httpd, port, seen = _mock_moonraker()
    try:
        bm = moonraker.bed_mesh("127.0.0.1", port, timeout=5)
        assert bm["available"] is True
        assert bm["profile_name"] == "default"
        # range = 0.20 - 0.00 = 0.20mm; no raw matrix leaked
        assert abs(bm["range_mm"] - 0.20) < 1e-6
        assert "probed_matrix" not in bm and "corner_spread_mm" in bm
        assert all(m == "GET" for m, _ in seen)
    finally:
        httpd.shutdown()


def test_bed_mesh_unreachable_never_raises():
    bm = moonraker.bed_mesh("127.0.0.1", 9, timeout=0.5)
    assert bm["available"] is False


def test_file_metadata_missing_never_raises():
    m = moonraker.file_metadata("127.0.0.1", "nope.gcode", port=9, timeout=0.5)
    assert m["available"] is False


def test_capabilities_reads_real_bed_and_toolheads():
    httpd, port, _ = _mock_moonraker()
    try:
        c = moonraker.capabilities("127.0.0.1", port, timeout=5)
        assert c["toolhead_count"] == 4
        assert c["bed_mm"] == {"x": 270.0, "y": 270.0, "z": 270.0}
    finally:
        httpd.shutdown()


def test_machine_info_reads_nozzle_diameters():
    httpd, port, seen = _mock_moonraker()
    try:
        m = moonraker.machine_info("127.0.0.1", port, timeout=5)
        assert m["nozzle_diameters"] == [0.4, 0.4, 0.4, 0.4]
        assert ("GET", "/machine/system_info") in seen
    finally:
        httpd.shutdown()


def test_machine_info_never_returns_identifying_fields():
    """The response this test's mock sends carries device_name/serial_number/
    cpu serial/mac_address/ip_addresses — none of them may survive into the
    return value, by construction, not because a redaction pass caught them."""
    httpd, port, _ = _mock_moonraker()
    try:
        m = moonraker.machine_info("127.0.0.1", port, timeout=5)
        assert set(m.keys()) == {"schema_version", "nozzle_diameters", "storage_bytes"}
        dumped = json.dumps(m)
        for leak in ("Test Printer Name", "TEST-SERIAL-DO-NOT-USE", "TEST-CPU-SERIAL",
                     "00:00:00:00:00:00", "203.0.113.1"):
            assert leak not in dumped
    finally:
        httpd.shutdown()


def test_machine_info_storage_absent_when_firmware_says_unknown():
    """Real stock U1 firmware reports sd_info.total_bytes=0 / capacity="Unknown"
    (confirmed live) — this must come back as None, never a fabricated number."""
    httpd, port, _ = _mock_moonraker()
    try:
        m = moonraker.machine_info("127.0.0.1", port, timeout=5)
        assert m["storage_bytes"] is None
    finally:
        httpd.shutdown()


def test_machine_info_storage_present_when_firmware_reports_it():
    httpd, port, _ = _mock_moonraker(system_info=_SYSTEM_INFO_WITH_STORAGE)
    try:
        m = moonraker.machine_info("127.0.0.1", port, timeout=5)
        assert m["storage_bytes"] == 16000000000
        assert m["nozzle_diameters"] == [0.4, 0.6]
    finally:
        httpd.shutdown()
