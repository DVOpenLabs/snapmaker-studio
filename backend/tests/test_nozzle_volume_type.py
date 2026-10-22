"""A prepared copy must not carry Bambu's `nozzle_volume_type` (issue 39).

Genuine Snapmaker-authored U1 projects have no such key. A Bambu-authored project carries it beside the
U1's four nozzles, and a reporter's copy showed a 'newer version, values replaced' notice naming it. That
notice is not confirmed in Snapmaker Orca, so these tests pin what Studio writes, not what Orca does.
"""
from __future__ import annotations

import json
import shutil
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
    assert rows[0]["reason"] == "left out: Snapmaker Orca does not write this setting"
    assert "not been confirmed in Snapmaker Orca" in rows[0]["explanation"]
    wording = (rows[0]["reason"] + " " + rows[0]["explanation"]).lower()
    assert "bambu-only" not in wording and "original printer" not in wording and "no meaning" not in wording


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


ORCASLICER = FIXTURES / "orcaslicer-2.4.2-painted-cube.3mf"


def _with_settings(src: Path, dst: Path, **changes) -> Path:
    """A copy of a fixture whose project settings state `changes`; every other part is carried byte for byte."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == SETTINGS:
                data = json.dumps({**json.loads(data), **changes}).encode()
            zout.writestr(info, data)
    return dst


@pytest.mark.parametrize("mode", ["preserve", "recommended"])
def test_a_declaration_of_the_key_is_withdrawn_in_both_modes(tmp_path, mode):
    src = _with_settings(BAMBU, tmp_path / "declared.3mf", different_settings_to_system=[
        "layer_height;nozzle_volume_type", "nozzle_volume_type", "", "nozzle_volume_type;filament_flow_ratio", ""])
    cfg = _settings(_prepare(src, tmp_path / "out", mode).output_path)
    assert "nozzle_volume_type" not in cfg
    assert not any("nozzle_volume_type" in str(e) for e in cfg.get("different_settings_to_system") or [])
    if mode == "preserve":          # a deviation the project made and Studio did not touch is still declared
        entries = [str(e) for e in cfg["different_settings_to_system"]]
        assert "layer_height" in entries[0] and "filament_flow_ratio" in entries[3]


def test_preserve_and_recommended_agree_on_the_key_and_its_declaration(tmp_path):
    src = _with_settings(BAMBU, tmp_path / "declared.3mf", different_settings_to_system=["nozzle_volume_type", "", "", "", ""])
    a = _settings(_prepare(src, tmp_path / "a", "preserve").output_path)
    b = _settings(_prepare(src, tmp_path / "b", "recommended").output_path)
    for cfg in (a, b):
        assert "nozzle_volume_type" not in cfg
        assert all("nozzle_volume_type" not in str(e) for e in cfg["different_settings_to_system"])


def test_the_withdrawal_is_an_accounted_change():
    cfg = {"nozzle_volume_type": ["Standard"], "different_settings_to_system": ["nozzle_volume_type", "", ""]}
    changes = orca_import.apply_compatibility(cfg)
    assert {c["key"] for c in changes} >= {"nozzle_volume_type", "different_settings_to_system"}
    assert all(c["reason"] and c["explanation"] for c in changes)
    assert cfg["different_settings_to_system"] == ["", "", ""]


def test_the_preserve_summary_does_not_offer_the_applied_removal_as_optional(tmp_path):
    summary = _prepare(BAMBU, tmp_path, "preserve").settings_summary
    assert [r for r in summary["recommended_changes"] if r["key"] == "nozzle_volume_type"] == []
    assert summary["recommended_changes"], "other recommended changes are still offered"


@pytest.mark.parametrize("mode", ["preserve", "recommended"])
def test_an_orcaslicer_authored_u1_file_loses_the_key_with_an_honest_reason(tmp_path, mode):
    assert _settings(ORCASLICER)["nozzle_volume_type"] == ["Standard"]       # not Bambu-only: it names a U1
    with_rule = _settings(_prepare(ORCASLICER, tmp_path / "a", mode).output_path)
    assert "nozzle_volume_type" not in with_rule
    result = _prepare(ORCASLICER, tmp_path / "c", mode)
    rows = [r for g in ("compat_changed", "mapped_to_u1") for r in result.settings_summary[g] if r["key"] == "nozzle_volume_type"]
    assert len(rows) == 1 and "Snapmaker Orca does not write" in rows[0]["reason"]
    assert "Bambu" not in rows[0]["reason"] and "original printer" not in rows[0]["reason"]


def test_orcaslicer_other_keys_are_unchanged_by_the_rule(tmp_path, monkeypatch):
    a = _settings(_prepare(ORCASLICER, tmp_path / "a", "preserve").output_path)
    monkeypatch.setattr(orca_import, "_drop_foreign_nozzle_volume_type", lambda cfg, changes: None)
    b = _settings(_prepare(ORCASLICER, tmp_path / "b", "preserve").output_path)
    assert {k for k in set(a) | set(b) if a.get(k, "<absent>") != b.get(k, "<absent>")} == {"nozzle_volume_type"}


def test_snapmaker_orca_2_3_6_fixtures_do_not_carry_the_key():
    found = sorted(FIXTURES.parent.rglob("*.3mf"))
    assert found
    for path in found:
        with zipfile.ZipFile(path) as z:
            if SETTINGS in z.namelist() and "nozzle_volume_type" not in json.loads(z.read(SETTINGS)):
                continue
        # every file that has it is from Bambu Studio or OrcaSlicer, never Snapmaker Orca
        assert "snapmaker-orca" not in path.name, path.name


def test_the_fidelity_row_says_snapmaker_orca_does_not_write_it(tmp_path):
    from snapstudio_core import fidelity
    out = _prepare(BAMBU, tmp_path, "preserve").output_path
    report = fidelity.audit(str(BAMBU), out)
    rows = [r for r in report["rows"] if r["element"] in ("Print settings not carried over", "Print settings Snapmaker Orca does not write")]
    mine = [r for r in rows if "nozzle_volume_type" in r["detail"]]
    assert len(mine) == 1 and mine[0]["element"] == "Print settings Snapmaker Orca does not write"
    assert "original printer" not in mine[0]["reason"] and "no meaning" not in mine[0]["reason"]


def test_the_prepare_ledger_records_the_removal(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    from snapstudio_api import service
    src = tmp_path / "in.3mf"
    shutil.copy(BAMBU, src)
    service.convert(str(src), out_dir=str(tmp_path / "out"))
    entry = service.fix_history(source=str(src))["entries"][0]
    rows = [c for c in entry["changes"] + [{"key": f["title"], "reason": f["detail"]} for f in entry["findings"]] if c.get("key") == "nozzle_volume_type"]
    assert rows and "Snapmaker Orca does not write" in rows[0]["reason"]


def test_the_fidelity_claims_change_honestly_for_a_file_that_carried_the_key(tmp_path):
    """The card's headline moves from 'Everything Studio can identify...' to 'Every change and everything not carried
    over is listed below' for such a file: something was left out, and it is listed with its reason."""
    from snapstudio_core import fidelity
    out = _prepare(BAMBU, tmp_path, "preserve").output_path
    claims = fidelity.audit(str(BAMBU), out)["claims"]
    assert claims["fully_accounted"] is True and claims["nothing_removed"] is False and claims["may_claim_nothing_lost"] is False


