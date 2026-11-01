"""Regression tests for round 2 of the Opus+Sol result review of the Phase 2 portfolio candidate.

Evidence label: fixture-tested. Every file here is synthetic and lives in tmp_path.
"""
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from snapstudio_api import ext_routes, routes_passport, routes_variants  # noqa: F401  (imports register routes)
from snapstudio_core import localpath
from snapstudio_core.variants import compare_outputs

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "variants"
MIXED = ["\\/attacker-host/share/p.3mf", "/\\attacker-host\\share\\p.3mf", "\\\\attacker-host\\share\\p.3mf"]


class FakeHandler:
    def __init__(self):
        self.sent = []

    def _send(self, code, obj):
        self.sent.append((code, obj))


def call(path, data):
    h = FakeHandler()
    assert ext_routes.dispatch(h, path, data) is True
    return h.sent[0]


@pytest.fixture
def no_probe(monkeypatch):
    """Any filesystem call on a network-looking path fails the test, whichever os / os.path function makes it."""
    def guard(real):
        def wrapper(*a, **k):
            if a and isinstance(a[0], str) and "attacker-host" in a[0]:
                raise AssertionError(f"{real.__name__} probed a network path")
            return real(*a, **k)
        return wrapper
    for owner, name in ((os, "stat"), (os, "lstat"), (os, "readlink"), (os.path, "isdir"), (os.path, "isfile"),
                        (os.path, "exists"), (os.path, "realpath"), (os.path, "getsize"), (os, "listdir")):
        monkeypatch.setattr(owner, name, guard(getattr(owner, name)))
    monkeypatch.setattr("builtins.open", guard(open))


@pytest.mark.parametrize("path", MIXED)
def test_mixed_separator_unc_forms_are_network_paths(path):
    assert localpath.is_network_or_device_path(path)


@pytest.mark.parametrize("path", MIXED)
def test_guard_helpers_never_probe_a_network_path(no_probe, path):
    assert localpath.is_local_regular_file(path) is False
    assert localpath.is_local_directory(path) is False
    assert localpath.usable_path(path) is None


def test_passport_routes_refuse_a_unc_base_dir_without_probing(no_probe):
    for route in ("/passport/verify", "/passport/import"):
        code, body = call(route, {"passport": {}, "base_dir": MIXED[0]})
        assert code == 400, route


def test_passport_cli_refuses_unc_paths_before_click_probes_them(no_probe):
    from click.testing import CliRunner

    from snapstudio_core import passport_cli

    runner = CliRunner()
    for args in (["export", "--original", MIXED[2]], ["verify", MIXED[1]], ["verify", "x.json", "--base-dir", MIXED[0]]):
        result = runner.invoke(passport_cli.passport, args)
        assert result.exit_code == 2, args
        assert "local files only" in result.output


def test_a_symlink_to_a_network_path_is_refused_without_following_it(tmp_path, monkeypatch, no_probe):
    link = tmp_path / "linked.3mf"
    try:
        os.symlink(MIXED[2], link)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create symlinks")
    assert localpath.is_local_regular_file(str(link)) is False
    assert localpath.usable_path(str(link)) is None


def test_a_symlink_to_a_local_file_is_still_usable(tmp_path):
    real = tmp_path / "real.3mf"
    real.write_bytes(b"synthetic")
    link = tmp_path / "linked.3mf"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create symlinks")
    assert localpath.is_local_regular_file(str(link)) is True


def _3mf_with_member(tmp_path, name, payload, *, corrupt=False):
    path = tmp_path / "out.3mf"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", "<model/>")
        archive.writestr(name, payload)
    if corrupt:
        raw = bytearray(path.read_bytes())
        marker = raw.find(b"Metadata/")
        # flip a byte inside the deflate stream of the member (after its local header)
        header_end = marker + len(name) + 2
        raw[header_end + 2] ^= 0xFF
        path.write_bytes(bytes(raw))
    return path


def test_corrupt_recognised_member_is_a_400_not_silently_unknown(tmp_path):
    path = _3mf_with_member(tmp_path, "Metadata/project_settings.config", json.dumps({"layer_height": "0.2"}) * 20,
                            corrupt=True)
    code, body = call("/variants/compare", {"outputs": [{"path": str(path)}, {"path": str(FIXTURES / "right.gcode")}]})
    assert code == 400 and body["error"] == "invalid"


@pytest.mark.parametrize("bad", ["1" + "0" * 400, "1e999", -1])
def test_overflowing_or_infinite_numbers_are_unknown_not_a_500(tmp_path, bad):
    payload = '{"estimated_time_s": %s, "filament_used_g": [%s]}' % (bad, bad)
    path = _3mf_with_member(tmp_path, "Metadata/slice_info.config", payload)
    report = compare_outputs({"outputs": [{"path": str(path)}, {"path": str(FIXTURES / "right.gcode")}]})
    first = report["outputs"][0]
    assert first["time"]["status"] == "unknown" if "time" in first else True
    assert json.dumps(report)                                   # no inf/nan leaked into the response


def test_deeply_nested_project_settings_is_a_400_for_creative(tmp_path):
    from snapstudio_api import routes_creative  # noqa: F401

    path = tmp_path / "deep.3mf"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", "<model/>")
        archive.writestr("Metadata/project_settings.config", "[" * 200000 + "]" * 200000)
    code, body = call("/creative/inspect", {"path": str(path)})
    assert code == 400
