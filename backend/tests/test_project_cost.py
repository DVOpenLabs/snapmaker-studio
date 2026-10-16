"""Costing a project from its own recorded slicing result.

The point of this module is that it refuses to guess. These tests hold both
halves of that: when the file carries real figures the arithmetic must be right
and attributed, and when it does not the answer must be an explanation, never a
number.
"""
from __future__ import annotations

import json
import zipfile

from snapstudio_core import project_cost, project_traits


def _traits(plates, sliced=True):
    return {
        "is_sliced": {"value": sliced, "confidence": "confirmed", "evidence": "test"},
        "plate_predictions": plates,
    }


def _plate(index="1", seconds=3600.0, weight=100.0, filaments=None):
    return {
        "index": index,
        "predicted_seconds": seconds,
        "predicted_weight_g": weight,
        "filaments": filaments if filaments is not None else [
            {"id": "1", "type": "PLA", "color": "#FF0000", "used_g": 100.0, "used_m": 33.5},
        ],
    }


def test_costs_a_single_plate_from_the_file():
    out = project_cost.from_traits(_traits([_plate()]), price_per_kg=20.0)
    assert out["available"] is True
    assert out["grams"] == 100.0
    assert out["cost"] == 2.0            # 100 g at $20/kg
    assert out["hours"] == 1.0
    assert out["basis"] == project_cost.BASIS_SLICED


def test_totals_across_several_plates():
    out = project_cost.from_traits(_traits([
        _plate("1", 3600.0, 100.0),
        _plate("2", 1800.0, 50.0, [{"id": "1", "type": "PLA", "used_g": 50.0, "used_m": 17.0}]),
    ]), price_per_kg=20.0)
    assert out["plate_count"] == 2
    assert out["grams"] == 150.0
    assert out["cost"] == 3.0
    assert out["hours"] == 1.5


def test_per_material_prices_are_respected():
    """A plate that mixes cheap PLA with expensive support material must not be
    costed as if it were all one spool."""
    plate = _plate(filaments=[
        {"id": "1", "type": "PLA", "used_g": 100.0, "used_m": 33.0},
        {"id": "2", "type": "PVA", "used_g": 50.0, "used_m": 17.0},
    ], weight=150.0)
    out = project_cost.from_traits(_traits([plate]), price_per_kg=20.0,
                                   prices={"PVA": 80.0})
    # 100 g PLA at $20/kg = $2.00; 50 g PVA at $80/kg = $4.00
    assert out["cost"] == 6.0
    by_material = {m["material"]: m for m in out["by_material"]}
    assert by_material["PVA"]["cost"] == 4.0
    assert by_material["PLA"]["cost"] == 2.0
    # The costliest material leads, because that is the one worth changing.
    assert out["by_material"][0]["material"] == "PVA"


def test_material_price_lookup_is_case_insensitive():
    out = project_cost.from_traits(_traits([_plate()]), price_per_kg=20.0,
                                   prices={"pla": 40.0})
    assert out["cost"] == 4.0


def test_unpriced_material_falls_back_to_the_single_price():
    out = project_cost.from_traits(_traits([_plate()]), price_per_kg=25.0,
                                   prices={"ASA": 60.0})
    assert out["cost"] == 2.5


def test_unsliced_project_gets_an_explanation_not_a_number():
    out = project_cost.from_traits(_traits([], sliced=False))
    assert out["available"] is False
    assert out["cost"] if False else "cost" not in out
    assert "has not been sliced" in out["reason"]
    assert out["basis"] == project_cost.BASIS_NONE


def test_sliced_project_without_weights_says_so_differently():
    """"Sliced but no material figures" is a different problem from "not sliced",
    and the fix is different, so the message must be too."""
    out = project_cost.from_traits(_traits([_plate(weight=None, filaments=[])]))
    assert out["available"] is False
    assert "does not record how much" in out["reason"]


def test_recorded_plate_weight_wins_over_the_slot_breakdown():
    """The plate's own recorded weight is the authority; per-slot grams explain it."""
    plate = _plate(weight=120.0, filaments=[
        {"id": "1", "type": "PLA", "used_g": 100.0, "used_m": 33.0},
    ])
    out = project_cost.from_traits(_traits([plate]), price_per_kg=20.0)
    assert out["grams"] == 120.0
    assert out["plates"][0]["filaments"][0]["grams"] == 100.0


def test_missing_time_is_reported_as_unknown_not_zero():
    out = project_cost.from_traits(_traits([_plate(seconds=None)]))
    assert out["time_known"] is False
    assert out["hours"] is None
    assert "h of printing" not in out["summary"]


def test_zero_and_negative_prices_fall_back_to_the_default():
    for bad in (0, -5, None, "nonsense"):
        out = project_cost.from_traits(_traits([_plate()]), price_per_kg=bad)
        assert out["price_per_kg"] == project_cost.DEFAULT_PRICE_PER_KG


def test_summary_names_its_source():
    out = project_cost.from_traits(_traits([_plate()]))
    assert "own slicing result" in out["summary"]


def test_disclaimer_states_what_is_excluded():
    out = project_cost.from_traits(_traits([_plate()]))
    for excluded in ("electricity", "machine wear", "labour", "failed prints"):
        assert excluded in out["disclaimer"]


def test_end_to_end_from_a_real_file(tmp_path):
    slice_info = (
        "<config><plate>"
        "<metadata key='index' value='1'/>"
        "<metadata key='prediction' value='7200'/>"
        "<metadata key='weight' value='60'/>"
        "<filament id='1' type='PETG' color='#00FF00' used_m='20.1' used_g='60'/>"
        "</plate></config>"
    )
    p = tmp_path / "sliced.3mf"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("_rels/.rels", "<Relationships/>")
        z.writestr("3D/3dmodel.model", '<model unit="millimeter"><build/></model>')
        z.writestr("Metadata/project_settings.config",
                   json.dumps({"printer_model": "Snapmaker U1"}))
        z.writestr("Metadata/slice_info.config", slice_info)
        z.writestr("Metadata/plate_1.gcode", "G1 X0\n")
    out = project_cost.estimate(str(p), price_per_kg=30.0)
    assert out["available"] is True
    assert out["grams"] == 60.0
    assert out["cost"] == 1.8
    assert out["hours"] == 2.0
    assert out["by_material"][0]["material"] == "PETG"


def test_unreadable_file_does_not_raise(tmp_path):
    p = tmp_path / "junk.3mf"
    p.write_bytes(b"not a zip")
    out = project_cost.estimate(str(p))
    assert out["available"] is False


def test_traits_module_and_cost_module_agree_on_the_shape(tmp_path):
    """Guards the seam: cost reads exactly what traits writes."""
    p = tmp_path / "x.3mf"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("_rels/.rels", "<Relationships/>")
        z.writestr("3D/3dmodel.model", '<model unit="millimeter"><build/></model>')
        z.writestr("Metadata/slice_info.config",
                   "<config><plate><metadata key='weight' value='10'/>"
                   "<filament id='1' type='PLA' used_g='10' used_m='3'/></plate></config>")
    traits = project_traits.extract(str(p))
    assert project_cost.from_traits(traits)["grams"] == 10.0
