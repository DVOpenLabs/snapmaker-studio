"""E-suite (plan-39 §7): proof against the SAME extracted/frozen sidecar
binary a release actually ships — not the source tree — because a PyInstaller
freeze is exactly the kind of place a lazily-imported dependency
(`cryptography`) can go missing without a single unit test noticing.

Skipped (not failed) when ``SNAPSTUDIO_SIDECAR_EXE`` is unset. FAILS (not
skipped) when it is set but does not point at a real file (plan-39 v3.4 L-5) —
a CI job that meant to run this and typo'd the path must not silently pass.

Terminates only the child process this test itself started.
"""
from __future__ import annotations

import http.client
import json
import os
import queue
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from fixtures.providers.spoolease_fake import FIXTURE_KEY, SpoolEaseFake  # noqa: E402

_EXE = os.environ.get("SNAPSTUDIO_SIDECAR_EXE")

if _EXE is None:
    pytestmark = pytest.mark.skip(reason="SNAPSTUDIO_SIDECAR_EXE not set")
elif not os.path.isfile(_EXE):
    # plan-39 v3.4 L-5: set but wrong is a red build, not a quiet skip — a
    # collection-time failure (nonzero exit), not `xfail` (which would let a
    # typo'd CI path pass green).
    raise AssertionError(
        f"SNAPSTUDIO_SIDECAR_EXE={_EXE!r} is set but does not point at a real file")


def _request(port: int, token: str, route: str, payload: dict) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json", "X-Auth-Token": token}
        connection.request("POST", route, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        return response.status, (json.loads(raw) if raw else {})
    finally:
        connection.close()


@pytest.fixture(scope="module")
def sidecar():
    env = dict(os.environ)
    env.pop("SNAPSTUDIO_API_PORT", None)  # ephemeral port, exactly as the app runs it
    proc = subprocess.Popen(
        [_EXE], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, text=True, bufsize=1)
    try:
        # `proc.stdout.readline()` itself has no timeout, so calling it
        # directly inside a "while time.monotonic() < deadline" loop does not
        # make the deadline effective: a sidecar that never writes a line and
        # never closes stdout hangs the test past 15s regardless of the loop
        # condition. A reader thread that never blocks the main thread does —
        # and works the same on Windows and Linux, unlike a `select()`/
        # `signal.alarm` approach, neither of which is available on both.
        lines: "queue.Queue[str]" = queue.Queue()

        def _read_handshake_line():
            try:
                lines.put(proc.stdout.readline())
            except (ValueError, OSError):
                pass  # the pipe closed under us — the main thread times out

        reader = threading.Thread(target=_read_handshake_line, daemon=True)
        reader.start()
        try:
            line = lines.get(timeout=15)
        except queue.Empty:
            line = ""
        if not line.strip():
            proc.kill()
            proc.wait(10)
            raise AssertionError("the sidecar never printed a handshake line")
        handshake = json.loads(line)
        yield handshake["port"], handshake["token"]
    finally:
        # Only the PID this fixture itself started.
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(10)


def test_provider_test_reads_the_fixture_through_the_frozen_binary(sidecar):
    port, token = sidecar
    with SpoolEaseFake(mode="ok") as fake:
        status, out = _request(port, token, "/provider/test",
                               {"url": fake.url, "provider": "spoolease",
                                "provider_key": FIXTURE_KEY})
    assert status == 200
    assert out["ok"] is True
    assert out["spools"] == 3
    assert out["with_weight"] == 2


def test_provider_test_wrong_key_through_the_frozen_binary(sidecar):
    port, token = sidecar
    with SpoolEaseFake(mode="wrong_key") as fake:
        status, out = _request(port, token, "/provider/test",
                               {"url": fake.url, "provider": "spoolease",
                                "provider_key": FIXTURE_KEY})
    assert status == 200
    assert out["ok"] is False
    assert out["error_code"] == "authentication_failed"


def test_material_plan_carries_provider_status_through_the_frozen_binary(
        sidecar, tmp_path):
    port, token = sidecar
    gcode_path = tmp_path / "job.gcode"
    gcode_path.write_text("; not a real slice, only exercising provider_status\n")
    with SpoolEaseFake(mode="ok") as fake:
        status, out = _request(port, token, "/material_plan", {
            "path": str(gcode_path), "provider": "spoolease", "provider_url": fake.url,
            "provider_key": FIXTURE_KEY, "slot_map": {"1": "1"}})
    assert status == 200
    assert out["provider_status"]["available"] is True
    assert out["provider_status"]["provider"] == "spoolease"


def test_both_build_scripts_name_cryptography_in_their_import_probe():
    """A tiny source pin (E-suite tail): the frozen build cannot pick up a
    dependency its own probe never asked for."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "desktop" / "scripts"
    for name in ("build-sidecar.ps1", "build-sidecar.sh"):
        text = (root / name).read_text("utf-8")
        assert "cryptography" in text, f"{name} does not mention cryptography"