def _declarations(cfg) -> list[str]:
    dss = cfg.get("different_settings_to_system")
    return [str(e) for e in (dss if isinstance(dss, list) else [dss or ""])]


@pytest.mark.parametrize("mode", ["preserve", "recommended"])
@pytest.mark.parametrize("declared", [
    None,                                                                         # the source never declared it
    ["nozzle_volume_type", "", "", "", ""],                                       # a list
    ["layer_height;nozzle_volume_type", "nozzle_volume_type", "", "", ""],
    "nozzle_volume_type;layer_height",                                            # a scalar string
])
def test_real_convert_leaves_no_declaration_of_the_key(tmp_path, mode, declared):
    extra = {} if declared is None else {"different_settings_to_system": declared}
    src = _with_settings(BAMBU, tmp_path / "s.3mf", **extra)
    cfg = _settings(_prepare(src, tmp_path / "out", mode).output_path)
    assert "nozzle_volume_type" not in cfg
    assert not any("nozzle_volume_type" in e for e in _declarations(cfg)), cfg.get("different_settings_to_system")


@pytest.mark.parametrize("extra", [
    {}, {"exclude_object": "0", "brim_type": "auto_brim"},
    {"different_settings_to_system": ["nozzle_volume_type", "", "", "", ""]},
])
def test_optional_recommendations_never_repeat_what_the_preserve_copy_already_has(tmp_path, extra):
    src = _with_settings(BAMBU, tmp_path / "s.3mf", **extra)
    preserve = _prepare(src, tmp_path / "a", "preserve")
    applied = _settings(preserve.output_path)
    recommended = _settings(_prepare(src, tmp_path / "b", "recommended").output_path)
    offered = {r["key"] for r in preserve.settings_summary["recommended_changes"]}
    differing = {k for k in set(applied) | set(recommended) if applied.get(k, "<absent>") != recommended.get(k, "<absent>")}
    assert offered <= differing, offered - differing          # nothing already applied is offered again
    assert offered, "the genuinely different recommendations are still offered"
    for key in ("exclude_object", "brim_type", "nozzle_volume_type"):
        if key in extra or key == "nozzle_volume_type":
            assert key not in offered, key


