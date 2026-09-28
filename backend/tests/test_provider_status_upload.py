"""plan-39 addendum §8 (A-2) + v3.3 B-2: `provider_status` is present on
every `/printer/upload_gcode` return shape, computed once from the optional
recheck, never a second provider read of its own.

`changed` is only ever produced through a recheck — by construction, calling
`printer_upload_gcode` with no `expect_state` never runs `send_check`, so
`changed` and "no recheck" is an unreachable pair; this suite proves that by
never being able to construct the combination, and asserts it explicitly in
`test_changed_is_unreachable_without_a_recheck`.
"""
from __future__ import annotations

import json
import sys

import pytest

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "tests")

from snapstudio_api import service
from snapstudio_core import moonraker

PS_OK = {"provider": "spoolease", "name": "SpoolEase", "available": True,
        "error": None, "error_code": None, "spools": 3, "with_weight": 2}
PS_FAIL = {"provider": "spoolease", "name": "SpoolEase", "available": False,
          "error": "SpoolEase did not answer: HTTP 500", "error_code": "http_status",
          "spools": 0, "with_weight": 0}

RECHECK_MODES = ("provider_ok", "provider_fail", "no_provider", "no_recheck")


def _install_fake_send_check(monkeypatch, *, mode: str, same_hashes: bool):
    """Stands in for `service.send_check`: returns a controlled `state` (for
    `send_state.changes` to compare against `expect_state`) and the
    `provider_status` the given recheck mode implies."""
    status = {"provider_ok": PS_OK, "provider_fail": PS_FAIL, "no_provider": None}.get(mode)
    hashes = {"job": "same"} if same_hashes else {"job": "different"}

    def fake_send_check(path, **kwargs):
        return {"state": {"hashes": hashes}, "provider_status": status}

    monkeypatch.setattr(service, "send_check", fake_send_check)
    return status


def _base_expect_state():
    return {"hashes": {"job": "same"}}


@pytest.fixture
def gcode_file(tmp_path):
    p = tmp_path / "job.gcode"
    p.write_text("; not a real slice\n")
    return str(p)


# --- the eight non-"changed" reachable states, each in every recheck mode ---

def _run(monkeypatch, gcode_file, *, recheck_mode: str, confirm: bool = True,
        upload_raises=None, confirmation=None, confirmation_raises=None):
    if upload_raises is not None:
        def fake_upload(host, path, port):
            raise upload_raises
        monkeypatch.setattr(moonraker, "upload_gcode", fake_upload)
    else:
        monkeypatch.setattr(
            moonraker, "upload_gcode",
            lambda host, path, port: {"ok": True, "action": "upload",
                                      "filename": "job.gcode", "path": "job.gcode", "size": 10})

    if confirmation_raises is not None:
        def fake_confirm(host, filename, expected_size=None, port=7125):
            raise confirmation_raises
        monkeypatch.setattr(moonraker, "confirm_upload", fake_confirm)
    elif confirmation is not None:
        monkeypatch.setattr(moonraker, "confirm_upload",
                            lambda host, filename, expected_size=None, port=7125: confirmation)

    expect_state = None if recheck_mode == "no_recheck" else _base_expect_state()
    kwargs = {}
    if recheck_mode != "no_recheck":
        _install_fake_send_check(monkeypatch, mode=recheck_mode, same_hashes=True)

    return service.printer_upload_gcode(
        "printer.local", gcode_file, confirm=confirm, expect_state=expect_state, **kwargs)


EXPECTED_STATUS = {"provider_ok": PS_OK, "provider_fail": PS_FAIL,
                   "no_provider": None, "no_recheck": None}


@pytest.mark.parametrize("recheck_mode", RECHECK_MODES)
def test_refused_by_printer_carries_provider_status(monkeypatch, gcode_file, recheck_mode):
    out = _run(monkeypatch, gcode_file, recheck_mode=recheck_mode,
              upload_raises=moonraker.UploadRefused(403, "no"))
    assert out["state"] == "refused_by_printer"
    assert out["provider_status"] == EXPECTED_STATUS[recheck_mode]


