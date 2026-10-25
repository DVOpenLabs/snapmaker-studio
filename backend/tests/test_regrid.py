"""Per-plate re-grid, prime-tower placement and support intent, through the real producer
(``convert_to_u1``) on projects built at test time from the committed Orca-authored base."""
from __future__ import annotations

import pytest

from snapstudio_core import regrid
from snapstudio_core.convert import convert_to_u1
from tests import regrid_fixtures as rf

MODES = ["preserve", "recommended"]


def run(tmp_path, src, mode):
    return convert_to_u1(src, out_dir=str(tmp_path / f"out_{mode}"), prepare_mode=mode)


def tokens(path):
    return [i["transform"].split() for i in rf.items_of(path)]


# --- Orca's grid rule ----------------------------------------------------------------------------

def test_column_count_matches_orcas_rule():
    assert [regrid.column_count(n) for n in (1, 2, 3, 4, 5, 6, 7, 9, 10)] == [1, 2, 2, 2, 3, 3, 3, 3, 4]


def test_origin_goes_right_then_down_with_negative_y():
    stride = (324.0, 324.0)
    assert regrid.origin(0, 3, stride) == (0, 0)
    assert regrid.origin(2, 3, stride) == (648.0, 0)
    assert regrid.origin(3, 3, stride) == (0, -324.0)


# --- the plate grid ------------------------------------------------------------------------------

@pytest.mark.parametrize("mode", MODES)
def test_a_larger_bed_stride_is_regridded_per_plate_in_both_modes(tmp_path, mode):
    src = rf.project(tmp_path, plates=2, bed=(330.0, 320.0))
    before = tokens(src)
    result = run(tmp_path, src, mode)
    after = tokens(result.output_path)
    # plate 1 is where it was; plate 2 moved from 396 + 165 to 324 + 165 (the U1 stride)
    assert after[0] == before[0] and after[1][9] == "489" and after[1][10] == "160"
    layout = result.settings_summary["layout"]
    assert layout["status"] == "regridded" and layout["formula_check"] == {"items": 2, "matched": 2, "mismatches": []}
    assert layout["stride_source"] == [396.0, 384.0] and layout["stride_target"] == [324.0, 324.0]
    assert any("Repositioned plate 2 objects to the U1 plate layout" in line
               for line in result.settings_summary["placement_changes"])
    assert result.validated_ok


@pytest.mark.parametrize("mode", MODES)
def test_rotation_and_scale_tokens_survive_verbatim(tmp_path, mode):
    rot = "0.7071067812 0.7071067812 0 -0.7071067812 0.7071067812 0 0 0 1.5"
    ox, oy = rf.source_origin(1, 2, (330.0, 320.0))
    src = rf.project(tmp_path, plates=2, transforms={1: f"{rot} {ox + 165:g} {oy + 160:g} 10"})
    result = run(tmp_path, src, mode)
    after = tokens(result.output_path)[1]
    assert " ".join(after[:9]) == rot and after[11] == "10"           # basis and Z, byte for byte
    assert after[9] == "489" and after[10] == "160"


@pytest.mark.parametrize("mode", MODES)
def test_five_plates_use_negative_y_rows(tmp_path, mode):
    src = rf.project(tmp_path, plates=5, bed=(330.0, 320.0))
    result = run(tmp_path, src, mode)
    after = tokens(result.output_path)
    layout = result.settings_summary["layout"]
    assert layout["cols"] == 3 and layout["status"] == "regridded"
    # plate 4 (index 3): row 1, col 0 -> y = -324 + 160 on the U1 grid (it was -384 + 160)
    assert (after[3][9], after[3][10]) == ("165", "-164")
    # plate 3 (index 2): col 2 -> x = 648 + 165
    assert (after[2][9], after[2][10]) == ("813", "160")


@pytest.mark.parametrize("mode", MODES)
def test_an_item_outside_its_recorded_cell_is_never_guessed(tmp_path, mode):
    # item 2 is recorded on plate 2 but sits where plate 1's cell is: the formula does not hold
    src = rf.project(tmp_path, plates=2, transforms={1: f"{rf.IDENT} 165 160 10"})
    before = tokens(src)
    result = run(tmp_path, src, mode)
    assert tokens(result.output_path) == before                                   # nothing moved
    layout = result.settings_summary["layout"]
    assert layout["status"] == "unresolved" and layout["formula_check"]["mismatches"]
    assert any("Plate positions were left" in w for w in result.settings_summary["warnings"])


