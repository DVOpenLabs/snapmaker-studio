"""Community hardware verification — read-only, and safe to attach to an issue.

Tested against a mock Moonraker so this proves what the module actually does
without a real printer: it never issues anything but a GET, it produces
PASS/FAIL/UNKNOWN rather than inventing a verdict, and the printer's own
address never survives into the evidence it hands back.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from snapstudio_core import hardware_verify

_SERVER_INFO = {"result": {"klippy_state": "ready", "moonraker_version": "v0.9.3",
                           "api_version_string": "1.5.0"}}
_OBJECTS_LIST = {"result": {"objects": ["print_stats", "heater_bed", "toolhead",
                                        "extruder", "extruder1", "extruder2", "extruder3",
                                        "print_task_config"]}}
_TOOLHEAD = {"result": {"status": {"toolhead": {
    "axis_maximum": [270.0, 270.0, 270.0, 0.0], "axis_minimum": [0.0, 0.0, 0.0, 0.0]}}}}
_PRINT_TASK_CONFIG = {"result": {"status": {"print_task_config": {
    "filament_type": ["PLA", "PETG", None, "PLA"],
    "filament_color_rgba": ["FF0000", "00FF00", None, "FFFFFF"],
    "filament_exist": [True, True, False, True],
}}}}


def _mock_moonraker(*, with_print_task_config=True):
    methods_seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, obj):
            b = json.dumps(obj).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            methods_seen.append(("GET", self.path))
            if self.path == "/server/info":
                self._send(_SERVER_INFO)
            elif self.path == "/printer/objects/list":
                self._send(_OBJECTS_LIST)
            elif self.path.startswith("/printer/objects/query") and "print_task_config" in self.path:
                self._send(_PRINT_TASK_CONFIG if with_print_task_config else {"result": {"status": {}}})
            elif self.path.startswith("/printer/objects/query") and "toolhead" in self.path:
                self._send(_TOOLHEAD)
            else:
                self.send_response(404); self.end_headers()

        def do_POST(self):  # must NEVER be hit — this tool is read-only
            methods_seen.append(("POST", self.path)); self.send_response(405); self.end_headers()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1], methods_seen


_GENERIC_OBJECTS_LIST = {"result": {"objects": ["print_stats", "heater_bed", "toolhead",
                                                 "extruder", "extruder1", "extruder2", "extruder3"]}}


def _mock_generic_klipper():
    """A four-toolhead Klipper printer with no Snapmaker-specific object —
    same shape as `_mock_moonraker`, minus the one thing identification keys on."""
    methods_seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, obj):
            b = json.dumps(obj).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            methods_seen.append(("GET", self.path))
            if self.path == "/server/info":
                self._send(_SERVER_INFO)
            elif self.path == "/printer/objects/list":
                self._send(_GENERIC_OBJECTS_LIST)
            elif self.path.startswith("/printer/objects/query") and "toolhead" in self.path:
                self._send(_TOOLHEAD)
            elif self.path.startswith("/printer/objects/query"):
                self._send({"result": {"status": {}}})
            else:
                self.send_response(404); self.end_headers()

        def do_POST(self):
            methods_seen.append(("POST", self.path)); self.send_response(405); self.end_headers()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1], methods_seen


def test_a_reachable_printer_passes_the_checks_it_can_answer():
    httpd, port, seen = _mock_moonraker()
    try:
        out = hardware_verify.run("127.0.0.1", port)
        by_id = {c["id"]: c for c in out["checks"]}
        assert by_id["printer.reachable"]["result"] == hardware_verify.PASS
        assert by_id["moonraker.version"]["result"] == hardware_verify.PASS
        assert by_id["capabilities.toolhead_count"]["result"] == hardware_verify.PASS
        assert by_id["capabilities.bed_size"]["result"] == hardware_verify.PASS
        assert by_id["capabilities.object_list"]["result"] == hardware_verify.PASS
        assert by_id["material.loaded_filaments"]["result"] == hardware_verify.PASS
        assert "3 slot(s)" in by_id["material.loaded_filaments"]["evidence"]
        assert out["moonraker_version"] == "v0.9.3"
        assert out["capabilities"]["toolhead_count"] == 4
        # read-only guarantee: the client issued only GETs
        assert all(m == "GET" for m, _ in seen)
    finally:
        httpd.shutdown()


def test_an_unreachable_printer_fails_only_the_reachability_check():
    out = hardware_verify.run("127.0.0.1", 9)  # nothing listening
    by_id = {c["id"]: c for c in out["checks"]}
    assert by_id["printer.reachable"]["result"] == hardware_verify.FAIL
    # Nothing downstream of an unreachable printer is asked at all.
    assert len(out["checks"]) == 1
    assert out["moonraker_version"] is None
    assert out["printer_model"] is None


def test_firmware_that_does_not_report_loaded_filament_is_unknown_not_a_failure():
    httpd, port, _ = _mock_moonraker(with_print_task_config=False)
    try:
        out = hardware_verify.run("127.0.0.1", port)
        by_id = {c["id"]: c for c in out["checks"]}
        assert by_id["material.loaded_filaments"]["result"] == hardware_verify.UNKNOWN
    finally:
        httpd.shutdown()


def test_a_snapmaker_shaped_printer_is_identified():
    """The mock carries the vendor object (`print_task_config`) and toolhead
    count identification actually keys on — the same U1 shape moonraker.py's
    own tests use."""
    httpd, port, _ = _mock_moonraker()
    try:
        out = hardware_verify.run("127.0.0.1", port)
        by_id = {c["id"]: c for c in out["checks"]}
        assert by_id["printer.identified"]["result"] == hardware_verify.PASS
        assert out["printer_model"] == "snapmaker_u1"
    finally:
        httpd.shutdown()


def test_a_generic_klipper_printer_is_unrecognised_never_a_failure():
    """No vendor-specific object, no match — and that is a perfectly good
    answer: not being identified is not the same as failing a check."""
    httpd, port, _ = _mock_generic_klipper()
    try:
        out = hardware_verify.run("127.0.0.1", port)
        by_id = {c["id"]: c for c in out["checks"]}
        assert by_id["printer.identified"]["result"] == hardware_verify.UNKNOWN
        assert out["printer_model"] is None
    finally:
        httpd.shutdown()


def test_every_check_is_pass_fail_or_unknown_never_anything_else():
    httpd, port, _ = _mock_moonraker()
    try:
        out = hardware_verify.run("127.0.0.1", port)
        for check in out["checks"]:
            assert check["result"] in (hardware_verify.PASS, hardware_verify.FAIL, hardware_verify.UNKNOWN)
            assert check["id"] and check["title"] and check["evidence"]
    finally:
        httpd.shutdown()


# --- the evidence bundle: redacted, and never claims hardware-verified -------

def test_build_evidence_never_contains_the_printer_address():
    httpd, port, _ = _mock_moonraker()
    try:
        bundle = hardware_verify.build_evidence("127.0.0.1", port)
        text = json.dumps(bundle)
        assert "127.0.0.1" not in text
        assert str(port) not in text
    finally:
        httpd.shutdown()


def test_build_evidence_carries_studio_and_os_facts():
    httpd, port, _ = _mock_moonraker()
    try:
        bundle = hardware_verify.build_evidence("127.0.0.1", port)
        assert bundle["studio_version"]
        assert bundle["os"]
        assert bundle["schema_version"] == hardware_verify.SCHEMA_VERSION
    finally:
        httpd.shutdown()


def test_nothing_in_the_bundle_itself_claims_hardware_verified():
    """That label is a maintainer's editorial decision on
    docs/PRINTER_COMPATIBILITY.md, made by reading a submitted bundle — never
    a verdict this module writes into its own output."""
    httpd, port, _ = _mock_moonraker()
    try:
        bundle = hardware_verify.build_evidence("127.0.0.1", port)
        assert "hardware verified" not in json.dumps(bundle).lower()
        assert all(c["result"] != "hardware_verified" for c in bundle["checks"])
    finally:
        httpd.shutdown()