@pytest.mark.parametrize("recheck_mode", RECHECK_MODES)
def test_not_accepted_carries_provider_status(monkeypatch, gcode_file, recheck_mode):
    out = _run(monkeypatch, gcode_file, recheck_mode=recheck_mode,
              upload_raises=OSError("connection refused"))
    assert out["state"] == "not_accepted"
    assert out["provider_status"] == EXPECTED_STATUS[recheck_mode]


@pytest.mark.parametrize("recheck_mode", RECHECK_MODES)
def test_pending_verification_no_confirm_carries_provider_status(monkeypatch, gcode_file, recheck_mode):
    out = _run(monkeypatch, gcode_file, recheck_mode=recheck_mode, confirm=False)
    assert out["state"] == "pending_verification"
    assert out["provider_status"] == EXPECTED_STATUS[recheck_mode]


@pytest.mark.parametrize("recheck_mode", RECHECK_MODES)
def test_pending_verification_metadata_not_ready_carries_provider_status(monkeypatch, gcode_file, recheck_mode):
    out = _run(monkeypatch, gcode_file, recheck_mode=recheck_mode,
              confirmation={"present": True, "metadata_ready": False, "size_matches": True,
                            "fresh": True, "modified": 1.0})
    assert out["state"] == "pending_verification"
    assert out["provider_status"] == EXPECTED_STATUS[recheck_mode]


@pytest.mark.parametrize("recheck_mode", RECHECK_MODES)
def test_verified_carries_provider_status(monkeypatch, gcode_file, recheck_mode):
    out = _run(monkeypatch, gcode_file, recheck_mode=recheck_mode,
              confirmation={"present": True, "metadata_ready": True, "size_matches": True,
                            "fresh": True, "modified": 1.0})
    assert out["state"] == "verified"
    assert out["provider_status"] == EXPECTED_STATUS[recheck_mode]


@pytest.mark.parametrize("recheck_mode", RECHECK_MODES)
def test_not_listed_carries_provider_status(monkeypatch, gcode_file, recheck_mode):
    out = _run(monkeypatch, gcode_file, recheck_mode=recheck_mode,
              confirmation={"present": False, "metadata_ready": False, "size_matches": None,
                            "fresh": None, "modified": None})
    assert out["state"] == "not_listed"
    assert out["provider_status"] == EXPECTED_STATUS[recheck_mode]


@pytest.mark.parametrize("recheck_mode", RECHECK_MODES)
def test_mismatch_carries_provider_status(monkeypatch, gcode_file, recheck_mode):
    out = _run(monkeypatch, gcode_file, recheck_mode=recheck_mode,
              confirmation={"present": True, "metadata_ready": True, "size_matches": False,
                            "fresh": True, "modified": 1.0})
    assert out["state"] == "mismatch"
    assert out["provider_status"] == EXPECTED_STATUS[recheck_mode]


@pytest.mark.parametrize("recheck_mode", RECHECK_MODES)
def test_unknown_confirmation_error_carries_provider_status(monkeypatch, gcode_file, recheck_mode):
    out = _run(monkeypatch, gcode_file, recheck_mode=recheck_mode,
              confirmation_raises=RuntimeError("moonraker hiccup"))
    assert out["state"] == "unknown"
    assert out["provider_status"] == EXPECTED_STATUS[recheck_mode]


# --- "changed": only ever with a recheck --------------------------------------

def test_changed_state_carries_the_recheck_provider_status(monkeypatch, gcode_file):
    _install_fake_send_check(monkeypatch, mode="provider_ok", same_hashes=False)
    out = service.printer_upload_gcode(
        "printer.local", gcode_file, expect_state=_base_expect_state())
    assert out["state"] == "changed"
    assert out["uploaded"] is False
    assert out["provider_status"] == PS_OK
    assert out["check"]["provider_status"] == PS_OK


