"""v1.3.1 (#67): a deliberate refusal is answered with its own message, not "internal error"; a genuine fault is logged
locally and answered with only its class name."""
from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

import pytest

from snapstudio_api import service
from snapstudio_api.server import build_server
from snapstudio_core.errors import FilamentLimitError, PreservationError, UnsoundOutput, SnapStudioError

from tests.test_api import _request

FIXTURE = Path(__file__).parent / "fixtures" / "prusa-semantics" / "inst3_out.3mf"


def _serve():
    httpd, token = build_server(port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, token, httpd.server_address[1]


def test_a_file_studio_refuses_to_prepare_says_why_instead_of_internal_error(tmp_path):
    """inst3_out.3mf is a real case where Studio builds a prepared copy it cannot vouch for and refuses to save it. In
    v1.2.0 and v1.3.0 that surfaced to the person as 'internal error'; the reason is already written for them."""
    src = tmp_path / "inst3_out.3mf"
    shutil.copy2(FIXTURE, src)
    httpd, token, port = _serve()
    try:
        status, body = _request(port, "/convert", {"path": str(src), "out_dir": str(tmp_path), "prepare_mode": "recommended"}, token)
    finally:
        httpd.shutdown()
    assert status == 422
    assert body["refusal"] == "UnsoundOutput"
    assert body["error"] != "internal error"
    # plain sentence first; the raw wording is a separate, secondary field
    assert "UnsoundOutput" not in body["error"] and "original file was not changed" in body["error"]
    assert "cannot vouch for" in body["details"]


@pytest.mark.parametrize("exc", [UnsoundOutput(["x differs from y"]), PreservationError("a setting could not be carried"),
                                 FilamentLimitError("more filaments than the printer carries")])
def test_every_deliberate_refusal_is_422_with_its_message_on_any_route(monkeypatch, exc):
    def refuse(*a, **k):
        raise exc

    monkeypatch.setattr(service, "doctor", refuse)
    monkeypatch.setattr(service, "convert", refuse)
    httpd, token, port = _serve()
    try:
        for route in ("/doctor", "/convert"):
            status, body = _request(port, route, {"path": "x.3mf"}, token)
            assert status == 422, route
            assert body["error"] == str(exc)
            assert body["refusal"] == type(exc).__name__
    finally:
        httpd.shutdown()


def test_a_genuine_fault_is_logged_locally_and_names_only_its_class(monkeypatch, tmp_path):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path))

    def boom(*a, **k):
        raise KeyError("secret-private-detail")

    monkeypatch.setattr(service, "convert", boom)
    httpd, token, port = _serve()
    try:
        status, body = _request(port, "/convert", {"path": "x.3mf"}, token)
    finally:
        httpd.shutdown()
    assert status == 500
    assert body == {"error": "internal error", "kind": "KeyError"}
    assert "secret-private-detail" not in str(body)
    log = (tmp_path / "engine-errors.log").read_text(encoding="utf-8")
    assert "KeyError" in log and "boom" in log
    # call sites only: never the message, never an absolute path
    assert "secret-private-detail" not in log
    assert str(tmp_path) not in log and "\\" not in log.replace("\n", "")


def test_the_engine_log_is_size_capped(monkeypatch, tmp_path):
    from snapstudio_api import server

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_ENGINE_LOG_MAX_BYTES", 200)
    monkeypatch.setattr(server, "_ENGINE_LOG_ENTRY_MAX", 150)
    for _ in range(20):
        server._log_unexpected(RuntimeError("x" * 120))
    assert (tmp_path / "engine-errors.log").stat().st_size <= 200
    assert (tmp_path / "engine-errors.log.1").exists()


def test_a_huge_exception_message_never_reaches_the_log(monkeypatch, tmp_path):
    from snapstudio_api import server

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path))
    server._log_unexpected(RuntimeError("x" * 5_000_000))
    log = (tmp_path / "engine-errors.log").read_text(encoding="utf-8")
    assert "RuntimeError" in log and "xxxx" not in log
    assert len(log) <= server._ENGINE_LOG_ENTRY_MAX


def test_log_stays_bounded_when_rotation_fails(monkeypatch, tmp_path):
    from snapstudio_api import server

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_ENGINE_LOG_MAX_BYTES", 300)
    monkeypatch.setattr(server, "_ENGINE_LOG_ENTRY_MAX", 150)

    def no_rotate(*a, **k):
        raise OSError("locked")

    monkeypatch.setattr(server.os, "replace", no_rotate)
    for _ in range(50):
        server._log_unexpected(RuntimeError("x"))
    assert (tmp_path / "engine-errors.log").stat().st_size <= 300


def test_log_byte_accounting_is_exact(monkeypatch, tmp_path):
    from snapstudio_api import server

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_ENGINE_LOG_MAX_BYTES", 10_000)
    server._log_unexpected(RuntimeError("x"))
    raw = (tmp_path / "engine-errors.log").read_bytes()
    assert b"\r\n" not in raw  # no newline translation: size on disk == size counted


def test_logging_failure_never_breaks_the_response(monkeypatch):
    from snapstudio_api import server

    monkeypatch.setattr(server._paths, "data_dir", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    server._log_unexpected(RuntimeError("x"))  # must not raise


def test_snapstudio_error_is_the_base_of_every_user_safe_refusal():
    from snapstudio_core import errors

    for name in ("PartNotFound", "PreservationError", "FilamentLimitError", "UnsoundOutput", "UnsafeArchive"):
        assert issubclass(getattr(errors, name), SnapStudioError)
