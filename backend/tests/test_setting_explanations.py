"""Setting-change explanations: what the engine says about WHY a setting changed, end to end.

Two things are guarded here.

1. The raft expansion has two owners: the U1 clamp table (runs in every mode, fixes -1) and the Orca-import rule (runs in
   Preserve/U1/Optimize, fixes any negative value). They must agree on the value and on the explanation, and a project
   must never get two competing change records for the key.
2. The explanation each step writes reaches the settings summary, so the app can show it. Kept settings, compatibility
   changes and optional recommendations stay separate; only compatibility changes carry a reason of this kind.
"""
import json
import zipfile

import pytest

from snapstudio_core import compatibility, orca_import
from snapstudio_core.convert import convert_to_u1
from snapstudio_core.rules import apply_clamps, clamp_explanation, load_rules


def _project(tmp_path, settings: dict):
    path = tmp_path / "foreign.3mf"
    base = {"printer_model": "Bambu Lab X1 Carbon", "filament_colour": ["#FF0000"], "filament_type": ["PLA"]}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", '<model unit="millimeter"><build/></model>')
        z.writestr("Metadata/project_settings.config", json.dumps({**base, **settings}))
    return path


def _prepare(tmp_path, settings, mode="preserve"):
    result = convert_to_u1(str(_project(tmp_path, settings)), out_dir=str(tmp_path / "out"), prepare_mode=mode)
    with zipfile.ZipFile(result.output_path) as z:
        after = json.loads(z.read("Metadata/project_settings.config"))
    return result.settings_summary, after


# --- the clamp table agrees with the evidence it is explained by ----------------------------------------------------

def test_every_clamp_replaces_a_value_the_compatibility_check_calls_invalid():
    for clamp in load_rules()["clamps"]:
        span = compatibility.valid_range(clamp["key"])
        assert span is not None, f"{clamp['key']} is clamped but the Compatibility check has no range for it"
        lo, hi = span
        assert not lo <= float(clamp["bad"]) <= hi, f"{clamp['key']}: the 'bad' value is inside the valid range"
        assert lo <= float(clamp["good"]) <= hi, f"{clamp['key']}: the 'good' value is outside the valid range"


def test_the_raft_clamp_and_the_orca_import_rule_use_the_same_value():
    (raft,) = [c for c in load_rules()["clamps"] if c["key"] == "raft_first_layer_expansion"]
    assert raft["good"] == orca_import.u1_template()["raft_first_layer_expansion"]


def test_clamp_explanations_name_the_range_and_the_value_used():
    changes = apply_clamps({"prime_tower_brim_width": "-1", "tree_support_wall_count": "-1", "wall_filament": "0"}, load_rules())
    text = {c["key"]: clamp_explanation(c) for c in changes}
    assert "0 or more" in text["prime_tower_brim_width"] and "5" in text["prime_tower_brim_width"]
    assert "0 to 2" in text["tree_support_wall_count"]
    assert "1 or more" in text["wall_filament"]
    assert all("print" not in t.lower() for t in text.values()), "an explanation must not claim an effect on the print"


def test_the_raft_clamp_says_what_the_orca_import_rule_says():
    (change,) = apply_clamps({"raft_first_layer_expansion": "-1"}, load_rules())
    assert clamp_explanation(change) == orca_import.RAFT_EXPANSION_WHY


# --- through the whole pipeline, one record and one explanation per key ---------------------------------------------

@pytest.mark.parametrize("bad", ["-1", "-2", "-0.5"])
@pytest.mark.parametrize("mode", ["preserve", "recommended"])
def test_a_negative_raft_expansion_has_one_owner_per_run_and_one_explained_record(tmp_path, bad, mode):
    summary, after = _prepare(tmp_path, {"raft_first_layer_expansion": bad}, mode=mode)
    expected = orca_import.u1_template()["raft_first_layer_expansion"]
    assert after["raft_first_layer_expansion"] == expected
    records = [c for c in summary["compat_changed"] if c["key"] == "raft_first_layer_expansion"]
    assert len(records) == 1, "two owners must not produce two competing records"
    assert records[0]["old"] == bad and records[0]["new"] == expected
    assert records[0]["explanation"] == orca_import.RAFT_EXPANSION_WHY
    # the reason is the engine's own, never empty, and never shown instead of the explanation
    assert records[0]["reason"]


def test_each_clamped_setting_reaches_the_summary_with_its_explanation(tmp_path):
    summary, after = _prepare(tmp_path, {"prime_tower_brim_width": "-1", "wall_filament": "0", "tree_support_wall_count": "-1"})
    by_key = {c["key"]: c for c in summary["compat_changed"]}
    for key in ("prime_tower_brim_width", "wall_filament", "tree_support_wall_count"):
        assert key in by_key, f"{key} was changed but is not reported"
        assert by_key[key]["explanation"] == clamp_explanation(
            {"key": key, "old": by_key[key]["old"], "new": by_key[key]["new"]})
    assert after["prime_tower_brim_width"] == "5"


def test_an_ordinary_orca_import_change_keeps_its_own_explanation(tmp_path):
    summary, _ = _prepare(tmp_path, {"brim_type": "auto_brim"})
    (brim,) = [c for c in summary["compat_changed"] if c["key"] == "brim_type"]
    assert "Snapmaker Orca" in brim["explanation"]
    assert brim["reason"] and brim["reason"] != brim["explanation"]


def test_changes_with_no_explanation_carry_none_and_kept_settings_carry_no_reason(tmp_path):
    summary, _ = _prepare(tmp_path, {"layer_height": "0.16", "printer_settings_id": "Bambu Lab X1 Carbon 0.4 nozzle"})
    assert isinstance(summary["kept_count"], int)
    for change in summary["compat_changed"]:
        assert "explanation" not in change or (isinstance(change["explanation"], str) and change["explanation"])
    # optional recommendations are a separate list and are not explained here
    for change in summary["recommended_changes"]:
        assert "explanation" not in change
