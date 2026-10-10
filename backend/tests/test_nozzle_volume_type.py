"""A prepared copy must not carry Bambu's `nozzle_volume_type` (issue 39).

Genuine Snapmaker-authored U1 projects have no such key. A Bambu-authored project carries it beside the
U1's four nozzles, and a reporter's copy showed a 'newer version, values replaced' notice naming it. That
notice is not confirmed in Snapmaker Orca, so these tests pin what Studio writes, not what Orca does.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from snapstudio_core import orca_import
from snapstudio_core.convert import convert_to_u1

FIXTURES = Path(__file__).parent / "fixtures" / "painted"
BAMBU = FIXTURES / "bambustudio-2.08.02.61-authored.3mf"
SNAPMAKER = FIXTURES / "snapmaker-orca-2.3.5-authored.3mf"
SETTINGS = "Metadata/project_settings.config"


def _settings(path) -> dict:
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read(SETTINGS))


def _prepare(src: Path, out: Path, mode: str):
    result = convert_to_u1(str(src), str(out), prepare_mode=mode)
    assert result.validated_ok, result.errors
    return result


@pytest.mark.parametrize("mode", ["preserve", "recommended"])
def test_bambu_copy_has_no_nozzle_volume_type(tmp_path, mode):
    assert _settings(BAMBU)["nozzle_volume_type"] == ["Standard"]      # the fixture really carries it
    result = _prepare(BAMBU, tmp_path, mode)
    assert "nozzle_volume_type" not in _settings(result.output_path)


@pytest.mark.parametrize("mode", ["preserve", "recommended"])
def test_only_that_key_differs_from_a_copy_made_without_the_rule(tmp_path, monkeypatch, mode):
    with_rule = _settings(_prepare(BAMBU, tmp_path / "a", mode).output_path)
    monkeypatch.setattr(orca_import, "_drop_foreign_nozzle_volume_type", lambda cfg, changes: None)
    without_rule = _settings(_prepare(BAMBU, tmp_path / "b", mode).output_path)
    assert without_rule["nozzle_volume_type"] == ["Standard"]
    differing = {k for k in set(with_rule) | set(without_rule) if with_rule.get(k, "<absent>") != without_rule.get(k, "<absent>")}
    assert differing == {"nozzle_volume_type"}


@pytest.mark.parametrize("mode", ["preserve", "recommended"])
def test_the_removal_is_a_recorded_change_with_a_plain_reason(tmp_path, mode):
    result = _prepare(BAMBU, tmp_path, mode)
    summary = result.settings_summary
    rows = [r for group in ("compat_changed", "mapped_to_u1") for r in summary[group] if r["key"] == "nozzle_volume_type"]
    assert len(rows) == 1
    assert "genuine U1" in rows[0]["reason"]
    assert "not been confirmed in Snapmaker Orca" in rows[0]["explanation"]


def test_the_removal_is_not_declared_as_a_preset_deviation(tmp_path):
    cfg = _settings(_prepare(BAMBU, tmp_path, "preserve").output_path)
    assert all("nozzle_volume_type" not in str(e) for e in cfg.get("different_settings_to_system") or [])


def test_the_original_is_never_modified(tmp_path):
    before = BAMBU.read_bytes()
    _prepare(BAMBU, tmp_path, "preserve")
    assert BAMBU.read_bytes() == before


def test_a_snapmaker_authored_project_is_not_touched_by_the_rule(tmp_path, monkeypatch):
    assert "nozzle_volume_type" not in _settings(SNAPMAKER)
    with_rule = _settings(_prepare(SNAPMAKER, tmp_path / "a", "preserve").output_path)
    monkeypatch.setattr(orca_import, "_drop_foreign_nozzle_volume_type", lambda cfg, changes: None)
    without_rule = _settings(_prepare(SNAPMAKER, tmp_path / "b", "preserve").output_path)
    assert with_rule == without_rule
    assert "nozzle_volume_type" not in with_rule


def test_rule_alone_changes_nothing_when_the_key_is_absent():
    cfg = {"nozzle_diameter": ["0.4"] * 4}
    changes: list = []
    orca_import._drop_foreign_nozzle_volume_type(cfg, changes)
    assert changes == [] and cfg == {"nozzle_diameter": ["0.4"] * 4}