def test_changed_is_unreachable_without_a_recheck(monkeypatch, gcode_file):
    """No `expect_state` -> no recheck -> `send_check` is never called -> the
    `changed` state can never be produced. Proven by construction: patching
    `service.send_check` to always report a difference has no effect when the
    function that would call it is never reached."""
    def exploding_send_check(path, **kwargs):
        raise AssertionError("send_check must not run without expect_state")
    monkeypatch.setattr(service, "send_check", exploding_send_check)
    monkeypatch.setattr(
        moonraker, "upload_gcode",
        lambda host, path, port: {"ok": True, "action": "upload",
                                  "filename": "job.gcode", "path": "job.gcode", "size": 10})
    monkeypatch.setattr(
        moonraker, "confirm_upload",
        lambda host, filename, expected_size=None, port=7125: {
            "present": True, "metadata_ready": True, "size_matches": True,
            "fresh": True, "modified": 1.0})
    out = service.printer_upload_gcode("printer.local", gcode_file, expect_state=None)
    assert out["state"] != "changed"
    assert out["provider_status"] is None


# --- route-level (plan-39 B-1/B-3): through the REAL service.material_plan /
# service.send_check, against a real fake reader — not the send_check stub
# used above, which never reaches `_with_providers` at all.

def test_material_plan_route_carries_provider_status_shape(gcode_file):
    from fixtures.providers.spoolease_fake import FIXTURE_KEY, SpoolEaseFake

    with SpoolEaseFake(mode="http_500") as fake:
        out = service.material_plan(gcode_file, provider="spoolease",
                                    provider_url=fake.url, provider_key=FIXTURE_KEY)
    status = out["provider_status"]
    assert status == {
        "provider": "spoolease", "name": "SpoolEase", "available": False,
        "error": "SpoolEase did not answer: HTTP 500", "error_code": "http_status",
        "spools": 0, "with_weight": 0,
    }
    dumped = json.dumps(out)
    assert fake.url not in dumped
    assert FIXTURE_KEY not in dumped


def test_send_check_route_carries_provider_status_shape(gcode_file):
    from fixtures.providers.spoolease_fake import FIXTURE_KEY, SpoolEaseFake

    with SpoolEaseFake(mode="ok") as fake:
        out = service.send_check(gcode_file, provider="spoolease",
                                 provider_url=fake.url, provider_key=FIXTURE_KEY)
    status = out["provider_status"]
    assert status == {
        "provider": "spoolease", "name": "SpoolEase", "available": True,
        "error": None, "error_code": None, "spools": 3, "with_weight": 2,
    }
    dumped = json.dumps(out)
    assert fake.url not in dumped
    assert FIXTURE_KEY not in dumped


def test_send_check_route_unreachable_port_gives_transport(gcode_file):
    """A closed local port — no fake server at all — through the real route."""
    import socket as _socket

    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # closed immediately: nothing is listening on this port now

    out = service.send_check(gcode_file, provider="spoolease",
                             provider_url=f"http://127.0.0.1:{port}",
                             provider_key="Fx7-tEsT")
    status = out["provider_status"]
    assert status["available"] is False
    assert status["error_code"] == "transport"
    assert status["spools"] == 0
    assert status["with_weight"] == 0


def test_material_plan_route_a_raising_reader_gives_internal(monkeypatch, gcode_file):
    """B-4: a reader that raises must never propagate — `read()`'s own
    wrapping turns it into `error_code: "internal"`, through the real route."""
    from snapstudio_core import material_providers as providers

    def exploding_reader(base_url, slot_map=None, timeout=4.0, slot_base=None, key=None):
        raise RuntimeError("a reader defect, not a network failure")

    monkeypatch.setitem(providers.READERS, providers.SPOOLEASE, exploding_reader)
    out = service.material_plan(gcode_file, provider="spoolease",
                                provider_url="http://192.168.1.50", provider_key="anything")
    status = out["provider_status"]
    assert status["available"] is False
    assert status["error_code"] == "internal"
    assert "192.168.1.50" not in json.dumps(out)