@pytest.mark.parametrize("mode", MODES)
def test_the_same_grid_is_left_alone(tmp_path, mode):
    src = rf.project(tmp_path, plates=2, bed=(270.0, 270.0), local=(135.5, 136.0))
    before = tokens(src)
    result = run(tmp_path, src, mode)
    assert tokens(result.output_path) == before
    assert result.settings_summary["layout"]["status"] == "same_grid"


@pytest.mark.parametrize("mode", MODES)
def test_a_plate_that_needs_a_nudge_gets_the_minimal_fit(tmp_path, mode):
    # local y 290 on a 320 bed is outside the U1's 271 limit: plate 2 is nudged, plate 1 is not
    ox, oy = rf.source_origin(1, 2, (330.0, 320.0))
    src = rf.project(tmp_path, plates=2, transforms={1: f"{rf.IDENT} {ox + 165:g} {oy + 290:g} 10"})
    result = run(tmp_path, src, mode)
    after = tokens(result.output_path)
    plate = result.settings_summary["layout"]["plates"][1]
    assert plate["fits_u1_plate"] is True and plate["fit_shift"][1] < 0
    assert float(after[1][10]) <= 271 - 10 - 0.5 + 1e-6 and after[1][9] == "489"
    # the disclosure names the fit adjustment instead of saying positions are unchanged
    line = [d for d in result.settings_summary["placement_changes"] if d.startswith("Repositioned plate 2")][0]
    assert "fit adjustment" in line and "relative to each other" in line and "inside the plate" not in line.split("fit adjustment")[0]


@pytest.mark.parametrize("mode", MODES)
def test_the_original_is_never_modified(tmp_path, mode):
    import hashlib
    src = rf.project(tmp_path, plates=2)
    before = hashlib.sha256(open(src, "rb").read()).hexdigest()
    run(tmp_path, src, mode)
    assert hashlib.sha256(open(src, "rb").read()).hexdigest() == before


# --- the prime tower: assessed, never moved, never called safe --------------------------------------

def tower_values(path):
    cfg = rf.settings_of(path)
    return cfg["wipe_tower_x"], cfg["wipe_tower_y"]


def tower_records(result):
    return result.settings_summary["layout"]["tower"]


@pytest.mark.parametrize("mode", MODES)
def test_an_outside_tower_is_proven_and_reported_but_never_moved(tmp_path, mode):
    cfg = {"wipe_tower_x": ["236.895", "165"], "wipe_tower_y": ["233.729", "250"], "prime_tower_width": "60"}
    src = rf.project(tmp_path, plates=2, cfg=cfg)
    result = run(tmp_path, src, mode)
    records = tower_records(result)
    if mode == "preserve":
        # the creator's own values come through byte for byte: Studio did not move them
        assert tower_values(result.output_path) == (["236.895", "165"], ["233.729", "250"])
        # plate 1: x 236.9 + 60 + brim leaves the 270.5 edge, which the file proves; plate 2's depth is unknown
        assert [r["status"] for r in records] == ["outside_proven", "unknown"]
    assert all(r["status"] != "inside" and r["status"] != "safe" for r in records)
    assert any("prime tower is outside" in w for w in result.settings_summary["warnings"]) == (mode == "preserve")


@pytest.mark.parametrize("mode", MODES)
def test_a_tower_that_looks_fine_is_unknown_not_safe(tmp_path, mode):
    src = rf.project(tmp_path, plates=2, bed=(270.0, 270.0), local=(135.5, 136.0),
                     cfg={"wipe_tower_x": ["39.25", "39.25"], "wipe_tower_y": ["212.1", "212.1"],
                          "prime_tower_width": "30"})
    result = run(tmp_path, src, mode)
    records = tower_records(result)
    assert [r["status"] for r in records] == ["unknown", "unknown"]
    assert records[0]["estimate"]["rect"] is not None and "depth" in records[0]["estimate"]["note"]
    assert "tower_note" in result.settings_summary["layout"]
    if mode == "preserve":
        assert tower_values(result.output_path) == (["39.25", "39.25"], ["212.1", "212.1"])   # byte-identical


def test_a_tower_whose_corner_is_inside_an_object_is_an_overlap_possible(tmp_path):
    src = rf.project(tmp_path, plates=1, bed=(270.0, 270.0), local=(165.0, 160.0),
                     cfg={"wipe_tower_x": ["165"], "wipe_tower_y": ["160"], "prime_tower_width": "30"})
    result = run(tmp_path, src, "preserve")
    assert tower_records(result)[0]["status"] == "overlap_possible"
    assert tower_values(result.output_path) == (["165"], ["160"])


