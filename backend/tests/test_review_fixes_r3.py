"""Regression tests for round 3 of the Opus+Sol result review of the Phase 2 portfolio candidate.

Evidence label: fixture-tested. Every file here is synthetic and lives in tmp_path.
"""
from __future__ import annotations

import json
import lzma
import os
import stat
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from snapstudio_api import ext_routes
from snapstudio_core import localpath, passport_cli

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "variants"
UNC_OUT = "\\\\attacker-host\\share\\out.passport.json"
MIXED_OUT = "/\\attacker-host/share/out.passport.json"
DEVICE_OUT = "\\\\.\\C:\\out.passport.json"


class FakeHandler:
    def __init__(self):
        self.sent = []

    def _send(self, code, obj):
        self.sent.append((code, obj))


def call(path, data):
    h = FakeHandler()
    assert ext_routes.dispatch(h, path, data) is True
    return h.sent[0]


def test_windows_readlink_form_of_a_local_drive_is_plain_but_network_forms_stay_refused():
    assert localpath._plain_drive_target("\\\\?\\C:\\models") == "C:\\models"
    assert localpath._plain_drive_target("\\\\?\\UNC\\host\\share\\x") == "\\\\?\\UNC\\host\\share\\x"
    assert localpath._plain_drive_target("\\\\.\\C:\\x") == "\\\\.\\C:\\x"
    assert localpath._plain_drive_target("\\\\?\\Volume{1234}\\x") == "\\\\?\\Volume{1234}\\x"
    assert localpath._plain_drive_target("C:\\plain") == "C:\\plain"


class _Link:
    st_mode = stat.S_IFLNK


def _simulate(monkeypatch, link: str, target: str):
    real_lstat = os.lstat
    monkeypatch.setattr(os, "lstat", lambda p, *a, **k: _Link() if p == link else real_lstat(p, *a, **k))
    monkeypatch.setattr(os, "readlink", lambda p, *a, **k: target if p == link else (_ for _ in ()).throw(OSError()))


@pytest.mark.skipif(os.name != "nt", reason="the readlink form being simulated is Windows-specific")
def test_junction_to_a_local_drive_as_windows_reports_it_is_not_refused(monkeypatch, tmp_path):
    link = str(tmp_path / "models")
    _simulate(monkeypatch, link, "\\\\?\\" + str(tmp_path / "real"))
    assert localpath._reaches_network(link) is False


def test_junction_to_a_unc_share_as_windows_reports_it_is_refused(monkeypatch, tmp_path):
    link = str(tmp_path / "models")
    _simulate(monkeypatch, link, "\\\\?\\UNC\\attacker-host\\share\\x")
    assert localpath._reaches_network(link) is True


@pytest.fixture
def no_probe(monkeypatch):
    def guard(real):
        def wrapper(*a, **k):
            if a and isinstance(a[0], str) and "attacker-host" in a[0]:
                raise AssertionError(f"{real.__name__} probed a network path")
            return real(*a, **k)
        return wrapper
    for owner, name in ((os, "stat"), (os, "lstat"), (os.path, "exists"), (os.path, "isdir"), (os.path, "isfile"),
                        (os, "link"), (os, "rename")):
        monkeypatch.setattr(owner, name, guard(getattr(owner, name)))
    import tempfile
    monkeypatch.setattr(tempfile, "mkstemp", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("mkstemp reached") if "attacker-host" in str(k.get("dir", "")) else OSError()))
    monkeypatch.setattr("builtins.open", guard(open))


@pytest.mark.parametrize("out", [UNC_OUT, MIXED_OUT, DEVICE_OUT])
def test_export_output_on_a_network_or_device_path_is_refused_before_any_probe(no_probe, tmp_path, out):
    original = tmp_path / "a.3mf"
    original.write_bytes(b"synthetic")
    result = CliRunner().invoke(passport_cli.passport, ["export", "--original", str(original), "-o", out])
    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["code"] == "bad_output"


def test_export_output_below_a_link_to_a_share_is_refused(monkeypatch, tmp_path):
    original = tmp_path / "a.3mf"
    original.write_bytes(b"synthetic")
    link = str(tmp_path / "outdir")
    _simulate(monkeypatch, link, "\\\\attacker-host\\share\\dir")
    result = CliRunner().invoke(passport_cli.passport,
                                ["export", "--original", str(original), "-o", os.path.join(link, "p.json")])
    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["code"] == "bad_output"


@pytest.mark.skipif(os.name != "nt", reason="the no-hard-link fallback publishes with an atomic Windows rename")
def test_export_without_hard_links_publishes_the_whole_file_atomically(monkeypatch, tmp_path):
    original = tmp_path / "a.3mf"
    original.write_bytes(b"synthetic")
    target = tmp_path / "out.passport.json"
    monkeypatch.setattr(os, "link", lambda *a, **k: (_ for _ in ()).throw(PermissionError("no hard links")))
    result = CliRunner().invoke(passport_cli.passport, ["export", "--original", str(original), "-o", str(target)])
    assert result.exit_code == 0, result.output
    assert json.loads(target.read_text(encoding="utf-8"))["schema_version"] == "passport/1"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="the no-hard-link fallback publishes with an atomic Windows rename")
def test_export_without_hard_links_never_replaces_a_destination_that_appears(monkeypatch, tmp_path):
    original = tmp_path / "a.3mf"
    original.write_bytes(b"synthetic")
    target = tmp_path / "out.passport.json"
    real_rename = os.rename

    def racing_rename(src, dst, *a, **k):
        Path(dst).write_text("someone else's file", encoding="utf-8")
        return real_rename(src, dst, *a, **k)

    monkeypatch.setattr(os, "link", lambda *a, **k: (_ for _ in ()).throw(PermissionError("no hard links")))
    monkeypatch.setattr(os, "rename", racing_rename)
    result = CliRunner().invoke(passport_cli.passport, ["export", "--original", str(original), "-o", str(target)])
    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["code"] == "output_exists"
    assert target.read_text(encoding="utf-8") == "someone else's file"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("error", [EOFError("truncated"), lzma.LZMAError("corrupt")])
def test_truncated_or_corrupt_compressed_member_is_a_400(monkeypatch, tmp_path, error):
    path = tmp_path / "out.3mf"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", "<model/>")
        archive.writestr("Metadata/slice_info.config", json.dumps({"estimated_time_s": 5}))

    def broken_read(self, *a, **k):
        raise error

    monkeypatch.setattr(zipfile.ZipFile, "read", broken_read)
    code, body = call("/variants/compare", {"outputs": [{"path": str(path)}, {"path": str(FIXTURES / "right.gcode")}]})
    assert code == 400 and body["error"] == "invalid"
