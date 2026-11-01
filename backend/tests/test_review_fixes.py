"""Regression tests for the Opus+Sol result review of the Phase 2 portfolio candidate.

Evidence label: fixture-tested. Every file here is synthetic and lives in tmp_path.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from snapstudio_api import ext_routes, routes_creative, routes_variants  # noqa: F401  (imports register routes)
from snapstudio_core import localpath
from snapstudio_core.calibration import palette, service
from snapstudio_core.passport import build_passport

UNC = r"\\attacker-host\share\project.3mf"
DEVICE = r"\\?\C:\project.3mf"


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
def no_filesystem_probe(monkeypatch):
    """Fail the test if a network or device path reaches any open/stat/listing call."""
    def guarded(real):
        def wrapper(*a, **k):
            if a and isinstance(a[0], str) and localpath.is_network_or_device_path(a[0]):
                raise AssertionError("a network or device path reached the filesystem")
            return real(*a, **k)
        return wrapper
    monkeypatch.setattr(os, "stat", guarded(os.stat))
    monkeypatch.setattr("builtins.open", guarded(open))


@pytest.mark.parametrize("path", [UNC, DEVICE, "//attacker-host/share/p.3mf"])
def test_network_and_device_paths_are_refused_before_any_filesystem_access(path):
    assert localpath.is_network_or_device_path(path)
    assert localpath.is_local_regular_file(path) is False
    assert localpath.usable_path(path) is None


def test_creative_route_refuses_unc_with_a_400(no_filesystem_probe):
    code, body = call("/creative/inspect", {"path": UNC})
    assert code == 400 and body["error"] == "invalid"


def test_variants_route_refuses_unc_with_a_400(no_filesystem_probe):
    code, body = call("/variants/compare", {"outputs": [{"path": UNC}, {"path": UNC}]})
    assert code == 400 and body["error"] == "invalid"


def test_passport_build_refuses_unc_as_unreadable(no_filesystem_probe):
    built = build_passport([{"path": UNC, "role": "original"}])
    assert built.passport is None
    assert built.diagnostics[0].code == "file_unreadable"


def test_directory_and_missing_paths_are_not_local_regular_files(tmp_path):
    assert localpath.is_local_regular_file(str(tmp_path)) is False
    assert localpath.is_local_regular_file(str(tmp_path / "nope.3mf")) is False
    assert localpath.usable_path(str(tmp_path / "nope.3mf")) == str(tmp_path / "nope.3mf")  # missing stays missing


def test_oversize_file_is_not_a_usable_path(tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 64)
    assert localpath.is_local_regular_file(str(big), max_bytes=10) is False
    assert localpath.usable_path(str(big), max_bytes=10) is None


@pytest.mark.parametrize("flag", [True, None, "omitted"])
def test_passport_never_repeats_an_execution_claim(tmp_path, flag):
    original = tmp_path / "a.3mf"
    original.write_bytes(b"synthetic")
    recipe = {"schema_version": "virtual_recipe/1", "recipe_id": "synthetic:mix",
              "generator": {"name": "synthetic", "version": "1"}, "kind": "custom",
              "components": [{"slot_ref": "slot:0", "ratio": 1, "ratio_kind": "mass"}], "simulated": True}
    if flag != "omitted":
        recipe["execution_supported"] = flag
    built = build_passport([{"path": str(original), "role": "original"}], recipes=[recipe])
    assert built.passport is not None
    document = built.passport.to_dict()
    assert [r["execution_supported"] for r in document["recipes"]] == [False]
    assert all(r["simulated"] is True for r in document["recipes"])


def test_repeated_calibration_with_different_readings_keeps_both_runs(tmp_path):
    parsed = palette.parse_ditherforge("#112233 td Ink").value.to_dict()
    basis = service.basis_document("frontlit", 0.2, 0.4, "PLA")
    d = str(tmp_path)
    first = service.save_run(basis, parsed, service.evaluate(parsed, basis, {"0": "#102030"}, []), data_dir=d)
    second = service.save_run(basis, parsed, service.evaluate(parsed, basis, {"0": "#FFFFFF"}, []), data_dir=d)
    assert first["run_id"] != second["run_id"]
    assert first["inputs_revision"]["revision"] != second["inputs_revision"]["revision"]
    assert len(service.history(data_dir=d)) == 2
    again = service.save_run(basis, parsed, service.evaluate(parsed, basis, {"0": "#102030"}, []), data_dir=d)
    assert again["run_id"] == first["run_id"] and len(service.history(data_dir=d)) == 2


def test_export_refuses_a_destination_that_appears_before_publication(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from snapstudio_core import passport_cli

    original = tmp_path / "a.3mf"
    original.write_bytes(b"synthetic")
    target = tmp_path / "out.passport.json"
    real_link = os.link

    def racing_link(src, dst, *a, **k):
        Path(dst).write_text("someone else's file", encoding="utf-8")   # appears after validation
        return real_link(src, dst, *a, **k)

    monkeypatch.setattr(os, "link", racing_link)
    result = CliRunner().invoke(passport_cli.passport, ["export", "--original", str(original), "-o", str(target)])
    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["code"] == "output_exists"
    assert target.read_text(encoding="utf-8") == "someone else's file"
    assert not list(tmp_path.glob("*.tmp"))
