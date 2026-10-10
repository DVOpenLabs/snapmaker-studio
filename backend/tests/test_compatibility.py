"""Compatibility Doctor — read-only diagnostics tests.

Synthetic 3MFs only (no paid/commercial model names or files). A conditional
real-fixture test runs when SNAPSTUDIO_REAL_MULTICOLOR_FIXTURE is set.
"""
import hashlib
import json
import os
import zipfile

import pytest

from snapstudio_core import compatibility as cc

SETTINGS = "Metadata/project_settings.config"

_VALID = {
    "printer_model": "Snapmaker U1",
    "printer_settings_id": "Snapmaker U1 (0.4 nozzle)",
    "prime_tower_brim_width": "2",
    "raft_first_layer_expansion": "0",
    "tree_support_wall_count": "1",
    "solid_infill_filament": "1",
    "sparse_infill_filament": "1",
    "wall_filament": "1",
    "use_relative_e_distances": "0",
    "layer_change_gcode": "",
}


def _make(path, cfg: dict):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(SETTINGS, json.dumps(cfg))


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _ids(res):
    return {f["id"] for f in res["findings"]}


def test_bad_values_flagged_with_severity_and_range(tmp_path):
    cfg = dict(_VALID)
    cfg.update({
        "prime_tower_brim_width": "-1",
        "tree_support_wall_count": "-1",
        "solid_infill_filament": "0",
        "wall_filament": "0",
    })
    p = str(tmp_path / "bad.3mf"); _make(p, cfg)
    res = cc.check(p)
    ids = _ids(res)
    assert "value.prime_tower_brim_width" in ids
    assert "value.tree_support_wall_count" in ids
    assert "value.solid_infill_filament" in ids
    assert "value.wall_filament" in ids
    for f in res["findings"]:
        if f["id"].startswith("value."):
            assert f["severity"] == "error"
            assert "range" in f["evidence"]


def test_valid_u1_project_is_clean(tmp_path):
    p = str(tmp_path / "good.3mf"); _make(p, _VALID)
    res = cc.check(p)
    # The fixture has no countable objects, so object spacing stays "not verified"
    # (unknown is never treated as a single object); nothing else is flagged.
    assert [f["id"] for f in res["findings"]] == ["layout.object_spacing"]
    assert not [f for f in res["findings"] if f["severity"] == "error"]


def test_relative_e_without_reset_flagged(tmp_path):
    cfg = dict(_VALID); cfg["use_relative_e_distances"] = "1"; cfg["layer_change_gcode"] = "; layer"
    p = str(tmp_path / "rel.3mf"); _make(p, cfg)
    res = cc.check(p)
    f = next(f for f in res["findings"] if f["id"] == "extrusion.relative_no_reset")
    assert f["severity"] == "warning"


def test_relative_e_with_reset_is_clean(tmp_path):
    cfg = dict(_VALID); cfg["use_relative_e_distances"] = "1"; cfg["layer_change_gcode"] = "G92 E0\n; layer"
    p = str(tmp_path / "rel_ok.3mf"); _make(p, cfg)
    res = cc.check(p)
    assert "extrusion.relative_no_reset" not in _ids(res)


def test_non_u1_profile_flagged(tmp_path):
    cfg = dict(_VALID); cfg["printer_model"] = "Bambu Lab X1 Carbon"; cfg["printer_settings_id"] = "0.20mm Standard @BBL X1C"
    p = str(tmp_path / "foreign.3mf"); _make(p, cfg)
    res = cc.check(p)
    f = next(f for f in res["findings"] if f["id"] == "profile.not_u1")
    assert f["severity"] == "warning"


def test_source_bytes_unchanged(tmp_path):
    cfg = dict(_VALID); cfg["wall_filament"] = "0"
    p = str(tmp_path / "x.3mf"); _make(p, cfg)
    before = _sha(p)
    cc.check(p)
    assert _sha(p) == before


def test_bare_model_without_settings(tmp_path):
    p = str(tmp_path / "bare.3mf")
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("3D/3dmodel.model", "<model/>")
    res = cc.check(p)
    assert res["findings"] == []
    assert "bare model" in res["summary"]


@pytest.mark.skipif(not os.environ.get("SNAPSTUDIO_REAL_MULTICOLOR_FIXTURE"),
                    reason="real multicolor fixture not available")
def test_real_fixture_no_false_positives():
    real = os.environ["SNAPSTUDIO_REAL_MULTICOLOR_FIXTURE"]
    res = cc.check(real)
    # A known-good real U1 project should not raise invalid-value errors.
    assert not [f for f in res["findings"] if f["severity"] == "error"]
