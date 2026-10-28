"""Which index each per-slot setting vector is addressed by.

The expected results below are the setting contract (Snapmaker Orca b1831e5: Preset.cpp filament
options vs printer options, PrintConfig.cpp), written out here as literals. They are not produced by
iterating the implementation's key lists, and a vector's length is never evidence of its scope.
Evidence: read from source; not measured in a running Snapmaker Orca; no printer.
"""
import json
from importlib.resources import files

from snapstudio_core import preserve
from tests.integration.setup_helpers import FILAMENT_SCOPE, HEAD_SCOPE


def vec(key, n):
    return [f"{key}-{i}" for i in range(n)]


def test_scope_data_matches_the_source_contract():
    data = json.loads((files("snapstudio_core.data") / "u1_setting_scopes.json").read_text("utf-8"))
    assert set(data["logical_filament"]) == set(FILAMENT_SCOPE)
    assert set(data["physical_head"]) == set(HEAD_SCOPE)
    assert data["source"]["commit"] == "b1831e5dcb464172de33783142425aafda834fbc"
    assert data["source"]["method"].startswith("Read from the committed source files")
    assert not set(FILAMENT_SCOPE) & set(HEAD_SCOPE)


def test_mixed_four_head_eight_filament_settings_are_valid_as_they_are():
    cfg = {**{k: vec(k, 8) for k in FILAMENT_SCOPE}, **{k: vec(k, 4) for k in HEAD_SCOPE}}
    before = {k: list(v) for k, v in cfg.items()}
    changes, warnings = preserve.prepare_preserved_values(cfg, 8, physical_heads=4)
    assert cfg == before and changes == [] and warnings == []


def test_equal_length_is_not_evidence_a_head_vector_with_eight_entries_is_cut_to_the_head_count():
    cfg = {k: vec(k, 8) for k in HEAD_SCOPE}
    changes, warnings = preserve.prepare_preserved_values(cfg, 8, physical_heads=4)
    for k in HEAD_SCOPE:
        assert cfg[k] == [f"{k}-{i}" for i in range(4)]          # first four, in order
    assert len(warnings) == 3 and all("per-physical head" in w for w in warnings)
    assert {c["key"] for c in changes} == set(HEAD_SCOPE)


def test_a_filament_vector_follows_the_project_filament_count_not_the_head_count():
    cfg = {k: vec(k, 4) for k in FILAMENT_SCOPE}                 # 4 entries for an 8-filament project
    changes, warnings = preserve.prepare_preserved_values(cfg, 8, physical_heads=4)
    for k in FILAMENT_SCOPE:
        assert cfg[k] == vec(k, 4) + [f"{k}-3"] * 4              # padded with the last entry, nothing dropped
    assert all("per-project filament" in w for w in warnings) and len(changes) == 4


def test_the_scope_rule_sizes_head_vectors_to_whatever_head_count_it_is_given():
    cfg = {k: vec(k, 6) for k in HEAD_SCOPE}
    changes, _ = preserve.prepare_preserved_values(cfg, 6, physical_heads=6)
    assert changes == [] and all(cfg[k] == vec(k, 6) for k in HEAD_SCOPE)


def test_without_a_setup_every_vector_is_mapped_to_four_as_before():
    cfg = {k: vec(k, 8) for k in FILAMENT_SCOPE + HEAD_SCOPE}
    changes, _ = preserve.prepare_preserved_values(cfg, 8)
    assert all(cfg[k] == vec(k, 8)[:4] for k in FILAMENT_SCOPE + HEAD_SCOPE)
    assert {c["category"] for c in changes} == {"mapped"}


def test_a_key_outside_both_scopes_is_not_touched_by_the_setup_path():
    cfg = {"curr_bed_type": "Textured PEI Plate", "something_else": [1, 2, 3, 4, 5, 6, 7, 8]}
    changes, warnings = preserve.prepare_preserved_values(cfg, 8, physical_heads=4)
    assert cfg["something_else"] == [1, 2, 3, 4, 5, 6, 7, 8] and changes == [] and warnings == []