def test_every_tower_record_carries_the_known_extent_and_the_estimate_with_clearances(tmp_path):
    src = rf.project(tmp_path, plates=1, bed=(270.0, 270.0), local=(135.5, 136.0),
                     cfg={"wipe_tower_x": ["39.25"], "wipe_tower_y": ["212.1"], "prime_tower_width": "30"})
    record = tower_records(run(tmp_path, src, "preserve"))[0]
    assert record["known_x_extent"] == [34.25, 74.25] and record["known_y_min"] == 207.1
    est = record["estimate"]
    assert est["rect"] == [34.25, 207.1, 74.25, 247.1]
    assert est["clearance_to_edges"] == {"left": 33.75, "right": 196.25, "front": 206.1, "back": 23.9}
    assert est["clearance_to_objects"] is not None and est["clearance_to_objects"] > 0


@pytest.mark.parametrize("mode", MODES)
def test_towers_are_never_written(tmp_path, mode):
    src = rf.project(tmp_path, plates=2, cfg={"wipe_tower_x": ["236.895", "165"],
                                                "wipe_tower_y": ["233.729", "250"]})
    before = rf.settings_of(src)
    after = rf.settings_of(run(tmp_path, src, mode).output_path)
    if mode == "preserve":
        assert (after["wipe_tower_x"], after["wipe_tower_y"]) == (before["wipe_tower_x"], before["wipe_tower_y"])


def test_a_disabled_tower_is_not_assessed(tmp_path):
    src = rf.project(tmp_path, plates=1, bed=(270.0, 270.0), local=(135.5, 136.0),
                     cfg={"enable_prime_tower": "0", "wipe_tower_x": ["900"], "wipe_tower_y": ["900"]})
    result = run(tmp_path, src, "preserve")
    assert tower_records(result) == []
    assert tower_values(result.output_path) == (["900"], ["900"])


# --- support intent: explicit disable > positive intent > starter reset > creator values -------------

SUPPORT = ("enable_support", "support_type", "support_filament", "support_interface_filament")


def declared_first(path):
    return set(filter(None, rf.settings_of(path)["different_settings_to_system"][0].split(";")))


def support_case(tmp_path, supports, cfg=None, mode="recommended"):
    src = rf.project(tmp_path, plates=1, bed=(270.0, 270.0), local=(135.5, 136.0), supports=supports, cfg=cfg)
    result = run(tmp_path, src, mode)
    return result, result.settings_summary.get("support_intent"), declared_first(result.output_path)


@pytest.mark.parametrize("supports", ["paint", "enforcer", "object"])
def test_positive_intent_survives_the_starter_settings(tmp_path, supports):
    result, intent, declared = support_case(tmp_path, supports)
    cfg = rf.settings_of(result.output_path)
    assert intent["decision"] == "kept" and set(SUPPORT) <= declared
    assert (cfg["enable_support"], cfg["support_type"], cfg["support_filament"]) == ("1", "tree(manual)", "2")
    assert "kept as the creator set them" in intent["statement"]


@pytest.mark.parametrize("supports", ["blocker", "paint_blocker", {"blocker", "paint_blocker"}])
def test_blocker_only_data_is_not_a_request_for_supports(tmp_path, supports):
    result, intent, declared = support_case(tmp_path, supports)
    assert intent["decision"] == "starter_reset" and not (set(SUPPORT) & declared)
    assert intent["blocker_evidence"] and "do not turn supports on" in intent["statement"]


def test_enforcers_with_an_explicit_object_disable_stay_disabled_and_say_so(tmp_path):
    result, intent, declared = support_case(tmp_path, {"enforcer", "object_off"})
    assert intent["decision"] == "disabled" and not (set(SUPPORT) & declared)
    assert "Supports stay off" in intent["statement"] and "support-enforcer volumes" in intent["statement"]


@pytest.mark.parametrize("enable, decision", [("0", "disabled"), ("1", "kept")])
def test_painted_supports_with_global_enable_support_zero_or_one(tmp_path, enable, decision):
    result, intent, declared = support_case(tmp_path, "paint", cfg={"enable_support": enable})
    assert intent["decision"] == decision
    assert bool(set(SUPPORT) & declared) == (decision == "kept")
    assert rf.settings_of(result.output_path)["enable_support"] == enable           # the value is the creator's


def test_global_off_with_an_object_switched_on_is_reported_per_object_not_off(tmp_path):
    result, intent, declared = support_case(tmp_path, "object", cfg={"enable_support": "0"})
    assert intent["decision"] == "per_object" and not (set(SUPPORT) & declared)
    assert "set per object" in intent["statement"] and "Supports stay off" not in intent["statement"]


