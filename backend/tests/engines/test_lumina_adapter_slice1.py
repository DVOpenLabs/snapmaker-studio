from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest

from snapstudio_core.engines.cli_runner import CliRunner, RunnerError
from snapstudio_core.engines.lumina import LuminaClient, LuminaError
from snapstudio_core.foundation.netguard import (
    NetguardRefused,
    clear_write_origins,
    local_request,
    require_local_url,
)
from tests.mocks.lumina_server import LuminaMock


def _pid_alive(pid: int) -> bool:
    """Liveness probe that does not signal the process.

    os.kill(pid, 0) is not a probe on Windows: it calls TerminateProcess and raises
    OSError (not ProcessLookupError) for a PID that no longer exists.
    """
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


@pytest.fixture
def mock_service():
    with LuminaMock() as service:
        yield service
    clear_write_origins()


def test_lumina_discovery_preview_and_artifact_are_mock_service_tested(mock_service):
    client = LuminaClient(mock_service.url, request=mock_service.request)
    discovery = client.discover()
    assert discovery.api_version == "2.0"
    assert "/api/convert/preview" in discovery.paths
    assert client.health_check() == {}
    preview = client.preview(b"synthetic-image", "input.png", lut_name="Default")
    assert preview["session_id"] == "session1"
    artifact = client.fetch_artifact("file1")
    assert artifact.sha256 == hashlib.sha256(b"mock-3mf").hexdigest()
    assert artifact.size_bytes == 8
    assert artifact.kind == "3mf"
    client.close()


def test_lumina_url_is_local_and_propagates_mock_redirect_refusal():
    with pytest.raises(NetguardRefused):
        require_local_url("https://example.invalid")
    with LuminaMock(mode="redirect") as service:
        with pytest.raises(NetguardRefused) as exc:
            LuminaClient(service.url, request=service.request).discover()
    assert exc.value.code == "redirect"


@pytest.mark.parametrize(("mode", "code"), [("large", "too_large"), ("slow", "deadline")])
def test_lumina_propagates_mock_oversize_and_slow_refusals(mode, code):
    with LuminaMock(mode=mode) as service:
        with pytest.raises(NetguardRefused) as exc:
            LuminaClient(service.url, request=service.request).discover()
    assert exc.value.code == code


def test_local_request_enforces_http_redirect_boundary_on_loopback():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/openapi.json"
        with pytest.raises(NetguardRefused) as exc:
            local_request("GET", url, timeout=1, max_bytes=1024)
        assert exc.value.code == "redirect"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=1)


@pytest.mark.parametrize(("mode", "version", "code"), [
    ("malformed", "2.0", "malformed_json"),
    ("normal", "99.0", "unsupported_version"),
])
def test_lumina_rejects_malformed_or_unsupported_discovery(mode, version, code):
    with LuminaMock(mode=mode, version=version) as service:
        with pytest.raises(LuminaError) as exc:
            LuminaClient(service.url, request=service.request).discover()
    assert exc.value.code == code


def test_lumina_does_not_invent_progress_cancel_or_accept_traversal(mock_service):
    client = LuminaClient(mock_service.url, request=mock_service.request)
    client.discover()
    with pytest.raises(LuminaError, match="progress_unknown"):
        client.progress("session1")
    with pytest.raises(LuminaError, match="cancel_unknown"):
        client.cancel("session1")
    with pytest.raises(LuminaError, match="invalid_file_id"):
        client.fetch_artifact("../outside")


def test_lumina_fixture_is_documentation_derived_preview_shape():
    fixture = Path(__file__).parents[1] / "fixtures" / "engines" / "lumina_api_2_preview.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    assert data["session_id"] == "session1"
    assert data["preview_url"] == "/api/files/file1"
    assert "threemf_disk_path" not in data


def _runner(tmp_path: Path, args: tuple[str, ...], *, timeout: float = 2,
            limit: int = 4096) -> CliRunner:
    root = tmp_path / "studio-jobs"
    root.mkdir()
    return CliRunner(sys.executable, root, args, timeout_s=timeout, output_limit=limit)


def test_cli_runner_stages_input_and_builds_artifact_manifest(tmp_path):
    scratch = tmp_path / "jobs-{output_dir}"
    scratch.mkdir()
    source = tmp_path / "original.3mf"
    source.write_bytes(b"original")
    # Paths reach the child through argv: embedding a Windows path in Python source breaks on its backslashes.
    code = "import sys; from pathlib import Path; Path(sys.argv[1], 'result.3mf').write_bytes(Path(sys.argv[2]).read_bytes())"
    runner = _runner(scratch, ("-c", code, "{output_dir}", "{input}"))
    result = runner.run(inputs={"input.3mf": str(source)})
    assert source.read_bytes() == b"original"
    assert result.artifacts == ({"name": "result.3mf", "sha256": hashlib.sha256(b"original").hexdigest(),
                                 "size_bytes": 8, "kind": "3mf"},)
    assert "{output_dir}" in str(result.job_dir)


def test_cli_runner_timeout_and_output_flood_are_bounded(tmp_path):
    scratch = tmp_path
    with pytest.raises(RunnerError) as timed:
        _runner(scratch, ("-c", "import time; time.sleep(3)"), timeout=0.1).run()
    assert timed.value.code == "timeout"
    flood_root = scratch / "flood-jobs"
    flood_root.mkdir()
    runner = CliRunner(sys.executable, flood_root, ("-c", "print('x' * 1000000)"),
                       timeout_s=2, output_limit=1024)
    with pytest.raises(RunnerError) as flooded:
        runner.run()
    assert flooded.value.code == "output_limit_exceeded"
    assert len(flooded.value.stdout) <= 1024


