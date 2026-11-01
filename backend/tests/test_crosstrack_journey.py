"""Test 11: synthetic cross-track journey through route dispatch, the Prepare service and the real passport CLI.

Not covered: the HTTP transport and token, the HTTP /convert handler, /creative/prepare, the desktop UI, and a process crash or restart.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import http.client
import struct
from pathlib import Path
import zipfile

from snapstudio_api import ext_routes
from snapstudio_api import service
from snapstudio_core.stl_wrap import wrap_stl
from tests.mocks.hosts.host_mocks import MockHost


class _Dispatch:
    def __init__(self):
        self.result = None

    def _send(self, status, body):
        self.result = status, body


def _post(path: str, data: dict) -> tuple[int, dict]:
    handler = _Dispatch()
    assert ext_routes.dispatch(handler, path, data)
    assert handler.result is not None
    return handler.result


def _forca_project(path: Path) -> Path:
    """Add a published FOrca key to a synthetic project archive used by Prepare."""
    staged = path.with_suffix(".staged.3mf")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "Metadata/project_settings.config":
                settings = json.loads(data)
                settings["fos_physical_nozzle_diameter"] = [0.4]
                data = json.dumps(settings).encode()
            dst.writestr(item, data)
    staged.replace(path)
    return path


def _synthetic_project(path: Path) -> Path:
    """Build a tiny geometry archive entirely from synthetic tetrahedron bytes."""
    stl = path.with_suffix(".stl")
    head = b"\0" * 80 + struct.pack("<I", 2)
    for v1, v2, v3 in [((0, 0, 0), (10, 0, 0), (0, 10, 0)),
                       ((0, 0, 0), (0, 10, 0), (0, 0, 10))]:
        head += struct.pack("<12fH", 0, 0, 0, *v1, *v2, *v3, 0)
    stl.write_bytes(head)
    wrap_stl(str(stl)).save(path)
    stl.unlink()
    return _forca_project(path)


def test_11_cross_track_prepare_passport_checkpoint_mutation_and_read_only_restore(tmp_path, monkeypatch):
    """Exercise inspect -> Prepare -> passport CLI -> checkpoint -> mutation -> preview."""
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "studio-data"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    # (a) A synthetic FOrca-tagged creative project enters via the real route dispatch.
    original = _synthetic_project(tmp_path / "synthetic-project.3mf")
    before = original.read_bytes()
    code, inspected = _post("/creative/inspect", {"path": str(original), "format": "forcaslicer"})
    assert code == 200 and inspected["origin"]["generator"] == "forcaslicer"
    assert inspected["source"]["unchanged"] is True and original.read_bytes() == before

    # (b) Prepare calls the same service entry used by the HTTP /convert handler.
    result = service.convert(str(original), str(tmp_path))
    prepared = Path(result["output_path"])
    assert result["validated_ok"] is True and prepared != original and prepared.is_file()
    assert original.read_bytes() == before

    # (c) Build a declared original -> prepared chain and verify through the real CLI module.
    code, built = _post("/passport/build", {"entries": [
        {"path": str(original), "role": "original"},
        {"path": str(prepared), "role": "prepared", "parents": [0]},
    ]})
    assert code == 200 and built["passport"]
    passport_file = tmp_path / "job.passport.json"
    passport_file.write_text(json.dumps(built["passport"]), encoding="utf-8")
    cli = subprocess.run(
        [sys.executable, "-m", "u1convert.cli", "passport", "verify", str(passport_file),
         "--base-dir", str(tmp_path)], cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True, text=True, timeout=120, check=False,
    )
    initial_verification = json.loads(cli.stdout)
    assert cli.returncode == 0 and initial_verification["ok"] is True
    assert initial_verification["verification"]["summary"]["all_intact"] is True

    # (d) Checkpoint the original, the prepared copy and an additional synthetic tracked file (three files).
    extra = tmp_path / "synthetic-sliced.gcode"
    extra.write_text("synthetic sliced stand-in", encoding="utf-8")
    code, checkpoint = _post("/recovery/checkpoint", {"workspace": {"name": "Synthetic demo"},
        "files": [{"name": p.name, "path": str(p)} for p in (original, prepared, extra)],
        "jobs": [{"job_id": "synthetic-job", "state": "running"}]})
    assert code == 200 and checkpoint["file_count"] == 3

    # (e) Mutate prepared bytes, delete an extra file, then replace the original by the same name.
    prepared.write_bytes(prepared.read_bytes() + b"synthetic post-checkpoint mutation")
    extra.unlink()
    original.unlink()
    original.write_bytes(b"different synthetic file with the same name")
    cli = subprocess.run(
        [sys.executable, "-m", "u1convert.cli", "passport", "verify", str(passport_file),
         "--base-dir", str(tmp_path)], cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True, text=True, timeout=120, check=False,
    )
    changed_verification = json.loads(cli.stdout)
    summary = changed_verification["verification"]["summary"]
    assert cli.returncode == 1 and changed_verification["ok"] is False
    assert summary["all_intact"] is False and summary["invalidated"]
    assert all(item["bytes"] != "same" for item in changed_verification["verification"]["artifacts"])

    # Monitoring is the sole network capability used here. The sentinel records every verb/path.
    mock = MockHost({
        "/printer/objects/query": (200, {"result": {"status": {"print_stats": {"state": "standby"}}}}),
        "/server/history/list": (200, {"result": {"jobs": []}}),
    }).start()
    try:
        for endpoint in ("/monitoring/read", "/monitoring/history"):
            code, _ = _post(endpoint, {"host": "127.0.0.1", "port": mock.server_address[1]})
            assert code == 200
        before_restore_requests = len(mock.requests)
        code, preview = _post("/recovery/restore", {})
        after_restore_requests = len(mock.requests)
        assert code == 200 and after_restore_requests == before_restore_requests
    finally:
        mock.stop()

    # (f) The original path now resolves to different bytes; the prepared file changed; extra is missing.
    states = {item["name"]: item["state"] for item in preview["files"]}
    assert states == {original.name: "changed", prepared.name: "changed", extra.name: "missing"}
    assert preview["jobs"][0] == {"job_id": "synthetic-job", "state": "interrupted", "replayed": False}
    observed = [(request["method"], request["path"]) for request in mock.requests]
    # Sentinel: any non-GET or unapproved GET reaches this assertion and fails the journey.
    assert observed == [("GET", "/printer/objects/query"), ("GET", "/server/history/list")]



def test_11_sentinel_records_every_verb_it_would_have_to_reject():
    """The request sentinel used by test 11 must see HEAD, OPTIONS, write verbs and unapproved paths."""
    mock = MockHost({"/printer/objects/query": (200, {"result": {}})}).start()
    try:
        port = mock.server_address[1]
        for method, path in (("HEAD", "/printer/objects/query"), ("OPTIONS", "/printer/objects/query"),
                             ("PUT", "/printer/objects/query"), ("DELETE", "/x"), ("POST", "/printer/print/start"),
                             ("GET", "/printer/gcode/script")):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request(method, path)
            connection.getresponse().read()
            connection.close()
        observed = [(request["method"], request["path"]) for request in mock.requests]
    finally:
        mock.stop()
    assert observed == [("HEAD", "/printer/objects/query"), ("OPTIONS", "/printer/objects/query"),
                        ("PUT", "/printer/objects/query"), ("DELETE", "/x"), ("POST", "/printer/print/start"),
                        ("GET", "/printer/gcode/script")]
    assert observed != [("GET", "/printer/objects/query"), ("GET", "/server/history/list")]
