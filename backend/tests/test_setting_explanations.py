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
from snapstudio_core.container import ThreeMF
from snapstudio_core.repair import repair
from snapstudio_core.convert import convert_to_u1
from snapstudio_core.rules import apply_clamps, clamp_explanation, load_rules


def _project(tmp_path, settings: dict):
    path = tmp_path / "foreign.3mf"
    array_lengths = [len(value) for value in settings.values() if isinstance(value, list)]
    count = max(array_lengths or [1])
    base = {"printer_model": "Bambu Lab X1 Carbon", "filament_colour": ["#FF0000"] * count, "filament_type": ["PLA"] * count}
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
        # the explanation says Studio used "the U1 default", so that has to be what it used
        assert clamp["good"] == orca_import.u1_template()[clamp["key"]], f"{clamp['key']}: 'good' is not the U1 default"


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
    assert records[0]["reason"] == orca_import.RAFT_EXPANSION_REASON
    # whichever step wrote the surviving explanation also wrote its source and kind: never a mixed pair
    assert records[0]["source"] == "Studio's import rule for this setting"
    assert records[0]["kind"] == "orca"


@pytest.mark.parametrize("mode", ["safe", "preserve", "u1", "optimize"])
def test_the_repair_report_itself_holds_one_raft_record_in_every_mode(tmp_path, mode):
    """The summary dedupes by key, so count in the raw repair report, where two owners would show up as two records."""
    report = repair(ThreeMF.open(_project(tmp_path, {"raft_first_layer_expansion": "-1"})), mode=mode, dry_run=True).report
    records = [item for group in report.values() if isinstance(group, list) for item in group
               if isinstance(item, dict) and item.get("key") == "raft_first_layer_expansion"]
    identity = report.get("identity")
    if isinstance(identity, dict):
        records += [i for i in identity.get("changed", []) if i.get("key") == "raft_first_layer_expansion"]
    assert len(records) == 1, f"{mode}: {len(records)} records for the raft key: {records}"


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
    assert brim["explanation"] == "Studio replaced the automatic brim choice with no brim. A brim you chose yourself is kept."
    assert brim["kind"] == "orca"
    assert brim["source"] == "Studio's import rule for this setting"
    assert brim["kind"] == "orca"
    assert brim["reason"] and brim["reason"] != brim["explanation"]


@pytest.mark.parametrize("settings,key,phrase", [
    ({"adaptive_layer_height": "1", "support_type": "tree", "support_style": "organic"}, "support_style", "Studio replaced the tree support style with the hybrid style for this U1 copy."),
])
def test_orca_verify_advice_names_only_studios_operation(settings, key, phrase, tmp_path):
    summary, _ = _prepare(tmp_path, settings)
    change = next(c for c in summary["compat_changed"] if c["key"] == key)
    assert change["explanation"] == phrase
    assert change["kind"] == "orca"


def test_explanations_are_absent_or_non_empty_and_recommendations_carry_none(tmp_path):
    summary, _ = _prepare(tmp_path, {"layer_height": "0.16", "printer_settings_id": "Bambu Lab X1 Carbon 0.4 nozzle"})
    assert isinstance(summary["kept_count"], int)
    for change in summary["compat_changed"]:
        assert "explanation" not in change or (isinstance(change["explanation"], str) and change["explanation"])
    # optional recommendations are a separate list and are not explained here
    for change in summary["recommended_changes"]:
        assert "explanation" not in change


@pytest.mark.parametrize("key", ["filament_flush_temp", "filament_adaptive_volumetric_speed"])
@pytest.mark.parametrize("value,count,expected,reason", [
    ([220], 1, "Studio wrote each value in this list as text.", "wrote each value in the list as text"),
    ([5, 5, 5, 5], 4, "Studio wrote each value in this list as text.", "wrote each value in the list as text"),
    ([0, 0, 0, 0, 0], 5, "Studio wrote each value in this list as text.", "wrote each value in the list as text"),
    ([" 5 ", 220, "", "7"], 4, "Studio filled an empty entry with the last non-empty value in this list. Studio trimmed whitespace around a string value. Studio wrote each value in this list as text.", "filled an empty entry with the last non-empty value; trimmed whitespace from a string; wrote each value in the list as text"),
    (["", "5"], 2, "Studio filled an empty entry with the last non-empty value in this list.", "filled an empty entry with the last non-empty value"),
    (["1", "2", "3", "4", "5", "6"], 4, "Studio resized this list to cover every filament slot.", "resized the list"),
    ([" 1 ", "2", "3", "4", "5"], 4, "Studio resized this list to cover every filament slot. Studio trimmed whitespace around a string value.", "resized the list; trimmed whitespace from a string"),
])
def test_filament_import_explanation_matches_each_operation(key, value, count, expected, reason):
    from snapstudio_core.orca_import import _fix_filament_array_validity
    changes = []
    cfg = {key: list(value)}
    _fix_filament_array_validity(cfg, changes, count)
    assert changes[0]["explanation"] == expected
    assert changes[0]["kind"] == "engine"
    assert cfg[key] != value
    assert changes[0]["reason"] == reason
    assert all(part in changes[0]["explanation"] for part in expected.split(". ") if part)


@pytest.mark.parametrize("mode", ["preserve", "recommended"])
@pytest.mark.parametrize("key", ["filament_flush_temp", "filament_adaptive_volumetric_speed"])
@pytest.mark.parametrize("value", [[220], [5, 5, 5, 5], [0, 0, 0, 0, 0], [" 5 ", 220, "", "7"]])
def test_filament_array_conversion_passes_real_convert_preservation_invariant(tmp_path, mode, key, value):
    """The real converter records every normalization; this cannot establish prose clarity, source choice, physical behavior, Orca behavior, dates, paraphrased overclaims, or screen-reader behavior."""
    summary, after = _prepare(tmp_path, {key: value}, mode=mode)
    change = next(c for c in summary["compat_changed"] if c["key"] == key)
    assert change["reason"] and change["explanation"]
    assert all(isinstance(item, str) for item in after[key])
    assert after[key] != value


def test_action_reasons_replace_all_four_provenance_fields_as_one_record():
    from snapstudio_core.convert import _action_reasons
    records, _, _, = _action_reasons({"normalizations": [
        {"key": "raft", "reason": "first", "explanation": "old", "source": "old source", "kind": "engine"},
    ], "orca_compatibility": [
        {"key": "raft", "reason": "second", "explanation": "new", "source": "new source", "kind": "engine"},
    ]})
    assert records["raft"] == {"reason": "second", "explanation": "new", "source": "new source", "kind": "engine"}


def test_action_reasons_clear_a_stale_explanation_only_with_an_explicit_clear():
    from snapstudio_core.convert import _action_reasons
    records, _, _, = _action_reasons({"normalizations": [
        {"key": "raft", "reason": "first", "explanation": "old", "source": "old source", "kind": "engine"},
        {"key": "raft", "reason": ""},
    ]})
    assert "raft" not in records


def test_action_reasons_keep_prior_record_when_later_item_has_no_reason():
    from snapstudio_core.convert import _action_reasons
    records, _, _, = _action_reasons({"normalizations": [
        {"key": "raft", "reason": "first", "explanation": "old", "source": "old source", "kind": "engine"},
        {"key": "raft"},
    ]})
    assert records["raft"] == {"reason": "first", "explanation": "old", "source": "old source", "kind": "engine"}