@pytest.mark.parametrize("mode", ["preserve", "recommended"])
@pytest.mark.parametrize("declared", ["nozzle_volume_type;layer_height", ["nozzle_volume_type", "", "", "", "", "", ""]])
def test_a_stale_declaration_of_a_key_the_source_lacks_is_withdrawn(tmp_path, mode, declared):
    src = _with_settings(SNAPMAKER, tmp_path / "s.3mf", different_settings_to_system=declared)
    assert "nozzle_volume_type" not in _settings(src)
    cfg = _settings(_prepare(src, tmp_path / "out", mode).output_path)
    assert "nozzle_volume_type" not in cfg
    assert not any("nozzle_volume_type" in e for e in _declarations(cfg))


@pytest.mark.parametrize("src", [BAMBU, SNAPMAKER, ORCASLICER])
def test_the_preview_is_exactly_what_recommended_changes_in_the_preserve_copy(tmp_path, src):
    preserve = _prepare(src, tmp_path / "a", "preserve")
    applied = _settings(preserve.output_path)
    full = _settings(_prepare(src, tmp_path / "b", "recommended").output_path)
    from snapstudio_core.preserve import config_diff, display_value
    preview = preserve.settings_summary["recommended_changes"]
    assert {r["key"] for r in preview} == {d["key"] for d in config_diff(applied, full)}
    assert all(r["old"] == display_value(applied.get(r["key"]), key=r["key"]) for r in preview)


def test_the_late_guard_alone_withdraws_a_declaration_with_no_value():
    cfg = {"different_settings_to_system": ["nozzle_volume_type;layer_height", "nozzle_volume_type", ""]}
    changes = orca_import.withdraw_nozzle_volume_type_declaration(cfg)
    assert cfg["different_settings_to_system"] == ["layer_height", "", ""]
    assert [c["key"] for c in changes] == ["different_settings_to_system"]
    assert "declared nozzle_volume_type" in changes[0]["explanation"]          # true: it was declared


def test_the_late_guard_leaves_a_project_without_the_declaration_alone():
    cfg = {"different_settings_to_system": ["layer_height", "", ""]}
    assert orca_import.withdraw_nozzle_volume_type_declaration(cfg) == []
    assert cfg["different_settings_to_system"] == ["layer_height", "", ""]


def test_the_late_guard_does_nothing_while_the_key_is_still_in_the_project():
    cfg = {"nozzle_volume_type": ["Standard"], "different_settings_to_system": ["nozzle_volume_type"]}
    assert orca_import.withdraw_nozzle_volume_type_declaration(cfg) == []