def test_cli_runner_cancels_only_its_active_process(tmp_path):
    scratch = tmp_path
    runner = _runner(scratch, ("-c", "import time; time.sleep(3)"), timeout=2)
    cancel = threading.Event()
    result: list[object] = []

    def run():
        try:
            result.append(runner.run(cancel_event=cancel))
        except Exception as exc:  # noqa: BLE001 - assertion inspects safe runner outcome
            result.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.1)
    cancel.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert isinstance(result[0], RunnerError)
    assert result[0].code == "cancelled"


def test_cli_runner_rejects_unsafe_template_and_output_symlink(tmp_path):
    scratch = tmp_path
    with pytest.raises(RunnerError, match="argument_template_invalid"):
        _runner(scratch, ("{arbitrary}",))
    outside = scratch / "outside"
    outside.write_text("secret")
    root = scratch / "escape-jobs"
    root.mkdir()
    code = "import sys; from pathlib import Path; Path(sys.argv[1], 'escape').symlink_to(Path(sys.argv[2]))"
    runner = CliRunner(sys.executable, root, ("-c", code, "{output_dir}", str(outside)), timeout_s=2)
    try:
        (scratch / "probe-link").symlink_to(outside)
    except OSError:
        # This account cannot create symlinks (unprivileged Windows). The runner refuses a symlink wherever it
        # finds one; that refusal is exercised without a real link in the next test.
        pytest.skip("this account is not allowed to create symlinks")
    with pytest.raises(RunnerError, match="artifact_symlink_refused"):
        runner.run()


def test_cli_runner_refuses_a_symlink_in_the_output_without_needing_symlink_privilege(monkeypatch, tmp_path):
    scratch = tmp_path
    code = "import sys; from pathlib import Path; Path(sys.argv[1], 'result.3mf').write_bytes(b'x')"
    runner = _runner(scratch, ("-c", code, "{output_dir}"))
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "result.3mf")
    with pytest.raises(RunnerError, match="artifact_symlink_refused"):
        runner.run()


def test_cli_runner_timeout_returns_when_grandchild_keeps_pipes_open(tmp_path):
    root = tmp_path / "jobs"
    root.mkdir()
    pid_file = tmp_path / "grandchild.pid"
    code = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "open(sys.argv[1],'w').write(str(child.pid)); time.sleep(30)"
    )
    runner = CliRunner(sys.executable, root, ("-c", code, str(pid_file)), timeout_s=0.15)
    started = time.monotonic()
    try:
        with pytest.raises(RunnerError) as exc:
            runner.run()
        elapsed = time.monotonic() - started
        assert exc.value.code == "timeout"
        assert elapsed < 2.5
    finally:
        if pid_file.exists():
            grandchild_pid = int(pid_file.read_text())
        else:
            grandchild_pid = None
        # This exact PID was created by the fixture script above; no process-name sweep.
        if grandchild_pid is not None and _pid_alive(grandchild_pid):
            os.kill(grandchild_pid, signal.SIGTERM)


def test_cli_runner_stops_child_after_unexpected_poll_exception(monkeypatch, tmp_path):
    root = tmp_path / "jobs"
    root.mkdir()
    pid_file = tmp_path / "runner-child.pid"
    runner = CliRunner(sys.executable, root, ("-c", "import os,sys,time; open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(30)", str(pid_file)), timeout_s=10)

    def fail_scan(_output_dir):
        # Do not inject the polling failure until the exact owned child has written
        # its PID. This proves cleanup after an unexpected poll exception without
        # racing process startup or weakening the stopped-child assertion.
        deadline = time.monotonic() + 2
        while not pid_file.exists():
            if time.monotonic() >= deadline:
                raise AssertionError("runner child did not publish its PID")
            time.sleep(0.005)
        raise RuntimeError("synthetic scan failure")

    monkeypatch.setattr(runner, "_output_size", fail_scan)
    child_pid = None
    try:
        with pytest.raises(RuntimeError, match="synthetic scan failure"):
            runner.run()
        child_pid = int(pid_file.read_text())
        assert not _pid_alive(child_pid)
    finally:
        if child_pid is None and pid_file.exists():
            child_pid = int(pid_file.read_text())
        if child_pid is not None and _pid_alive(child_pid):
            os.kill(child_pid, signal.SIGTERM)


def test_cli_runner_refuses_windows_script_entry_points(tmp_path):
    root = tmp_path / "jobs"
    root.mkdir()
    executable = tmp_path / "engine.cmd"
    executable.write_text("echo synthetic")
    with pytest.raises(RunnerError, match="executable_script_refused"):
        CliRunner(executable, root, ())


def test_cli_runner_output_scan_refuses_oserror_junctions_and_unbounded_trees(monkeypatch, tmp_path):
    root = tmp_path / "jobs"
    root.mkdir()
    runner = CliRunner(sys.executable, root, ())
    output = tmp_path / "output"
    output.mkdir()

    monkeypatch.setattr("snapstudio_core.engines.cli_runner.os.scandir",
                        lambda _path: (_ for _ in ()).throw(OSError("synthetic scan failure")))
    with pytest.raises(RunnerError, match="artifact_scan_failed"):
        runner._output_size(output)

    monkeypatch.undo()
    junction_dir = output / "junction"
    junction_dir.mkdir()
    monkeypatch.setattr(Path, "is_junction", lambda self: self.name == "junction", raising=False)
    with pytest.raises(RunnerError, match="artifact_symlink_refused"):
        runner._output_size(output)

    monkeypatch.undo()
    (output / "a").write_text("a")
    (output / "b").write_text("b")
    monkeypatch.setattr("snapstudio_core.engines.cli_runner._MAX_SCAN_ENTRIES", 1)
    with pytest.raises(RunnerError, match="artifact_scan_limit_exceeded"):
        runner._output_size(output)