def test_painted_enforcers_without_a_global_enable_support_key_are_not_called_kept(tmp_path):
    src = rf.project(tmp_path, name="nokey.3mf", plates=1, bed=(270.0, 270.0), local=(135.5, 136.0),
                     supports="paint", cfg={"enable_support": None})
    result = run(tmp_path, src, "recommended")
    intent = result.settings_summary.get("support_intent")
    assert intent is None or intent["decision"] != "kept"


def test_with_no_support_data_the_starter_reset_stands(tmp_path):
    result, intent, declared = support_case(tmp_path, None)
    assert intent["decision"] == "starter_reset" and not (set(SUPPORT) & declared)
    assert "starter settings" in intent["statement"]


@pytest.mark.parametrize("supports", ["paint", "enforcer", {"enforcer", "object_off"}])
def test_preserve_is_unchanged_whatever_the_intent(tmp_path, supports):
    src = rf.project(tmp_path, plates=1, bed=(270.0, 270.0), local=(135.5, 136.0), supports=supports)
    result = run(tmp_path, src, "preserve")
    # the creator's own declaration comes through as it was; Studio adds none and removes none of the four
    assert set(SUPPORT) <= declared_first(result.output_path)
    assert result.settings_summary.get("support_intent") is None


# --- the audit accounts for it -------------------------------------------------------------------

@pytest.mark.parametrize("mode", MODES)
def test_the_fidelity_audit_does_not_call_a_regrid_a_bug(tmp_path, mode):
    from snapstudio_core import fidelity
    src = rf.project(tmp_path, plates=2)
    result = run(tmp_path, src, mode)
    report = fidelity.audit(src, result.output_path)
    text = str(report)
    assert "report this as a bug" not in text


def test_the_audit_makes_no_one_plate_outside_claim_about_a_multi_plate_copy(tmp_path):
    from snapstudio_core import fidelity
    src = rf.project(tmp_path, plates=2)
    result = run(tmp_path, src, "preserve")
    report = fidelity.audit(src, result.output_path)
    assert report["placement"] is None                      # not "plate 2 is 228 mm outside"
    row = next(r for r in report["rows"] if r["element"] == "Model geometry and object placement")
    assert row["status"] == "changed" and "translation only" in row["reason"]
    assert report["claims"]["geometry_unchanged"] is True


# --- already-U1 projects and preservation ----------------------------------------------------------

U1_POLYGON = ["0.5x1", "270.5x1", "270.5x271", "0.5x271"]


@pytest.mark.parametrize("mode", MODES)
def test_an_already_u1_multi_plate_project_comes_out_placement_identical(tmp_path, mode):
    # the creator's own Orca-made U1 project: plates on the U1 stride (324), tower where Orca put it
    src = rf.project(tmp_path, plates=2, bed=(270.0, 270.0), local=(135.5, 136.0), cfg={
        "printable_area": U1_POLYGON, "wipe_tower_x": ["39.25", "37.6"], "wipe_tower_y": ["212.1", "207.2"],
        "prime_tower_width": "30"})
    result = run(tmp_path, src, mode)
    assert [i["tag"] for i in rf.items_of(result.output_path)] == [i["tag"] for i in rf.items_of(src)]
    cfg = rf.settings_of(result.output_path)
    assert (cfg["wipe_tower_x"], cfg["wipe_tower_y"]) == (["39.25", "37.6"], ["212.1", "207.2"])
    assert result.settings_summary["layout"]["status"] == "same_grid"
    assert not result.settings_summary["placement_changes"]


@pytest.mark.parametrize("mode", MODES)
def test_painting_helper_relationships_and_object_files_are_untouched(tmp_path, mode):
    src = rf.project(tmp_path, plates=2, supports={"paint", "enforcer"})
    result = run(tmp_path, src, mode)
    a, b = rf.read(src), rf.read(result.output_path)
    for name in (n for n in a if n.startswith("3D/Objects/")):
        assert a[name] == b[name]                                       # meshes, paint_color, paint_supports
        for token in (b"paint_color", b"paint_supports"):
            assert a[name].count(token) == b[name].count(token) > 0 or a[name].count(token) == 0
    import re as _re
    parts = lambda blob: _re.findall(rb'<part id="[^"]+" subtype="[^"]*"', blob["Metadata/model_settings.config"])
    assert parts(a) == parts(b)                                         # helper-volume relationships
    components = lambda blob: blob["3D/3dmodel.model"].count(b"<component ")
    assert components(a) == components(b)
