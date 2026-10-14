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


@pytest.mark.parametrize("mode", MODES)
def test_the_original_is_never_modified(tmp_path, mode):
    import hashlib
    src = rf.project(tmp_path, plates=2)
    before = hashlib.sha256(open(src, "rb").read()).hexdigest()
    run(tmp_path, src, mode)
    assert hashlib.sha256(open(src, "rb").read()).hexdigest() == before


# --- the prime tower -----------------------------------------------------------------------------

def tower(path):
    cfg = rf.settings_of(path)
    return cfg["wipe_tower_x"], cfg["wipe_tower_y"]


def test_a_tower_outside_the_u1_plate_is_moved_inside_in_preserve(tmp_path):
    src = rf.project(tmp_path, plates=2, cfg={
        "wipe_tower_x": ["236.895", "165"], "wipe_tower_y": ["233.729", "250"], "prime_tower_width": "60"})
    result = run(tmp_path, src, "preserve")
    xs, ys = tower(result.output_path)
    assert len(xs) == 2 and len(ys) == 2
    for x, y in zip(xs, ys):
        rect = regrid.tower_rect(float(x), float(y), 60.0, 5.0)
        assert rect[0] >= 0.5 and rect[2] <= 270.5 and rect[1] >= 1 and rect[3] <= 271
    moved = [t for t in result.settings_summary["layout"]["tower"] if t["action"] == "moved"]
    assert [t["plate"] for t in moved] == [1, 2]
    assert rf.settings_of(result.output_path)["prime_tower_width"] == "60"      # the creator's width is kept


def test_a_valid_tower_is_left_exactly_as_the_creator_had_it(tmp_path):
    src = rf.project(tmp_path, plates=2, bed=(270.0, 270.0), local=(135.5, 136.0),
                     cfg={"wipe_tower_x": ["39.25", "39.25"], "wipe_tower_y": ["212.1", "212.1"],
                          "prime_tower_width": "30"})
    result = run(tmp_path, src, "preserve")
    assert tower(result.output_path) == (["39.25", "39.25"], ["212.1", "212.1"])
    assert all(t["action"] == "kept" for t in result.settings_summary["layout"]["tower"])


def test_a_tower_on_top_of_an_object_is_moved_clear_of_it(tmp_path):
    # the object is centred where the creator put the tower (local 165, 160); a 30 mm tower at (155, 150)
    src = rf.project(tmp_path, plates=2, bed=(270.0, 270.0), local=(165.0, 160.0),
                     cfg={"wipe_tower_x": ["155"], "wipe_tower_y": ["150"], "prime_tower_width": "30"})
    result = run(tmp_path, src, "preserve")
    xs, ys = tower(result.output_path)
    layout = result.settings_summary["layout"]
    assert [t["action"] for t in layout["tower"]] == ["moved", "moved"]
    rect = regrid.tower_rect(float(xs[0]), float(ys[0]), 30.0, 5.0)
    obj = (155.0, 150.0, 175.0, 170.0)                      # the cube's footprint in the plate's own frame
    assert rect[2] < obj[0] - 3 or rect[0] > obj[2] + 3 or rect[3] < obj[1] - 3 or rect[1] > obj[3] + 3


def test_recommended_tower_constant_that_overlaps_an_object_is_moved(tmp_path):
    # the profile constant is (165, 200.821); put the object exactly there (cube centre 175, 215)
    src = rf.project(tmp_path, plates=1, bed=(270.0, 270.0), local=(175.0, 215.0))
    result = run(tmp_path, src, "recommended")
    layout = result.settings_summary["layout"]
    assert layout["status"] == "not_multi_plate"
    assert layout["tower"][0]["action"] == "moved" and layout["tower"][0]["reason"] == "on top of a printing object"


def test_a_single_plate_control_with_a_valid_tower_is_byte_identical(tmp_path):
    src = rf.project(tmp_path, plates=1, bed=(270.0, 270.0), local=(135.5, 136.0))
    for mode in MODES:
        result = run(tmp_path, src, mode)
        cfg = rf.settings_of(result.output_path)
        assert result.settings_summary["layout"]["tower"][0]["action"] == "kept"
        if mode == "preserve":
            assert (cfg["wipe_tower_x"], cfg["wipe_tower_y"]) == (["13"], ["211"])        # the base's own values
        assert tokens(result.output_path) == tokens(src)


def test_no_free_position_is_reported_and_the_tower_left_alone(tmp_path):
    # a 250 mm tower leaves no room for any candidate on a 270 mm plate
    src = rf.project(tmp_path, plates=1, bed=(270.0, 270.0), local=(135.5, 136.0),
                     cfg={"wipe_tower_x": ["10"], "wipe_tower_y": ["10"], "prime_tower_width": "250"})
    result = run(tmp_path, src, "preserve")
    t = result.settings_summary["layout"]["tower"][0]
    assert t["action"] == "unresolved" and tower(result.output_path) == (["10"], ["10"])
    assert any("prime tower was left where it was" in w for w in result.settings_summary["warnings"])


def test_a_disabled_tower_is_not_touched(tmp_path):
    src = rf.project(tmp_path, plates=1, bed=(270.0, 270.0), local=(135.5, 136.0),
                     cfg={"enable_prime_tower": "0", "wipe_tower_x": ["900"], "wipe_tower_y": ["900"]})
    result = run(tmp_path, src, "preserve")
    assert result.settings_summary["layout"]["tower"] == []
    assert tower(result.output_path) == (["900"], ["900"])


# --- support intent ------------------------------------------------------------------------------

SUPPORT = ("enable_support", "support_type", "support_filament", "support_interface_filament")


def declared_first(path):
    return set(filter(None, rf.settings_of(path)["different_settings_to_system"][0].split(";")))


@pytest.mark.parametrize("intent", ["paint", "enforcer", "object"])
def test_explicit_support_intent_survives_the_starter_settings(tmp_path, intent):
    src = rf.project(tmp_path, plates=1, bed=(270.0, 270.0), local=(135.5, 136.0), supports=intent)
    result = run(tmp_path, src, "recommended")
    cfg = rf.settings_of(result.output_path)
    assert set(SUPPORT) <= declared_first(result.output_path)
    assert (cfg["enable_support"], cfg["support_type"], cfg["support_filament"]) == ("1", "tree(manual)", "2")
    stated = result.settings_summary["support_intent"]
    assert stated["kept"] is True and "kept as the creator set them" in stated["statement"]


def test_without_support_intent_the_starter_reset_is_intentional(tmp_path):
    src = rf.project(tmp_path, plates=1, bed=(270.0, 270.0), local=(135.5, 136.0))
    result = run(tmp_path, src, "recommended")
    assert not (set(SUPPORT) & declared_first(result.output_path))
    stated = result.settings_summary["support_intent"]
    assert stated["kept"] is False and "starter settings" in stated["statement"]


def test_preserve_keeps_the_creators_declarations_as_they_were(tmp_path):
    src = rf.project(tmp_path, plates=1, bed=(270.0, 270.0), local=(135.5, 136.0), supports="paint")
    result = run(tmp_path, src, "preserve")
    assert set(SUPPORT) <= declared_first(result.output_path)
    assert "support_intent" not in result.settings_summary or result.settings_summary["support_intent"] is None


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
